"""
SensingAgent — ingests earthquake events, classifies zones, elevates agent priorities,
and triggers RFP issuance from affected specialist agents.
Acts as the system's entry point for all disaster events.
"""

import asyncio
import dataclasses
import logging
from typing import Any, Dict, List, Optional

import config
from agents.base_agent import BaseAgent
from messaging.broker import MessageBroker
from messaging.message_types import (
    Bid, EarthquakeEvent, FireEvent, RFP, WebSocketEvent, ZoneStatus,
)
from negotiation.protocol import ContractNetProtocol
from simulation.city_model import CityModel
from simulation.earthquake import EarthquakeSimulator, _haversine_km
from simulation.fire_simulator import FireSimulator
from simulation.zone_classifier import ZoneClassifier

# ── Distance-band thresholds (metres) — must mirror ZoneCircle.jsx ───────────
# Earthquake: CRITICAL<3600m, HIGH<7000m, LOW<11000m, else SAFE
_EQ_BANDS_M   = (3_600, 7_000, 11_000)
# Fire: very tight — only the epicenter zone is CRITICAL, no HIGH band
# (bands[0]==bands[1] means HIGH is impossible), adjacent zones within 2.5km = LOW
_FIRE_BANDS_M = (500, 500, 2_500)

def _distance_class(dist_m: float, bands_m) -> str:
    """Classify a zone purely by its distance from the epicenter."""
    if dist_m < bands_m[0]: return "CRITICAL"
    if dist_m < bands_m[1]: return "HIGH"
    if dist_m < bands_m[2]: return "LOW"
    return "SAFE"


def _nearest_station(responder_type: str, target_lat: float, target_lon: float):
    """
    Find the closest physical utility station for a given responder type.
    Returns the station dict (id/name/lat/lon) or None if no stations defined.
    The frontend mirrors this same nearest-neighbor search visually.
    """
    stations = config.RESPONDER_LOCATIONS.get(responder_type, [])
    if not stations:
        return None
    return min(
        stations,
        key=lambda s: _haversine_km(s["lat"], s["lon"], target_lat, target_lon),
    )

logger = logging.getLogger(__name__)
_CNP = ContractNetProtocol()


class SensingAgent(BaseAgent):
    """
    Subscribes to earthquake events, computes zone severities,
    classifies zones, and triggers downstream agents to issue RFPs.
    """

    def __init__(
        self,
        broker: MessageBroker,
        city_model: CityModel,
        zone_classifier: ZoneClassifier,
        all_agents_ref: Dict,   # injected after all agents are created
    ) -> None:
        super().__init__(
            agent_id="sensing_agent",
            agent_type="sensing",
            broker=broker,
            initial_resources={},
            priority_weight=1.0,
        )
        self.city_model = city_model
        self.zone_classifier = zone_classifier
        self.simulator = EarthquakeSimulator()
        self.fire_simulator = FireSimulator()
        self.all_agents_ref = all_agents_ref
        self.current_zone_statuses: List[ZoneStatus] = []
        self.orchestrator = None  # set after orchestrator is initialized

    async def process_event(self, event: Any) -> None:
        """
        Handle an EarthquakeEvent dict (from broker callback) or EarthquakeEvent object.
        Runs the full pipeline: severity → classify → damage → notify → trigger RFPs.
        """
        if isinstance(event, dict):
            eq_event = EarthquakeEvent(**event)
        else:
            eq_event = event

        import logging as _logging
        _log = _logging.getLogger(__name__)

        _log.info("")
        _log.info("╔══════════════════════════════════════════════════════════════")
        _log.info("║ EARTHQUAKE DETECTED  M%.1f  epicenter=(%.4f, %.4f)  id=%s",
                  eq_event.magnitude, eq_event.epicenter_lat, eq_event.epicenter_lon, eq_event.event_id[:8])
        _log.info("╚══════════════════════════════════════════════════════════════")
        self.status = config.STATUS_ACTIVE

        # Compute severities and apply damage to city model
        severities = self.simulator.compute_zone_severities(eq_event, self.city_model)
        zone_statuses = self.simulator.apply_damage(eq_event, self.city_model, severities)

        # Classify → broadcast → elevate → trigger RFPs → dispatch
        await self._common_pipeline(
            zone_statuses, eq_event.event_id,
            calamity_type="EARTHQUAKE",
            epicenter_lat=eq_event.epicenter_lat,
            epicenter_lon=eq_event.epicenter_lon,
            dist_bands_m=_EQ_BANDS_M,
        )

        self.status = config.STATUS_IDLE

    async def process_fire_event(self, event: Any) -> None:
        """
        Handle a FireEvent dict or FireEvent object.
        Same pipeline as earthquake but uses the fire simulator's steep falloff.
        """
        if isinstance(event, dict):
            fire_event = FireEvent(**event)
        else:
            fire_event = event

        import logging as _logging
        _log = _logging.getLogger(__name__)

        _log.info("")
        _log.info("╔══════════════════════════════════════════════════════════════")
        _log.info("║ 🔥 FIRE DETECTED  intensity=%.1f  radius=%.2f km  epicenter=(%.4f, %.4f)  id=%s",
                  fire_event.intensity, fire_event.radius_km,
                  fire_event.epicenter_lat, fire_event.epicenter_lon, fire_event.event_id[:8])
        _log.info("╚══════════════════════════════════════════════════════════════")
        self.status = config.STATUS_ACTIVE

        # Compute severities with steep fire falloff and apply damage
        severities = self.fire_simulator.compute_zone_severities(fire_event, self.city_model)
        zone_statuses = self.fire_simulator.apply_damage(fire_event, self.city_model, severities)

        # Classify → broadcast → elevate → trigger RFPs → dispatch
        await self._common_pipeline(
            zone_statuses, fire_event.event_id,
            calamity_type="FIRE",
            epicenter_lat=fire_event.epicenter_lat,
            epicenter_lon=fire_event.epicenter_lon,
            dist_bands_m=_FIRE_BANDS_M,
        )

        self.status = config.STATUS_IDLE

    async def _common_pipeline(
        self,
        zone_statuses: List[ZoneStatus],
        event_id: str,
        calamity_type: str = "EARTHQUAKE",
        epicenter_lat: float = 0.0,
        epicenter_lon: float = 0.0,
        dist_bands_m: tuple = _EQ_BANDS_M,
    ) -> None:
        """
        Shared pipeline for all calamity types:
        classify → log → broadcast WS → elevate priorities → trigger RFPs → dispatch.

        Zone classification uses **distance from epicenter** (same bands as
        ZoneCircle.jsx) so the map and backend always agree.
        The ZoneClassifier's ML/weighted score is still run for logging but
        the distance-based result is authoritative.
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        # Build zone coordinate lookup for haversine
        zone_coords = {z["id"]: (z["lat"], z["lon"]) for z in config.CITY_ZONES}

        # Authoritative: distance-based classification (mirrors ZoneCircle.jsx)
        for zs in zone_statuses:
            lat, lon = zone_coords.get(zs.zone_id, (epicenter_lat, epicenter_lon))
            dist_km  = _haversine_km(epicenter_lat, epicenter_lon, lat, lon)
            dist_m   = dist_km * 1000.0
            zs.classification = _distance_class(dist_m, dist_bands_m)

        # Also run rule-based classifier for audit logging (not authoritative)
        classifications = {zs.zone_id: zs.classification for zs in zone_statuses}
        for zs in zone_statuses:
            rule_cls = self.zone_classifier.classify(zs)
            if rule_cls != zs.classification:
                _log.debug(
                    "[SENSING] Classifier override on %s: weighted=%s → distance=%s",
                    zs.zone_id, rule_cls, zs.classification,
                )

        self.current_zone_statuses = zone_statuses

        # Print zone assessment table
        _log.info("[SENSING] Zone damage assessment:")
        _log.info("  %-8s  %-20s  %-8s  %-10s  %-7s  %-5s", "Zone", "Name", "Severity", "Class", "Roads", "Power")
        _log.info("  " + "─" * 70)
        zone_names = {z["id"]: z["name"] for z in config.CITY_ZONES}
        for zs in sorted(zone_statuses, key=lambda z: z.severity_score, reverse=True):
            road_str = "BLOCKED" if zs.road_blocked else "OK"
            power_str = "OFF" if not zs.power_status else "ON"
            cls_marker = {"CRITICAL": "🔴", "HIGH": "🟠", "LOW": "🟡", "SAFE": "🟢"}.get(zs.classification, "")
            _log.info("  %-8s  %-20s  %-8.2f  %s %-8s  %-7s  %-5s",
                      zs.zone_id, zone_names.get(zs.zone_id, "?"),
                      zs.severity_score, cls_marker, zs.classification,
                      road_str, power_str)

        critical = [zs.zone_id for zs in zone_statuses if zs.classification == "CRITICAL"]
        high = [zs.zone_id for zs in zone_statuses if zs.classification == "HIGH"]
        _log.info("[SENSING] Summary: %d CRITICAL zones %s | %d HIGH zones %s",
                  len(critical), critical, len(high), high)

        # Publish zone_update WebSocket events — include lat/lon and calamity_type
        # so the frontend can adjust its rendering (e.g. smaller fire radius)
        zone_coords = {z["id"]: {"lat": z["lat"], "lon": z["lon"]}
                       for z in config.CITY_ZONES}
        for zs in zone_statuses:
            payload = dataclasses.asdict(zs)
            coords = zone_coords.get(zs.zone_id, {})
            payload["lat"] = coords.get("lat")
            payload["lon"] = coords.get("lon")
            payload["calamity_type"] = calamity_type
            ws_event = WebSocketEvent(event_type="zone_update", payload=payload)
            await self.broker.broadcast(ws_event)

        # Elevate priorities of agents whose zones are affected
        await self._elevate_priorities(zone_statuses, classifications)

        # Trigger RFP issuance from agents in CRITICAL/HIGH zones
        await self._trigger_rfps(zone_statuses, classifications, event_id, calamity_type)

        # Dispatch rescue units and broadcast routes to frontend
        await self._dispatch_rescue_units(zone_statuses)

    async def _dispatch_rescue_units(self, zone_statuses: List[ZoneStatus]) -> None:
        """
        Ask RescueCoordinator to assign units to all CRITICAL/HIGH zones
        and broadcast the assignments (with lat/lon waypoints) to the frontend.
        """
        rescue_coordinator = self.all_agents_ref.get("rescue_coordinator")
        if not rescue_coordinator:
            return

        priority_zones = [
            zs for zs in zone_statuses if zs.classification in ("CRITICAL", "HIGH")
        ]
        if not priority_zones:
            return

        ndrf = self.all_agents_ref.get("ndrf_agent")
        available = {"personnel": ndrf.resource_pool.get("personnel", 0)} if ndrf else {"personnel": 30}

        assignments = rescue_coordinator.coordinate_dispatch(priority_zones, available)
        await rescue_coordinator.broadcast_dispatch(assignments)

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """SensingAgent never bids on resource RFPs."""
        return None

    async def _elevate_priorities(
        self, zone_statuses: List[ZoneStatus], classifications: Dict[str, str]
    ) -> None:
        """Increase priority_weight for agents associated with CRITICAL/HIGH zones."""
        critical_zones = {zs.zone_id for zs in zone_statuses if zs.classification in ("CRITICAL", "HIGH")}
        for agent_id, agent in self.all_agents_ref.items():
            if agent_id == self.agent_id:
                continue
            # Bump all active response agents when critical zones exist
            if critical_zones and hasattr(agent, "priority_weight"):
                if agent.agent_type in ("ndrf", "hospital", "fire", "police"):
                    agent.priority_weight = min(3.0, agent.priority_weight * 1.5)
                    self._log(f"Elevated {agent_id} priority to {agent.priority_weight:.2f}")

    async def _trigger_rfps(
        self,
        zone_statuses: List[ZoneStatus],
        classifications: Dict[str, str],
        event_id: str,
        calamity_type: str = "EARTHQUAKE",
    ) -> None:
        """
        Generalized dispatch — for *any* epicenter, identify CRITICAL/HIGH
        zones and route specialist agents to them. Each zone is matched to
        the nearest physical utility station of each responder type
        (frontend mirrors this visually with AnimatedRoutes).

        Hospital is no longer pinned to Zone-B; it responds to whichever
        priority zones lost power. Fire and police respond to every
        priority zone regardless of calamity type. NDRF is reserved for
        CRITICAL zones to keep the RFP volume sane.
        """
        if self.orchestrator is None:
            self._log("No orchestrator set — skipping RFP triggers")
            return

        import logging as _logging
        _log = _logging.getLogger(__name__)
        _log.info("[SENSING] Dispatching alerts to specialist agents (calamity=%s)...", calamity_type)

        hospital_agent = self.all_agents_ref.get("hospital_agent")
        ndrf_agent     = self.all_agents_ref.get("ndrf_agent")
        fire_agent     = self.all_agents_ref.get("fire_agent")
        police_agent   = self.all_agents_ref.get("police_agent")

        zone_coords = {z["id"]: (z["lat"], z["lon"]) for z in config.CITY_ZONES}

        critical_zones = [zs for zs in zone_statuses if zs.classification == "CRITICAL"]
        high_zones     = [zs for zs in zone_statuses if zs.classification == "HIGH"]
        priority_zones = critical_zones + high_zones

        if not priority_zones:
            _log.info("[SENSING] No CRITICAL or HIGH zones — no specialist dispatch required")
            return

        _log.info("[SENSING] Priority zones: %d CRITICAL %s | %d HIGH %s",
                  len(critical_zones), [z.zone_id for z in critical_zones],
                  len(high_zones),     [z.zone_id for z in high_zones])

        def _dispatch_from_nearest(resp_type: str, zs: ZoneStatus, label: str) -> None:
            """Log which station is closest — keeps backend story aligned with frontend visuals."""
            lat, lon = zone_coords.get(zs.zone_id, (0.0, 0.0))
            station = _nearest_station(resp_type, lat, lon)
            if station:
                _log.info("[SENSING] → %s dispatched to %s (%s) from %s [%s]",
                          label, zs.zone_id, zs.classification, station["name"], station["id"])
            else:
                _log.info("[SENSING] → %s dispatched to %s (%s)", label, zs.zone_id, zs.classification)

        # ── Fire suppression + police crowd control ─ every priority zone ──
        for zs in priority_zones:
            if fire_agent:
                _dispatch_from_nearest("fire", zs, "fire_agent")
                await fire_agent.on_critical_zone(zs, self.orchestrator)

            if police_agent:
                _dispatch_from_nearest("police", zs, "police_agent (crowd control)")
                police_agent.assign_crowd_control(zs.zone_id)

            # Hospital ambulance — only if power is out at the zone (RFP for power)
            if hospital_agent and not zs.power_status:
                _dispatch_from_nearest("hospital", zs, "hospital_agent (ambulance)")
                await hospital_agent.on_critical_zone(zs, self.orchestrator)

        # ── NDRF heavy rescue ─ CRITICAL zones only ──────────────────────
        for zs in critical_zones:
            if ndrf_agent:
                _dispatch_from_nearest("ndrf", zs, "ndrf_agent")
                await ndrf_agent.on_affected_zone(zs, self.orchestrator)

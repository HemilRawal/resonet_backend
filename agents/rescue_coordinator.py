"""
RescueCoordinator — dispatches NDRF/Fire/Police units across zones.
Does not hold its own resources; coordinates other agents' deployments.
Decides AERIAL vs LAND routing based on road status and ETA.
"""

import asyncio
import dataclasses
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from agents.base_agent import BaseAgent
from messaging.broker import MessageBroker
from messaging.message_types import Bid, RFP, WebSocketEvent, ZoneStatus
from simulation.city_model import CityModel

logger = logging.getLogger(__name__)


class RescueCoordinator(BaseAgent):
    """Coordinates multi-agency rescue dispatch without holding direct resources."""

    def __init__(self, broker: MessageBroker, city_model: CityModel) -> None:
        super().__init__(
            agent_id="rescue_coordinator",
            agent_type="rescue_coordinator",
            broker=broker,
            initial_resources={},
            priority_weight=1.8,
        )
        self.city_model = city_model
        self.dispatch_log: List[Dict] = []

    async def process_event(self, event: Any) -> None:
        self._log("Earthquake event received — ready for dispatch coordination")

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """RescueCoordinator does not hold resources — never bids."""
        return None

    def decide_rescue_mode(
        self, zone_status: ZoneStatus, source_zone: str = "Zone-A"
    ) -> Tuple[str, float, Optional[List[Dict]]]:
        """
        Determine whether to dispatch AERIAL or LAND units to a zone.
        Returns: (mode, eta_minutes, waypoints_or_None)

        waypoints is a list of {zone_id, lat, lon} dicts so Leaflet can draw the route.
        AERIAL if: road blocked OR land ETA > AERIAL_ETA_THRESHOLD.
        LAND with shortest NetworkX path otherwise.
        """
        zone_id = zone_status.zone_id

        # Stub ETA: severity × 40 minutes (simulates congestion + distance)
        land_eta_stub = zone_status.severity_score * 40.0

        if zone_status.road_blocked or land_eta_stub > config.AERIAL_ETA_THRESHOLD:
            aerial_eta = land_eta_stub * 0.4
            return ("AERIAL", round(aerial_eta, 1), None)

        # Attempt real NetworkX routing
        path_ids = self.city_model.shortest_path(source_zone, zone_id)
        if path_ids:
            land_eta = self.city_model.path_travel_time(path_ids)
            if land_eta > config.AERIAL_ETA_THRESHOLD:
                return ("AERIAL", round(land_eta * 0.4, 1), None)
            waypoints = self._path_to_waypoints(path_ids)
            return ("LAND", round(land_eta, 1), waypoints)

        # Fallback: no path found → aerial
        return ("AERIAL", round(land_eta_stub * 0.4, 1), None)

    def _path_to_waypoints(self, zone_ids: List[str]) -> List[Dict]:
        """Convert a list of zone IDs to [{zone_id, lat, lon}] for Leaflet polylines."""
        waypoints = []
        for zid in zone_ids:
            node = self.city_model.G.nodes.get(zid, {})
            if node:
                waypoints.append({
                    "zone_id": zid,
                    "lat": node.get("lat"),
                    "lon": node.get("lon"),
                })
        return waypoints

    def coordinate_dispatch(
        self,
        zone_priority_list: List[ZoneStatus],
        available_units: Dict[str, int],
    ) -> Dict[str, Dict]:
        """
        Assign available units across zones by priority.
        Returns {zone_id: {mode, eta, units_assigned, path}}.
        """
        assignments: Dict[str, Dict] = {}
        remaining = dict(available_units)

        for zone_status in sorted(zone_priority_list, key=lambda z: z.severity_score, reverse=True):
            if sum(remaining.values()) <= 0:
                break

            mode, eta, path = self.decide_rescue_mode(zone_status)
            units_to_assign = min(remaining.get("personnel", 0), 10)
            if units_to_assign > 0:
                remaining["personnel"] = remaining.get("personnel", 0) - units_to_assign

            assignments[zone_status.zone_id] = {
                "mode": mode,
                "eta_minutes": eta,
                "units_assigned": units_to_assign,
                "path": path,
                "classification": zone_status.classification,
            }
            self._log(f"Zone {zone_status.zone_id}: {mode} mode, ETA={eta}min, units={units_to_assign}")

        self.dispatch_log.append(assignments)
        return assignments

    async def broadcast_dispatch(self, assignments: Dict) -> None:
        """Push dispatch assignments to WebSocket clients."""
        ws_event = WebSocketEvent(
            event_type="dispatch",
            payload={"assignments": assignments},
        )
        await self.broker.broadcast(ws_event)

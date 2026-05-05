"""
Fire event simulator for DACRO.
Computes per-zone severity using haversine distance from the fire origin,
with a *very steep* falloff — only the epicenter and immediately adjacent
zones will be affected.  Everything else stays SAFE.

The reusable _haversine_km function is imported from earthquake.py to
avoid duplication.
"""

import logging
import math
import uuid
from typing import Dict, List

import config
from messaging.message_types import FireEvent, ZoneStatus
from simulation.city_model import CityModel
from simulation.earthquake import _haversine_km  # shared utility

logger = logging.getLogger(__name__)

# Default fire parameters — can be overridden per-call
_DEFAULT_FIRE_INTENSITY = 5.0   # analogous to magnitude, controls radius
_DEFAULT_FIRE_RADIUS_KM = 1.5   # damage drops to zero at this distance


class FireSimulator:
    """Generates fire events and computes their localised effect on the city graph."""

    def generate_event(
        self,
        lat: float,
        lon: float,
        intensity: float = _DEFAULT_FIRE_INTENSITY,
        radius_km: float = _DEFAULT_FIRE_RADIUS_KM,
    ) -> FireEvent:
        """Create a new FireEvent with a unique ID."""
        event = FireEvent(
            epicenter_lat=lat,
            epicenter_lon=lon,
            intensity=intensity,
            radius_km=radius_km,
            event_id=str(uuid.uuid4()),
        )
        logger.info(
            "FireSimulator: generated event %s (intensity=%.1f, radius=%.2f km @ %.4f, %.4f)",
            event.event_id, intensity, radius_km, lat, lon,
        )
        return event

    def compute_zone_severities(
        self, event: FireEvent, city_model: CityModel
    ) -> Dict[str, float]:
        """
        Compute severity score per zone with extremely steep falloff.
        Formula:  severity = max(0.0, 1.0 − (dist_km / radius_km))
        Only the epicenter zone (~0 km) scores near 1.0; zones beyond
        radius_km score 0.0 (SAFE).
        """
        severities: Dict[str, float] = {}
        for zone in city_model.get_all_zones():
            dist_km = _haversine_km(
                event.epicenter_lat, event.epicenter_lon,
                zone["lat"], zone["lon"],
            )
            severity = max(0.0, 1.0 - (dist_km / event.radius_km))
            severities[zone["id"]] = round(severity, 4)
            logger.debug(
                "Zone %s: dist=%.2f km, fire-severity=%.4f", zone["id"], dist_km, severity
            )
        return severities

    def apply_damage(
        self,
        event: FireEvent,
        city_model: CityModel,
        zone_severities: Dict[str, float],
    ) -> List[ZoneStatus]:
        """
        Apply fire damage to zones with severity > 0.6.
        Returns a list of ZoneStatus objects reflecting post-fire state.
        """
        zone_statuses: List[ZoneStatus] = []
        for zone in city_model.get_all_zones():
            zone_id = zone["id"]
            severity = zone_severities.get(zone_id, 0.0)
            road_blocked = False
            power_status = True

            if severity > 0.6:
                city_model.block_road(zone_id)
                road_blocked = True
                city_model.set_zone_power(zone_id, False)
                power_status = False
                logger.warning(
                    "Zone %s FIRE DAMAGE: severity=%.2f — roads blocked, power cut",
                    zone_id, severity,
                )

            zone_statuses.append(
                ZoneStatus(
                    zone_id=zone_id,
                    severity_score=severity,
                    classification="UNCLASSIFIED",  # ZoneClassifier will fill this
                    population_density=zone["population_density"],
                    has_critical_infra=zone["has_critical_infra"],
                    road_blocked=road_blocked,
                    power_status=power_status,
                )
            )
        return zone_statuses

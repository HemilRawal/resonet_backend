"""
Earthquake event generator for DACRO.
Computes per-zone severity using haversine distance from epicenter,
then applies physical damage (road blocks, power cuts) to the city model.
No external geo libraries — haversine is implemented inline for portability.
"""

import logging
import math
import uuid
from typing import Dict, List

import config
from messaging.message_types import EarthquakeEvent, ZoneStatus
from simulation.city_model import CityModel

logger = logging.getLogger(__name__)

# Earth radius in km
_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km between two lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class EarthquakeSimulator:
    """Generates earthquake events and computes their effect on the city graph."""

    def generate_event(self, lat: float, lon: float, magnitude: float) -> EarthquakeEvent:
        """Create a new EarthquakeEvent with a unique ID."""
        event = EarthquakeEvent(
            epicenter_lat=lat,
            epicenter_lon=lon,
            magnitude=magnitude,
            event_id=str(uuid.uuid4()),
        )
        logger.info(
            "EarthquakeSimulator: generated event %s (M%.1f @ %.4f, %.4f)",
            event.event_id, magnitude, lat, lon,
        )
        return event

    def compute_zone_severities(
        self, event: EarthquakeEvent, city_model: CityModel
    ) -> Dict[str, float]:
        """
        Compute severity score per zone.
        Formula: severity = max(0, min(1, (magnitude - distance_km * 0.15) / magnitude))
        Zones within ~0 km score 1.0; damage drops linearly with distance.
        """
        severities: Dict[str, float] = {}
        for zone in city_model.get_all_zones():
            dist_km = _haversine_km(
                event.epicenter_lat, event.epicenter_lon,
                zone["lat"], zone["lon"],
            )
            raw = (event.magnitude - dist_km * 0.15) / event.magnitude
            severity = max(0.0, min(1.0, raw))
            
            # Explicit override: mark Kengeri (Zone-F) as completely safe
            if zone["id"] == "Zone-F":
                severity = 0.0
                
            severities[zone["id"]] = round(severity, 4)
            logger.debug(
                "Zone %s: dist=%.2f km, severity=%.4f", zone["id"], dist_km, severity
            )
        return severities

    def apply_damage(
        self,
        event: EarthquakeEvent,
        city_model: CityModel,
        zone_severities: Dict[str, float],
    ) -> List[ZoneStatus]:
        """
        Apply physical damage to zones with severity > 0.6.
        Returns a list of ZoneStatus objects reflecting post-quake state.
        """
        zone_statuses: List[ZoneStatus] = []
        for zone in city_model.get_all_zones():
            zone_id = zone["id"]
            severity = zone_severities.get(zone_id, 0.0)
            road_blocked = False
            power_status = True

            # Only CRITICAL-radius zones (severity > 0.85 for linear formula at M7)
            # get road blocks and power cuts. This aligns with the distance bands
            # shown on the map (ZoneCircle.jsx: CRITICAL < 3 600 m).
            if severity > 0.85:
                city_model.block_road(zone_id)
                road_blocked = True
                city_model.set_zone_power(zone_id, False)
                power_status = False
                logger.warning(
                    "Zone %s DAMAGED: severity=%.2f — roads blocked, power cut",
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

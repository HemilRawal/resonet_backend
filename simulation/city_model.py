"""
City graph model for DACRO — 12 pre-seeded zones with connectivity and infrastructure data.
Uses NetworkX DiGraph so routing and edge-weight manipulation (road damage) are trivial.
"""

import logging
from typing import Any, Dict, List, Optional

import networkx as nx

import config

logger = logging.getLogger(__name__)


class CityModel:
    """
    Directed graph of city zones loaded from config.CITY_ZONES.
    Edges represent navigable roads with travel_time weights.
    Road damage is modelled by inflating edge weights, not removing edges.
    """

    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()
        self._zone_power: Dict[str, bool] = {}
        self._load_zones()

    def _load_zones(self) -> None:
        for zone in config.CITY_ZONES:
            self.G.add_node(
                zone["id"],
                name=zone["name"],
                lat=zone["lat"],
                lon=zone["lon"],
                population_density=zone["population_density"],
                has_critical_infra=zone["has_critical_infra"],
                connected_zones=zone["connected_zones"],
                road_blocked=False,
            )
            self._zone_power[zone["id"]] = True  # all zones start with power

        for zone in config.CITY_ZONES:
            for neighbor_id in zone["connected_zones"]:
                self.G.add_edge(
                    zone["id"],
                    neighbor_id,
                    travel_time=config.DEFAULT_EDGE_TRAVEL_TIME,
                )
        logger.info("CityModel loaded %d zones, %d edges", self.G.number_of_nodes(), self.G.number_of_edges())

    # ------------------------------------------------------------------
    # Zone accessors
    # ------------------------------------------------------------------

    def get_zone(self, zone_id: str) -> Optional[Dict[str, Any]]:
        """Return all attributes of a zone node, or None if not found."""
        if zone_id not in self.G:
            return None
        data = dict(self.G.nodes[zone_id])
        data["id"] = zone_id
        data["power_status"] = self._zone_power.get(zone_id, True)
        return data

    def get_all_zones(self) -> List[Dict[str, Any]]:
        """Return all zone attribute dicts."""
        return [self.get_zone(z) for z in self.G.nodes]

    # ------------------------------------------------------------------
    # Damage application
    # ------------------------------------------------------------------

    def block_road(self, zone_id: str) -> None:
        """
        Mark a zone's roads as blocked by dramatically inflating edge weights.
        Does not remove edges — routing still works, just returns very high ETAs.
        """
        if zone_id not in self.G:
            return
        self.G.nodes[zone_id]["road_blocked"] = True
        for u, v in list(self.G.edges(zone_id)):
            self.G[u][v]["travel_time"] = config.BLOCKED_ROAD_TRAVEL_TIME
        for u, v in list(self.G.in_edges(zone_id)):
            self.G[u][v]["travel_time"] = config.BLOCKED_ROAD_TRAVEL_TIME
        logger.info("CityModel: roads blocked in %s", zone_id)

    def set_zone_power(self, zone_id: str, status: bool) -> None:
        """Set power on/off for a zone."""
        self._zone_power[zone_id] = status
        logger.info("CityModel: power %s for %s", "ON" if status else "OFF", zone_id)

    def is_road_blocked(self, zone_id: str) -> bool:
        return self.G.nodes.get(zone_id, {}).get("road_blocked", False)

    def get_power_status(self, zone_id: str) -> bool:
        return self._zone_power.get(zone_id, True)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        """Return shortest path by travel_time, or None if unreachable."""
        try:
            return nx.shortest_path(self.G, source, target, weight="travel_time")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def path_travel_time(self, path: List[str]) -> float:
        """Total travel time in minutes for a given path."""
        total = 0.0
        for i in range(len(path) - 1):
            edge_data = self.G.get_edge_data(path[i], path[i + 1])
            total += edge_data.get("travel_time", config.DEFAULT_EDGE_TRAVEL_TIME) if edge_data else config.DEFAULT_EDGE_TRAVEL_TIME
        return total

    # ------------------------------------------------------------------
    # Serialisation for API / WebSocket
    # ------------------------------------------------------------------

    def get_zone_graph_json(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of the full graph."""
        nodes = []
        for zone_id in self.G.nodes:
            data = self.get_zone(zone_id)
            nodes.append(data)

        edges = []
        for u, v, attrs in self.G.edges(data=True):
            edges.append({"source": u, "target": v, "travel_time": attrs.get("travel_time", config.DEFAULT_EDGE_TRAVEL_TIME)})

        return {"nodes": nodes, "edges": edges}

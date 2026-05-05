"""
FastAPI REST routes for DACRO.
All simulation triggers, state queries, and agent management endpoints live here.
The application state (agents, city_model, etc.) is accessed via app.state.
"""

import dataclasses
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import config
from messaging.message_types import EarthquakeEvent, FireEvent, WebSocketEvent
from simulation.earthquake import EarthquakeSimulator
from simulation.fire_simulator import FireSimulator

logger = logging.getLogger(__name__)
router = APIRouter()
_simulator = EarthquakeSimulator()
_fire_simulator = FireSimulator()


# ------------------------------------------------------------------
# Request bodies
# ------------------------------------------------------------------

class EarthquakeBody(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    magnitude: Optional[float] = None
    zone_id: Optional[str] = None


class FireBody(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    intensity: Optional[float] = None
    radius_km: Optional[float] = None
    zone_id: Optional[str] = None


class PriorityBody(BaseModel):
    weight: float


# ------------------------------------------------------------------
# Health & State
# ------------------------------------------------------------------

@router.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    state = request.app.state
    redis_ok = not state.broker.use_fallback
    return {
        "status": "ok",
        "agents": len(state.all_agents),
        "redis": redis_ok,
    }


@router.get("/state")
async def get_state(request: Request) -> Dict[str, Any]:
    state = request.app.state
    agent_states = {aid: dataclasses.asdict(a.get_state()) for aid, a in state.all_agents.items()}
    zone_states = state.city_model.get_all_zones()
    decisions = state.decision_log.get_decisions(limit=10)
    return {
        "agents": agent_states,
        "zones": zone_states,
        "recent_decisions": decisions,
    }


@router.get("/decisions")
async def get_decisions(request: Request, limit: int = 20) -> Dict[str, Any]:
    state = request.app.state
    decisions = state.decision_log.get_decisions(limit=limit)
    return {"decisions": decisions, "count": len(decisions)}


@router.get("/zones")
async def get_zones(request: Request) -> Dict[str, Any]:
    state = request.app.state
    zones = state.city_model.get_all_zones()
    return {"zones": zones}


# ------------------------------------------------------------------
# Simulation triggers
# ------------------------------------------------------------------

@router.post("/simulate/earthquake")
async def simulate_earthquake(request: Request, body: EarthquakeBody = EarthquakeBody()) -> Dict[str, Any]:
    """
    Trigger a full earthquake simulation cycle. Caller can supply lat/lon/zone_id
    from any zone popup — when omitted, falls back to the demo seed.
    """
    state = request.app.state
    lat = body.lat if body.lat is not None else config.DEMO_EARTHQUAKE["epicenter_lat"]
    lon = body.lon if body.lon is not None else config.DEMO_EARTHQUAKE["epicenter_lon"]
    magnitude = body.magnitude if body.magnitude is not None else config.DEMO_EARTHQUAKE["magnitude"]
    zone_id = body.zone_id if body.zone_id is not None else config.DEMO_EARTHQUAKE["epicenter_zone"]

    event = _simulator.generate_event(lat, lon, magnitude)
    # Call process_event directly — broker publish is for external consumers only
    await state.sensing_agent.process_event(event)

    return {
        "scenario": "earthquake",
        "event_id": event.event_id,
        "calamity_type": "EARTHQUAKE",
        "epicenter_zone": zone_id,
        "magnitude": magnitude,
        "epicenter_lat": lat,
        "epicenter_lon": lon,
    }


@router.post("/simulate/scenario/hospital-earthquake")
async def simulate_hospital_earthquake(
    request: Request, body: EarthquakeBody = EarthquakeBody()
) -> Dict[str, Any]:
    """
    Trigger an earthquake scenario. If lat/lon/zone_id are supplied (e.g. from
    a zone popup click), the epicenter is fixed there. Otherwise the pre-seeded
    demo seed is used with slight ± randomisation so each run varies.
    """
    import random
    state = request.app.state
    demo = config.DEMO_EARTHQUAKE

    if body.lat is not None and body.lon is not None:
        lat = body.lat
        lon = body.lon
        zone_id = body.zone_id or demo["epicenter_zone"]
        magnitude = body.magnitude if body.magnitude is not None else demo["magnitude"]
    else:
        magnitude = round(demo["magnitude"] + random.uniform(-0.3, 0.3), 1)
        lat = round(demo["epicenter_lat"] + random.uniform(-0.015, 0.015), 4)
        lon = round(demo["epicenter_lon"] + random.uniform(-0.015, 0.015), 4)
        zone_id = demo["epicenter_zone"]

    event = _simulator.generate_event(lat, lon, magnitude)
    await state.sensing_agent.process_event(event)
    return {
        "scenario": "hospital-earthquake",
        "event_id": event.event_id,
        "calamity_type": "EARTHQUAKE",
        "epicenter_zone": zone_id,
        "magnitude": magnitude,
        "epicenter_lat": lat,
        "epicenter_lon": lon,
    }


@router.post("/simulate/scenario/fire")
async def simulate_fire(request: Request, body: FireBody = FireBody()) -> Dict[str, Any]:
    """
    Trigger a fire simulation with steep severity falloff.
    Caller can supply lat/lon/zone_id from any zone popup; falls back to the
    demo seed (Zone-I / Mahalakshmi Layout) when omitted.
    """
    state = request.app.state
    demo = config.DEMO_FIRE
    lat       = body.lat       if body.lat       is not None else demo["epicenter_lat"]
    lon       = body.lon       if body.lon       is not None else demo["epicenter_lon"]
    intensity = body.intensity if body.intensity is not None else demo["intensity"]
    radius_km = body.radius_km if body.radius_km is not None else demo["radius_km"]
    zone_id   = body.zone_id   if body.zone_id   is not None else demo["epicenter_zone"]

    event = _fire_simulator.generate_event(lat, lon, intensity, radius_km)
    await state.sensing_agent.process_fire_event(event)

    return {
        "scenario": "fire",
        "event_id": event.event_id,
        "calamity_type": "FIRE",
        "epicenter_zone": zone_id,
        "intensity": intensity,
        "radius_km": radius_km,
        "epicenter_lat": lat,
        "epicenter_lon": lon,
    }


# ------------------------------------------------------------------
# Reset — restores city and agents to pre-earthquake state
# ------------------------------------------------------------------

@router.post("/simulate/reset")
async def reset_simulation(request: Request) -> Dict[str, Any]:
    """
    Reset city graph and all agent resource pools to initial state.
    Essential for re-running the demo without restarting the server.
    """
    import config as cfg
    state = request.app.state

    # Rebuild city model from scratch (clears road blocks and power cuts)
    from simulation.city_model import CityModel
    new_city = CityModel()
    state.city_model = new_city
    state.sensing_agent.city_model = new_city
    state.sensing_agent.simulator.city_model = new_city if hasattr(state.sensing_agent.simulator, "city_model") else None
    state.orchestrator.city_model = new_city

    # Restore agent resources and status
    for agent_id, agent in state.all_agents.items():
        initial = cfg.AGENT_INITIAL_RESOURCES.get(agent.agent_type, {})
        agent.resource_pool = dict(initial)
        agent.current_load = 0.0
        agent.status = cfg.STATUS_IDLE
        agent.priority_weight = {
            "hospital": 2.0, "ndrf": 2.0, "fire": 1.5,
            "police": 1.2, "power": 1.2, "rescue_coordinator": 1.8,
        }.get(agent.agent_type, 1.0)

    # Reset NDRF-specific state
    ndrf = state.all_agents.get("ndrf_agent")
    if ndrf:
        ndrf.deployed_units = {}
        ndrf._power_rfp_issued = False

    # Reset fire-specific state
    fire = state.all_agents.get("fire_agent")
    if fire:
        fire.deployed_zones = []

    # Reset police-specific state
    police = state.all_agents.get("police_agent")
    if police:
        police.crowd_control_zones = []

    # Reset hospital patient load
    hospital = state.all_agents.get("hospital_agent")
    if hospital:
        hospital.patient_load = 0.0

    # Broadcast updated agent states to frontend
    for agent_id, agent in state.all_agents.items():
        agent_state = dataclasses.asdict(agent.get_state())
        ws_event = WebSocketEvent(event_type="agent_state", payload=agent_state)
        await state.broker.broadcast(ws_event)

    return {"status": "reset", "message": "City and all agents restored to initial state"}


# ------------------------------------------------------------------
# Agent management
# ------------------------------------------------------------------

@router.post("/agents/{agent_id}/priority")
async def set_agent_priority(
    agent_id: str, body: PriorityBody, request: Request
) -> Dict[str, Any]:
    state = request.app.state
    agent = state.all_agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    agent.priority_weight = max(0.1, min(5.0, body.weight))
    return {"agent_id": agent_id, "new_priority_weight": agent.priority_weight}


# ------------------------------------------------------------------
# WebSocket
# ------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, request: Request = None) -> None:
    app = websocket.app
    ws_manager = app.state.ws_manager
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive — clients can send pings, we echo back
            data = await websocket.receive_text()
            await websocket.send_text(f'{{"echo": "{data}"}}')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

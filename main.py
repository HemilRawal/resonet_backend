"""
DACRO FastAPI application entrypoint.
Initialises all subsystems on startup, wires the agent network, and mounts routes.
CORS enabled for all origins so the React/Leaflet frontend can connect.
"""

import asyncio
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from agents.fire_agent import FireAgent
from agents.hospital_agent import HospitalAgent
from agents.ndrf_agent import NDRFAgent
from agents.police_agent import PoliceAgent
from agents.policy_agent import PolicyAgent
from agents.power_agent import PowerAgent
from agents.rescue_coordinator import RescueCoordinator
from agents.sensing_agent import SensingAgent
from agents.xai_agent import XAIAgent
from api.routes import router
from api.websocket import WebSocketManager
from messaging.broker import MessageBroker
from negotiation.orchestrator import NegotiationOrchestrator
from persistence.decision_log import DecisionLog
from simulation.city_model import CityModel
from simulation.zone_classifier import ZoneClassifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ------------------------------------------------------------------
    # STARTUP
    # ------------------------------------------------------------------
    logger.info("DACRO: initialising subsystems...")

    # Infrastructure
    broker = MessageBroker()
    await broker.connect()

    city_model = CityModel()
    decision_log = DecisionLog()
    zone_classifier = ZoneClassifier()  # trains ML model on init

    # WebSocket manager (must exist before routes handle /ws)
    ws_manager = WebSocketManager()

    # Wire broker broadcasts to WebSocket so all events reach the frontend
    async def _ws_broadcast_callback(message: dict):
        await ws_manager.broadcast(message)

    await broker.subscribe(config.CHANNEL_BROADCAST, _ws_broadcast_callback)

    # Concrete agents
    power_agent = PowerAgent(broker)
    hospital_agent = HospitalAgent(broker)
    fire_agent = FireAgent(broker)
    police_agent = PoliceAgent(broker)
    ndrf_agent = NDRFAgent(broker)
    rescue_coordinator = RescueCoordinator(broker, city_model)
    policy_agent = PolicyAgent(broker)
    xai_agent = XAIAgent(broker, decision_log)

    all_agents = {
        "power_agent": power_agent,
        "hospital_agent": hospital_agent,
        "fire_agent": fire_agent,
        "police_agent": police_agent,
        "ndrf_agent": ndrf_agent,
        "rescue_coordinator": rescue_coordinator,
        "policy_agent": policy_agent,
        "xai_agent": xai_agent,
    }

    # SensingAgent needs a reference to all other agents
    sensing_agent = SensingAgent(broker, city_model, zone_classifier, all_agents)
    all_agents["sensing_agent"] = sensing_agent

    # Orchestrator
    orchestrator = NegotiationOrchestrator(
        broker=broker,
        city_model=city_model,
        decision_log=decision_log,
        all_agents=all_agents,
        xai_agent=xai_agent,
        policy_agent=policy_agent,
    )

    # Give SensingAgent a reference to the orchestrator so it can trigger RFPs
    sensing_agent.orchestrator = orchestrator

    # Subscribe SensingAgent to earthquake channel
    async def _earthquake_callback(message: dict):
        await sensing_agent.process_event(message)

    await broker.subscribe(config.CHANNEL_EARTHQUAKE, _earthquake_callback)

    # Attach everything to app.state for route handlers
    app.state.broker = broker
    app.state.city_model = city_model
    app.state.decision_log = decision_log
    app.state.all_agents = all_agents
    app.state.sensing_agent = sensing_agent
    app.state.orchestrator = orchestrator
    app.state.ws_manager = ws_manager

    agent_count = len(all_agents)
    logger.info("DACRO system initialised — %d agents online", agent_count)

    yield  # application runs here

    # ------------------------------------------------------------------
    # SHUTDOWN
    # ------------------------------------------------------------------
    logger.info("DACRO: shutting down...")
    await broker.close()
    decision_log.close()
    logger.info("DACRO: shutdown complete")


# ------------------------------------------------------------------
# Application factory
# ------------------------------------------------------------------
app = FastAPI(
    title="DACRO — Decentralised Autonomous Crisis Resource Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

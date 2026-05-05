"""
FireAgent — manages fire suppression resources.
Based in Zone-F; dispatches to CRITICAL zones, bids on personnel and vehicle RFPs.
"""

import logging
from typing import Any, Optional

import config
from agents.base_agent import BaseAgent
from messaging.broker import MessageBroker
from messaging.message_types import Bid, RFP, ZoneStatus
from negotiation.protocol import ContractNetProtocol

logger = logging.getLogger(__name__)
_CNP = ContractNetProtocol()

_FIRE_STATION_ZONE = "Zone-F"


class FireAgent(BaseAgent):
    """Controls fire suppression vehicles, personnel, and water units."""

    def __init__(self, broker: MessageBroker) -> None:
        super().__init__(
            agent_id="fire_agent",
            agent_type="fire",
            broker=broker,
            initial_resources=dict(config.AGENT_INITIAL_RESOURCES["fire"]),
            priority_weight=1.5,
        )
        self.deployed_zones: list = []

    async def process_event(self, event: Any) -> None:
        self._log("Earthquake event received — standing by for dispatch")
        self.status = config.STATUS_ACTIVE

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """Bid on fire-relevant resource RFPs when surplus exists."""
        if not self.can_bid():
            return None

        resource = rfp.resource_type
        if resource == "personnel":
            surplus = self.resource_pool.get("personnel", 0) - 10
        elif resource == "vehicles":
            surplus = self.resource_pool.get("vehicles", 0) - 2
        elif resource == "water_units":
            surplus = self.resource_pool.get("water_units", 0) - 50
        else:
            return None

        if surplus <= 0:
            return None

        offered = min(surplus, rfp.amount_needed)
        return _CNP.create_bid(rfp, self.agent_id, offered, surplus)

    async def on_critical_zone(self, zone_status: ZoneStatus, orchestrator) -> None:
        """Dispatch units to a CRITICAL zone and update operational status."""
        if zone_status.zone_id in self.deployed_zones:
            return
        self._log(f"Dispatching to CRITICAL zone {zone_status.zone_id}")
        self.deployed_zones.append(zone_status.zone_id)
        # Consume resources for dispatch
        self.update_resources({"vehicles": -2, "personnel": -8, "water_units": -100})
        self.status = config.STATUS_ACTIVE

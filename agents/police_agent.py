"""
PoliceAgent — manages crowd control and zone access.
Bids on access control RFPs; maintains list of actively controlled zones.
"""

import logging
from typing import Any, List, Optional

import config
from agents.base_agent import BaseAgent
from messaging.broker import MessageBroker
from messaging.message_types import Bid, RFP
from negotiation.protocol import ContractNetProtocol

logger = logging.getLogger(__name__)
_CNP = ContractNetProtocol()


class PoliceAgent(BaseAgent):
    """Controls police personnel and vehicles for zone access management."""

    def __init__(self, broker: MessageBroker) -> None:
        super().__init__(
            agent_id="police_agent",
            agent_type="police",
            broker=broker,
            initial_resources=dict(config.AGENT_INITIAL_RESOURCES["police"]),
            priority_weight=1.2,
        )
        self.crowd_control_zones: List[str] = []

    async def process_event(self, event: Any) -> None:
        self._log("Earthquake event received — preparing crowd control deployment")
        self.status = config.STATUS_ACTIVE

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """Bid on personnel or vehicle access-control RFPs."""
        if not self.can_bid():
            return None

        resource = rfp.resource_type
        if resource == "personnel":
            surplus = self.resource_pool.get("personnel", 0) - 20
        elif resource == "vehicles":
            surplus = self.resource_pool.get("vehicles", 0) - 3
        else:
            return None

        if surplus <= 0:
            return None

        offered = min(surplus, rfp.amount_needed)
        return _CNP.create_bid(rfp, self.agent_id, offered, surplus)

    def assign_crowd_control(self, zone_id: str) -> None:
        """Mark a zone as under police crowd control."""
        if zone_id not in self.crowd_control_zones:
            self.crowd_control_zones.append(zone_id)
            self.update_resources({"personnel": -10, "vehicles": -2})
            self._log(f"Crowd control assigned to {zone_id}")

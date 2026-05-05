"""
NDRFAgent — National Disaster Response Force.
Primary earthquake rescue responder based in Zone-A.
Issues power RFPs when heavy equipment needs electricity; tracks deployed units per zone.
"""

import logging
from typing import Any, Dict, Optional

import config
from agents.base_agent import BaseAgent
from messaging.broker import MessageBroker
from messaging.message_types import Bid, RFP, ZoneStatus
from negotiation.protocol import ContractNetProtocol

logger = logging.getLogger(__name__)
_CNP = ContractNetProtocol()

_NDRF_BASE_ZONE = "Zone-A"


class NDRFAgent(BaseAgent):
    """Manages NDRF heavy equipment, personnel, and aerial rescue units."""

    def __init__(self, broker: MessageBroker) -> None:
        super().__init__(
            agent_id="ndrf_agent",
            agent_type="ndrf",
            broker=broker,
            initial_resources=dict(config.AGENT_INITIAL_RESOURCES["ndrf"]),
            priority_weight=2.0,
        )
        self.deployed_units: Dict[str, Dict] = {}  # zone_id -> {personnel, equipment}
        self._power_rfp_issued: bool = False  # emit only one power RFP per event

    async def process_event(self, event: Any) -> None:
        self._log("Earthquake event received — mobilising NDRF units")
        self.status = config.STATUS_ACTIVE

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """NDRF bids on personnel and heavy_equipment RFPs as primary responder."""
        if not self.can_bid():
            return None

        resource = rfp.resource_type
        if resource == "personnel":
            surplus = self.resource_pool.get("personnel", 0) - 20
        elif resource == "heavy_equipment":
            surplus = self.resource_pool.get("heavy_equipment", 0) - 2
        elif resource == "aerial_units":
            surplus = self.resource_pool.get("aerial_units", 0) - 1
        else:
            return None

        if surplus <= 0:
            return None

        offered = min(surplus, rfp.amount_needed)
        return _CNP.create_bid(rfp, self.agent_id, offered, surplus)

    async def on_affected_zone(self, zone_status: ZoneStatus, orchestrator) -> None:
        """
        Called by SensingAgent for CRITICAL zones.
        Deploys units; issues a single power RFP if equipment needs electricity and we haven't asked yet.
        """
        zone_id = zone_status.zone_id
        if zone_id in self.deployed_units:
            return

        self._log(f"Deploying to {zone_id} (severity={zone_status.severity_score:.2f})")
        deploy = {"personnel": 15, "heavy_equipment": 2}
        self.deployed_units[zone_id] = deploy
        self.update_resources({"personnel": -deploy["personnel"], "heavy_equipment": -deploy["heavy_equipment"]})

        # Issue one power RFP for all deployed zones (only on first deployment)
        if not zone_status.power_status and not self._power_rfp_issued:
            self._power_rfp_issued = True
            # Amount scales with severity of the worst affected zone
            power_needed = round(15 + zone_status.severity_score * 40)
            urgency = round(min(1.0, 0.6 + zone_status.severity_score * 0.4), 2)
            self._log(f"Zone {zone_id} has no power — RFP: {power_needed} units urgency={urgency}")
            rfp = _CNP.create_rfp(
                requester_id=self.agent_id,
                resource_type="power_units",
                amount=float(power_needed),
                urgency=urgency,
                zone_id=zone_id,
            )
            await orchestrator.run_cycle(rfp)

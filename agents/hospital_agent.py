"""
HospitalAgent — monitors hospital capacity and autonomously issues RFPs for power and personnel.
Located in Zone-B; always receives priority power allocation.
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

_HOSPITAL_ZONE = "Zone-B"
_PATIENT_LOAD_THRESHOLD = 0.8


class HospitalAgent(BaseAgent):
    """Manages hospital resources and triggers RFPs under crisis conditions."""

    def __init__(self, broker: MessageBroker) -> None:
        super().__init__(
            agent_id="hospital_agent",
            agent_type="hospital",
            broker=broker,
            initial_resources=dict(config.AGENT_INITIAL_RESOURCES["hospital"]),
            priority_weight=2.0,  # hospitals have elevated base priority
        )
        self.patient_load: float = 0.0

    async def process_event(self, event: Any) -> None:
        self._log("Earthquake event received — checking capacity")
        # Patient surge scales with magnitude: higher quake = more casualties admitted
        magnitude = getattr(event, "magnitude", None) or (event.get("magnitude", 7.0) if isinstance(event, dict) else 7.0)
        surge = round(min(1.0, (magnitude / 10.0) * 0.75), 2)
        self.patient_load = min(1.0, self.patient_load + surge)
        self._log(f"Patient surge +{surge} (M{magnitude:.1f}) → load={self.patient_load:.2f}")
        self._update_load()

        if self.patient_load > _PATIENT_LOAD_THRESHOLD:
            self._log(f"Patient load {self.patient_load:.2f} > threshold — personnel RFP will be issued on next on_critical_zone call")

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """Only bid on personnel RFPs when we have genuine surplus."""
        if rfp.resource_type != "personnel":
            return None
        if not self.can_bid():
            return None

        surplus = self.resource_pool.get("personnel", 0) - 20  # keep 20 in reserve
        if surplus <= 0:
            return None

        offered = min(surplus, rfp.amount_needed)
        return _CNP.create_bid(rfp, self.agent_id, offered, surplus)

    async def on_critical_zone(self, zone_status: ZoneStatus, orchestrator) -> None:
        """
        Called by SensingAgent when Zone-B is CRITICAL.
        Power demand scales with zone severity; urgency scales with patient load.
        """
        if zone_status.power_status:
            return
        # Demand is proportional to severity — harder hit = more power needed
        power_needed = round(20 + zone_status.severity_score * 60)
        urgency = round(min(1.0, 0.7 + self.patient_load * 0.3), 2)
        self._log(f"Zone-B without power — RFP: {power_needed} units at urgency={urgency}")
        rfp = _CNP.create_rfp(
            requester_id=self.agent_id,
            resource_type="power_units",
            amount=float(power_needed),
            urgency=urgency,
            zone_id=_HOSPITAL_ZONE,
        )
        await orchestrator.run_cycle(rfp)

        if self.patient_load > _PATIENT_LOAD_THRESHOLD:
            personnel_needed = round(10 + self.patient_load * 20)
            self._log(f"Patient load {self.patient_load:.2f} critical — RFP: {personnel_needed} personnel")
            personnel_rfp = _CNP.create_rfp(
                requester_id=self.agent_id,
                resource_type="personnel",
                amount=float(personnel_needed),
                urgency=round(min(1.0, self.patient_load), 2),
                zone_id=_HOSPITAL_ZONE,
            )
            await orchestrator.run_cycle(personnel_rfp)

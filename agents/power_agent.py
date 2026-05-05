"""
PowerAgent — manages the city's power grid.
Bids on power_unit RFPs, cuts power to unsafe zones, and guarantees hospital power
via a LIFE SAFETY OVERRIDE that bypasses normal negotiation.
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


class PowerAgent(BaseAgent):
    """Controls power allocation across city zones."""

    def __init__(self, broker: MessageBroker) -> None:
        super().__init__(
            agent_id="power_agent",
            agent_type="power",
            broker=broker,
            initial_resources=dict(config.AGENT_INITIAL_RESOURCES["power"]),
            priority_weight=1.2,
        )
        # Tracks which zones currently have power (True = powered)
        self.zone_power_map: Dict[str, bool] = {
            z["id"]: True for z in config.CITY_ZONES
        }

    async def process_event(self, event: Any) -> None:
        self._log("Received event (no direct power action needed at event level)")

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """Bid on power_units RFPs if surplus exceeds 20% of pool."""
        if rfp.resource_type != "power_units":
            return None
        if not self.can_bid():
            return None

        pool = self.resource_pool.get("power_units", 0)
        initial = config.AGENT_INITIAL_RESOURCES["power"].get("power_units", 1)
        surplus = pool - (initial * 0.2)  # keep 20% reserve

        if surplus <= 0:
            self._log(f"Cannot bid on RFP {rfp.rfp_id}: below 20% reserve")
            return None

        offered = min(surplus, rfp.amount_needed)
        return _CNP.create_bid(rfp, self.agent_id, offered, surplus)

    def apply_power_decision(self, zone_statuses: list) -> None:
        """
        Cut power to zones classified as unsafe (severity > 0.6).
        Maintain power to CRITICAL infrastructure zones regardless of status.
        """
        for zs in zone_statuses:
            if isinstance(zs, dict):
                zone_id = zs["zone_id"]
                has_infra = zs.get("has_critical_infra", False)
                severity = zs.get("severity_score", 0.0)
            else:
                zone_id = zs.zone_id
                has_infra = zs.has_critical_infra
                severity = zs.severity_score

            if has_infra:
                # Critical infrastructure always keeps power
                self.zone_power_map[zone_id] = True
            elif severity > 0.6:
                self.zone_power_map[zone_id] = False
                self._log(f"Power cut to {zone_id} (severity={severity:.2f})")

    def reallocate_to_hospital(self, zone_id: str) -> None:
        # LIFE SAFETY OVERRIDE — hospitals always receive power, no bidding required
        self.zone_power_map[zone_id] = True
        self._log(f"LIFE SAFETY OVERRIDE: power restored to hospital zone {zone_id}")

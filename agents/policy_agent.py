"""
PolicyAgent — monitors resource equity and intervenes when Gini exceeds threshold.
Penalises bids from hoarding agents; protects vulnerable high-population zones.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from agents.base_agent import BaseAgent
from intelligence.fairness import compute_gini
from messaging.broker import MessageBroker
from messaging.message_types import AgentState, Bid, RFP, ZoneStatus

logger = logging.getLogger(__name__)

_HOARDING_UTILIZATION_THRESHOLD = 0.3  # agents using <30% of resources are "hoarding"
_SCORE_PENALTY = 0.2


class PolicyAgent(BaseAgent):
    """Fairness monitor and bid-score adjuster for DACRO's negotiation system."""

    def __init__(self, broker: MessageBroker) -> None:
        super().__init__(
            agent_id="policy_agent",
            agent_type="policy",
            broker=broker,
            initial_resources={},
            priority_weight=1.0,
        )

    async def process_event(self, event: Any) -> None:
        self._log("Policy agent standing by")

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """PolicyAgent never holds or bids resources."""
        return None

    def check_fairness(self, agent_states: List[AgentState]) -> Dict:
        """
        Compute current Gini and identify agents hoarding resources.
        Returns {gini, intervention_needed, penalized_agents}.
        """
        from intelligence.fairness import get_allocation_summary
        allocations = [sum(s.resource_pool.values()) for s in agent_states]
        gini = compute_gini(allocations)
        intervention_needed = gini > config.GINI_THRESHOLD

        penalized: List[str] = []
        if intervention_needed:
            summary = get_allocation_summary(agent_states)
            for agent_id, info in summary.items():
                if info["utilization"] < _HOARDING_UTILIZATION_THRESHOLD:
                    penalized.append(agent_id)

        return {
            "gini": round(gini, 4),
            "intervention_needed": intervention_needed,
            "penalized_agents": penalized,
        }

    def adjust_scores(
        self,
        bid_scores: List[Tuple[Bid, float]],
        agent_states: Dict[str, AgentState],
    ) -> List[Tuple[Bid, float]]:
        """
        Reduce score of bids from agents with resource utilisation < 30%.
        Re-sorts the list after adjustment.
        """
        fairness_info = self.check_fairness(list(agent_states.values()))
        if not fairness_info["intervention_needed"]:
            return bid_scores

        penalized_ids = set(fairness_info["penalized_agents"])
        adjusted: List[Tuple[Bid, float]] = []
        for bid, score in bid_scores:
            if bid.bidder_agent_id in penalized_ids:
                new_score = max(0.0, score - _SCORE_PENALTY)
                self._log(
                    f"Penalising {bid.bidder_agent_id}: score {score:.4f} → {new_score:.4f} (hoarding)"
                )
                adjusted.append((bid, new_score))
            else:
                adjusted.append((bid, score))

        adjusted.sort(key=lambda x: x[1], reverse=True)
        return adjusted

    def get_vulnerable_zone_protection(self, zone_statuses: List[ZoneStatus]) -> List[str]:
        """
        Return zone IDs that must not be deprioritised.
        Criteria: high population density (>0.65) — regardless of current allocation.
        """
        protected: List[str] = []
        for zs in zone_statuses:
            if isinstance(zs, dict):
                pop = zs.get("population_density", 0)
                zone_id = zs.get("zone_id", "")
            else:
                pop = zs.population_density
                zone_id = zs.zone_id
            if pop > 0.65:
                protected.append(zone_id)
        return protected

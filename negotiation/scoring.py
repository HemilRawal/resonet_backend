"""
Bid scoring and ranking logic for DACRO's Contract Net Protocol.
Composite score: urgency × 0.5 + availability × 0.3 + fairness_adjustment × 0.2.
"""

import logging
from typing import Dict, List, Tuple

import config
from messaging.message_types import AgentState, Bid, RFP

logger = logging.getLogger(__name__)


def score_bid(
    bid: Bid,
    rfp: RFP,
    current_gini: float,
    agent_state: AgentState,
) -> float:
    """
    Compute a composite score for a bid.
    Higher score = better bid.

    urgency_score      = rfp.urgency_score  (how critical the need is)
    availability_score = bid.available_surplus / agent's total pool for that resource
    fairness_adjustment = 1 - current_gini  (reward bids that reduce inequality)
    """
    weights = config.BID_SCORE_WEIGHTS

    urgency_score = rfp.urgency_score

    pool_amount = agent_state.resource_pool.get(rfp.resource_type, 1)
    if pool_amount <= 0:
        availability_score = 0.0
    else:
        availability_score = min(1.0, bid.available_surplus / pool_amount)

    fairness_adjustment = max(0.0, 1.0 - current_gini)

    score = (
        urgency_score * weights["urgency"]
        + availability_score * weights["availability"]
        + fairness_adjustment * weights["fairness"]
    )
    return round(score, 6)


def rank_bids(
    bids: List[Bid],
    rfp: RFP,
    gini: float,
    agent_states: Dict[str, AgentState],
) -> List[Tuple[Bid, float]]:
    """
    Score and rank all bids for an RFP, returning (bid, score) sorted descending.
    Bids from agents not found in agent_states are scored with an empty resource pool.
    """
    scored: List[Tuple[Bid, float]] = []
    for bid in bids:
        state = agent_states.get(bid.bidder_agent_id)
        if state is None:
            logger.warning("No agent state found for bidder %s — scoring with empty pool", bid.bidder_agent_id)
            from messaging.message_types import AgentState as AS
            import datetime
            state = AS(
                agent_id=bid.bidder_agent_id,
                agent_type="unknown",
                resource_pool={},
                current_load=0.0,
                priority_weight=1.0,
                status=config.STATUS_IDLE,
                last_updated=datetime.datetime.utcnow().isoformat(),
            )
        s = score_bid(bid, rfp, gini, state)
        scored.append((bid, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored

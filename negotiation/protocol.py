"""
Contract Net Protocol (CNP) message factory for DACRO.
All methods are pure — they construct typed objects with UUIDs and have no side effects.
State transitions and I/O live in orchestrator.py.
"""

import uuid
from typing import List

from messaging.message_types import Award, Bid, RFP


class ContractNetProtocol:
    """
    Stateless factory for CNP message objects.
    Create instances of RFP, Bid, and Award without side effects.
    """

    @staticmethod
    def create_rfp(
        requester_id: str,
        resource_type: str,
        amount: float,
        urgency: float,
        zone_id: str,
    ) -> RFP:
        """Construct a new Request For Proposal."""
        return RFP(
            rfp_id=str(uuid.uuid4()),
            requester_agent_id=requester_id,
            resource_type=resource_type,
            amount_needed=amount,
            urgency_score=max(0.0, min(1.0, urgency)),
            zone_id=zone_id,
        )

    @staticmethod
    def create_bid(
        rfp: RFP,
        bidder_id: str,
        offered_amount: float,
        surplus: float,
    ) -> Bid:
        """Construct a Bid in response to an RFP."""
        cost_score = 1.0 - min(1.0, surplus / max(offered_amount, 1))
        return Bid(
            bid_id=str(uuid.uuid4()),
            rfp_id=rfp.rfp_id,
            bidder_agent_id=bidder_id,
            offered_amount=offered_amount,
            cost_score=round(cost_score, 4),
            available_surplus=surplus,
        )

    @staticmethod
    def create_award(
        rfp: RFP,
        winning_bid: Bid,
        all_bids: List[Bid],
    ) -> Award:
        """Construct an Award for the winning bid, summarising all bids."""
        all_bids_summary = [
            {
                "bidder_id": b.bidder_agent_id,
                "offered_amount": b.offered_amount,
                "bid_id": b.bid_id,
            }
            for b in all_bids
        ]
        return Award(
            award_id=str(uuid.uuid4()),
            rfp_id=rfp.rfp_id,
            winner_agent_id=winning_bid.bidder_agent_id,
            requester_agent_id=rfp.requester_agent_id,
            resource_type=rfp.resource_type,
            amount_awarded=min(winning_bid.offered_amount, rfp.amount_needed),
            all_bids_summary=all_bids_summary,
        )

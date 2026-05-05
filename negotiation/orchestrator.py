"""
NegotiationOrchestrator — runs a complete Contract Net Protocol cycle for each RFP.
Steps: broadcast RFP → collect bids → score → policy check → award → transfer → XAI → log → broadcast.
"""

import asyncio
import dataclasses
import logging
import uuid
from typing import Dict, List, Optional

import config
from intelligence.fairness import compute_gini, get_allocation_summary
from messaging.broker import MessageBroker
from messaging.message_types import (
    AgentState, Award, Bid, NegotiationDecision, RFP, WebSocketEvent,
)
from negotiation.protocol import ContractNetProtocol
from negotiation.scoring import rank_bids
from persistence.decision_log import DecisionLog
from simulation.city_model import CityModel

logger = logging.getLogger(__name__)

_CNP = ContractNetProtocol()


class NegotiationOrchestrator:
    """
    Coordinates a full CNP negotiation cycle for a single RFP.
    Agents are called directly (in-process) for bid collection rather than via pub/sub,
    keeping latency deterministic for the demo.
    """

    def __init__(
        self,
        broker: MessageBroker,
        city_model: CityModel,
        decision_log: DecisionLog,
        all_agents: Dict,
        xai_agent,
        policy_agent,
    ) -> None:
        self.broker = broker
        self.city_model = city_model
        self.decision_log = decision_log
        self.all_agents = all_agents  # agent_id -> BaseAgent
        self.xai_agent = xai_agent
        self.policy_agent = policy_agent

    async def run_cycle(self, rfp: RFP) -> NegotiationDecision:
        """Execute a full negotiation cycle and return the persisted decision."""
        logger.info("")
        logger.info("┌─────────────────────────────────────────────────────────────")
        logger.info("│ NEW RFP  resource=%-12s  amount=%-6.0f  urgency=%.1f  zone=%s",
                    rfp.resource_type, rfp.amount_needed, rfp.urgency_score, rfp.zone_id)
        logger.info("│ Requester: %s", rfp.requester_agent_id)
        logger.info("└─────────────────────────────────────────────────────────────")

        # Step 1: Broadcast RFP so agents are aware (fire-and-forget notification)
        await self.broker.publish(config.CHANNEL_RFP, rfp)

        # Step 2: Collect bids with a 2-second timeout per agent
        bids: List[Bid] = []
        logger.info("[BID COLLECTION] Polling %d agents...", len(self.all_agents) - 1)
        for agent_id, agent in self.all_agents.items():
            if agent_id == rfp.requester_agent_id:
                continue
            if not agent.can_bid():
                logger.info("  %-22s → SKIP  (status=%s)", agent_id, agent.status)
                continue
            try:
                bid = await asyncio.wait_for(agent.evaluate_rfp(rfp), timeout=2.0)
                if bid is not None:
                    pool_val = agent.resource_pool.get(rfp.resource_type, 0)
                    logger.info("  %-22s → BID   offered=%-6.0f  surplus=%-6.0f  pool_remaining=%g",
                                agent_id, bid.offered_amount, bid.available_surplus, pool_val)
                    bids.append(bid)
                else:
                    logger.info("  %-22s → PASS  (insufficient surplus or wrong resource)", agent_id)
            except asyncio.TimeoutError:
                logger.warning("  %-22s → TIMEOUT (>2s)", agent_id)
            except Exception as exc:
                logger.error("  %-22s → ERROR  %s", agent_id, exc)

        # Step 3: Compute Gini before award
        agent_states = {aid: a.get_state() for aid, a in self.all_agents.items()}
        current_resources = [
            sum(s.resource_pool.values()) for s in agent_states.values()
        ]
        gini_before = compute_gini(current_resources)
        logger.info("[FAIRNESS] Gini before award: %.4f  (%s)",
                    gini_before,
                    "intervention threshold NOT breached" if gini_before <= config.GINI_THRESHOLD
                    else "ABOVE threshold — policy agent will penalise hoarders")

        award: Optional[Award] = None
        winner = None

        if bids:
            # Step 4: Score and rank bids
            ranked = rank_bids(bids, rfp, gini_before, agent_states)

            logger.info("[SCORING] %d bid(s) received — scores (urgency×0.5 + avail×0.3 + fairness×0.2):", len(bids))
            for bid, score in ranked:
                state = agent_states.get(bid.bidder_agent_id)
                pool_val = state.resource_pool.get(rfp.resource_type, 1) if state else 1
                avail_score = min(1.0, bid.available_surplus / pool_val) if pool_val > 0 else 0
                fairness_adj = max(0.0, 1.0 - gini_before)
                logger.info("  %-22s  total=%.4f  [urgency=%.3f | avail=%.3f | fairness=%.3f]",
                            bid.bidder_agent_id, score,
                            rfp.urgency_score * 0.5,
                            avail_score * 0.3,
                            fairness_adj * 0.2)

            # Step 5: Policy check — penalise over-resourced agents if Gini too high
            if gini_before > config.GINI_THRESHOLD and self.policy_agent:
                try:
                    before_top = ranked[0][0].bidder_agent_id
                    ranked = self.policy_agent.adjust_scores(ranked, agent_states)
                    after_top = ranked[0][0].bidder_agent_id
                    if before_top != after_top:
                        logger.info("[POLICY] Gini=%.3f > threshold — scores adjusted. Top bidder changed: %s → %s",
                                    gini_before, before_top, after_top)
                    else:
                        logger.info("[POLICY] Gini=%.3f > threshold — scores adjusted. Top bidder unchanged: %s",
                                    gini_before, after_top)
                except Exception as exc:
                    logger.error("[POLICY] adjust error: %s", exc)

            # Step 6: Select winner and execute resource transfer
            winning_bid, winning_score = ranked[0]
            winner = self.all_agents.get(winning_bid.bidder_agent_id)
            requester = self.all_agents.get(rfp.requester_agent_id)
            amount = min(winning_bid.offered_amount, rfp.amount_needed)

            if winner:
                old_pool = winner.resource_pool.get(rfp.resource_type, 0)
                winner.update_resources({rfp.resource_type: -amount})
                new_pool = winner.resource_pool.get(rfp.resource_type, 0)
                logger.info("[AWARD] ★  %s  →  transfers %.0f %s  to  %s",
                            winning_bid.bidder_agent_id, amount, rfp.resource_type, rfp.requester_agent_id)
                logger.info("        %s pool: %g → %g", winning_bid.bidder_agent_id, old_pool, new_pool)
            if requester:
                requester.update_resources({rfp.resource_type: amount})

            # Step 7: Compute Gini after award
            updated_resources = [
                sum(a.get_state().resource_pool.values()) for a in self.all_agents.values()
            ]
            gini_after = compute_gini(updated_resources)
            delta = gini_after - gini_before
            direction = "more equal ▲" if delta < 0 else "less equal ▼"
            logger.info("[FAIRNESS] Gini after award:  %.4f  (Δ%+.4f — system became %s)",
                        gini_after, delta, direction)

            # Step 7b: Broadcast updated agent states so frontend inventory reflects changes
            for agent_obj in [winner, requester]:
                if agent_obj is not None:
                    state = agent_obj.get_state()
                    await self.broker.broadcast(WebSocketEvent(
                        event_type="agent_state",
                        payload=dataclasses.asdict(state),
                    ))

            # Step 8: Create Award and NegotiationDecision
            award = _CNP.create_award(rfp, winning_bid, bids)
        else:
            logger.warning("[AWARD] ✗  No bids received — %s gets no %s (degraded mode)",
                           rfp.requester_agent_id, rfp.resource_type)
            updated_resources = current_resources
            gini_after = gini_before

        zone_states = [
            dataclasses.asdict(zs) if dataclasses.is_dataclass(zs) else zs
            for zs in []  # zone_states populated by SensingAgent context; empty here
        ]

        decision = NegotiationDecision(
            decision_id=str(uuid.uuid4()),
            event_id=rfp.rfp_id,  # use rfp_id as event correlation; overridden by caller
            rfp=rfp,
            award=award,
            zone_states=zone_states,
            gini_before=gini_before,
            gini_after=gini_after,
            xai_explanation="",
        )

        # Step 9: Fire XAI agent async (don't await)
        if self.xai_agent and award:
            asyncio.create_task(self.xai_agent.explain(decision, self.broker))

        # Step 10: Log to SQLite
        self.decision_log.log_decision(decision)

        # Step 11: Broadcast negotiation event via WebSocket
        ws_event = WebSocketEvent(
            event_type="negotiation",
            payload={
                "decision_id": decision.decision_id,
                "rfp_id": rfp.rfp_id,
                "resource_type": rfp.resource_type,
                "requester": rfp.requester_agent_id,
                "winner": award.winner_agent_id if award else None,
                "amount_awarded": award.amount_awarded if award else 0,
                "gini_before": gini_before,
                "gini_after": gini_after,
                "bids_count": len(bids),
            },
        )
        await self.broker.broadcast(ws_event)

        # Step 12: Return
        return decision

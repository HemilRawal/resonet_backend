"""
XAIAgent — generates natural-language explanations for every negotiation decision.
Calls the LLM client asynchronously and broadcasts the explanation via WebSocket.
Also patches the explanation back into the SQLite decision record.
"""

import dataclasses
import logging
from typing import Any, Optional

import config
from agents.base_agent import BaseAgent
from intelligence import llm_client
from messaging.broker import MessageBroker
from messaging.message_types import Bid, NegotiationDecision, RFP, WebSocketEvent

logger = logging.getLogger(__name__)


class XAIAgent(BaseAgent):
    """Consumes NegotiationDecision objects and produces RATIONALE | COUNTERFACTUAL strings."""

    def __init__(self, broker: MessageBroker, decision_log) -> None:
        super().__init__(
            agent_id="xai_agent",
            agent_type="xai",
            broker=broker,
            initial_resources={},
            priority_weight=1.0,
        )
        self.decision_log = decision_log

    async def process_event(self, event: Any) -> None:
        self._log("XAI agent online — waiting for decisions")

    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """XAIAgent never holds or bids resources."""
        return None

    async def explain(self, decision: NegotiationDecision, broker: MessageBroker) -> None:
        """
        Build context dict, call LLM, parse result, broadcast via WebSocket,
        and patch the explanation back into SQLite.
        """
        self._log(f"Generating explanation for decision {decision.decision_id}")

        context = _build_context(decision)
        explanation = await llm_client.generate_explanation(context)

        rationale, counterfactual = _parse_explanation(explanation)

        # Broadcast XAI event to WebSocket clients
        ws_event = WebSocketEvent(
            event_type="xai",
            payload={
                "decision_id": decision.decision_id,
                "rationale": rationale,
                "counterfactual": counterfactual,
                "raw_explanation": explanation,
            },
        )
        await broker.broadcast(ws_event)

        # Patch the explanation into the SQLite record
        try:
            self.decision_log.update_xai_explanation(decision.decision_id, explanation)
        except Exception as exc:
            logger.error("XAIAgent: failed to update SQLite: %s", exc)

        self._log(f"Explanation broadcast for {decision.decision_id}")


def _build_context(decision: NegotiationDecision) -> dict:
    """Flatten a NegotiationDecision into a flat context dict for the LLM prompt."""
    rfp = decision.rfp
    award = decision.award
    ctx = {
        "decision_id": decision.decision_id,
        "event_id": decision.event_id,
        "resource_type": rfp.resource_type if rfp else "unknown",
        "requester_agent": rfp.requester_agent_id if rfp else "unknown",
        "amount_needed": rfp.amount_needed if rfp else 0,
        "urgency_score": rfp.urgency_score if rfp else 0,
        "zone_id": rfp.zone_id if rfp else "unknown",
        "winner_agent": award.winner_agent_id if award else "none",
        "amount_awarded": award.amount_awarded if award else 0,
        "all_bids_summary": award.all_bids_summary if award else [],
        "gini_before": decision.gini_before,
        "gini_after": decision.gini_after,
        "zone_count": len(decision.zone_states),
    }
    return ctx


def _parse_explanation(text: str) -> tuple:
    """
    Split 'RATIONALE: ... | COUNTERFACTUAL: ...' into two parts.
    Falls back gracefully if the format is not followed.
    """
    rationale = text
    counterfactual = ""
    if "COUNTERFACTUAL:" in text:
        parts = text.split("COUNTERFACTUAL:", 1)
        rationale = parts[0].replace("RATIONALE:", "").strip().rstrip("|").strip()
        counterfactual = parts[1].strip()
    elif "RATIONALE:" in text:
        rationale = text.replace("RATIONALE:", "").strip()
    return rationale, counterfactual

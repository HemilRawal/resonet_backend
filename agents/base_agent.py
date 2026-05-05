"""
Abstract base class for all DACRO agents.
Every concrete agent inherits this, guaranteeing a uniform interface
for the orchestrator to call process_event, evaluate_rfp, and get_state.
"""

import abc
import datetime
import logging
from typing import Dict, Optional

import config
from messaging.broker import MessageBroker
from messaging.message_types import AgentState, Bid, RFP

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """
    Base class providing shared state management and lifecycle methods.
    Subclasses must implement: process_event, evaluate_rfp.
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        broker: MessageBroker,
        initial_resources: Dict,
        priority_weight: float = 1.0,
    ) -> None:
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.broker = broker
        self.resource_pool: Dict = dict(initial_resources)
        self.current_load: float = 0.0
        self.priority_weight: float = priority_weight
        self.status: str = config.STATUS_IDLE

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement these
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def process_event(self, event) -> None:
        """Handle an incoming event (earthquake, zone update, etc.)."""

    @abc.abstractmethod
    async def evaluate_rfp(self, rfp: RFP) -> Optional[Bid]:
        """
        Evaluate a Request For Proposal and return a Bid, or None if the
        agent cannot fulfil the request.
        """

    # ------------------------------------------------------------------
    # Concrete shared methods
    # ------------------------------------------------------------------

    def get_state(self) -> AgentState:
        """Snapshot the agent's current operational state."""
        return AgentState(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            resource_pool=dict(self.resource_pool),
            current_load=self.current_load,
            priority_weight=self.priority_weight,
            status=self.status,
            last_updated=datetime.datetime.utcnow().isoformat(),
        )

    def update_resources(self, delta: Dict) -> None:
        """
        Apply a resource delta (positive = gain, negative = spend).
        Clamps each value to >= 0 to prevent negative resource pools.
        """
        for key, change in delta.items():
            current = self.resource_pool.get(key, 0)
            self.resource_pool[key] = max(0, current + change)
        self._update_load()

    def can_bid(self) -> bool:
        """Returns False if this agent is overloaded or offline."""
        return self.status not in (config.STATUS_OVERLOADED, config.STATUS_OFFLINE)

    def _update_load(self) -> None:
        """Recalculate current_load based on resource utilisation."""
        if not self.resource_pool:
            self.current_load = 0.0
            return
        initial = config.AGENT_INITIAL_RESOURCES.get(self.agent_type, {})
        if not initial:
            return
        ratios = []
        for key, initial_val in initial.items():
            if initial_val > 0:
                current = self.resource_pool.get(key, 0)
                used_ratio = 1.0 - (current / initial_val)
                ratios.append(max(0.0, min(1.0, used_ratio)))
        self.current_load = sum(ratios) / len(ratios) if ratios else 0.0

        if self.current_load >= 0.9:
            self.status = config.STATUS_OVERLOADED
        elif self.current_load > 0.0:
            self.status = config.STATUS_ACTIVE
        else:
            self.status = config.STATUS_IDLE

    def _log(self, message: str) -> None:
        """Prefixed print for agent-level logging."""
        logger.info("[%s] %s", self.agent_id, message)

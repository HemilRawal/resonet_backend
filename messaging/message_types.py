"""
All typed message dataclasses for inter-agent communication in DACRO.
Every message flowing through the broker must be one of these types — no raw dicts.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import datetime


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


@dataclass
class EarthquakeEvent:
    """Fired when an earthquake is simulated; consumed by SensingAgent."""
    epicenter_lat: float
    epicenter_lon: float
    magnitude: float
    event_id: str
    calamity_type: str = "EARTHQUAKE"
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class FireEvent:
    """Fired when a fire is simulated; consumed by SensingAgent."""
    epicenter_lat: float
    epicenter_lon: float
    intensity: float          # analogous to magnitude — controls radius/severity
    event_id: str
    radius_km: float = 1.5   # damage drops to zero at this distance
    calamity_type: str = "FIRE"
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class ZoneStatus:
    """Snapshot of one zone's post-earthquake state."""
    zone_id: str
    severity_score: float         # 0.0 – 1.0
    classification: str           # CRITICAL | HIGH | LOW | SAFE
    population_density: float     # 0.0 – 1.0
    has_critical_infra: bool
    road_blocked: bool
    power_status: bool            # True = power on


@dataclass
class RFP:
    """Request For Proposal — an agent advertising a resource need."""
    rfp_id: str
    requester_agent_id: str
    resource_type: str
    amount_needed: float
    urgency_score: float          # 0.0 – 1.0
    zone_id: str
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class Bid:
    """A bid response to an RFP from an agent with surplus resources."""
    bid_id: str
    rfp_id: str
    bidder_agent_id: str
    offered_amount: float
    cost_score: float             # lower = cheaper to deploy
    available_surplus: float
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class Award:
    """Outcome of a CNP negotiation cycle — sent to winner and requester."""
    award_id: str
    rfp_id: str
    winner_agent_id: str
    requester_agent_id: str
    resource_type: str
    amount_awarded: float
    all_bids_summary: list        # list of {bidder_id, offered_amount, score}
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class AgentState:
    """Current operational state of an agent, broadcast on state changes."""
    agent_id: str
    agent_type: str
    resource_pool: dict
    current_load: float           # 0.0 – 1.0
    priority_weight: float
    status: str                   # IDLE | ACTIVE | OVERLOADED | OFFLINE
    last_updated: str = field(default_factory=_now_iso)


@dataclass
class NegotiationDecision:
    """Full audit record of one negotiation cycle, persisted to SQLite."""
    decision_id: str
    event_id: str
    rfp: RFP
    award: Optional[Award]        # None if no bids received
    zone_states: list             # list of ZoneStatus dicts at time of decision
    gini_before: float
    gini_after: float
    xai_explanation: str          # filled later by XAIAgent
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class WebSocketEvent:
    """Envelope for all real-time events pushed to the frontend."""
    event_type: str               # zone_update | negotiation | xai | agent_state | dispatch
    payload: Any
    timestamp: str = field(default_factory=_now_iso)

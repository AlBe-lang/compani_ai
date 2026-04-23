"""Emergency meeting contracts (Part 7 Stage 1).

Three Pydantic models describe the lifecycle of a single emergency meeting:
- ``MeetingRequest``  — convening signal sent to each participant
- ``MeetingVote``     — one participant's response (or ABSTAIN on no-reply)
- ``ConsensusResult`` — final aggregated decision with source label

Rule 10 §1 (context preservation) applies: every field is kept on write so
future semantic search (Qdrant) can retrieve the full shape of past meetings,
not just the verdict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MeetingDecision(str, Enum):
    """Finite decision space for both individual votes and the final outcome."""

    RETRY = "RETRY"
    REROUTE = "REROUTE"
    ESCALATE = "ESCALATE"
    ABORT = "ABORT"


class DecisionSource(str, Enum):
    """Whether the final decision came from CTO judgment or DNA fallback."""

    CTO = "cto"
    DNA_FALLBACK = "dna_fallback"


class MeetingRequest(BaseModel):
    """Signal sent to each selected participant to open a meeting."""

    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    blocking_item_id: str
    blocking_owner_agent_id: str
    blocking_reason: str = ""
    participant_agent_ids: list[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MeetingVote(BaseModel):
    """One participant's vote. ``abstained=True`` means timeout / no-response.

    When abstained, ``decision`` carries a placeholder (ABORT by convention)
    that is ignored by the tally; callers must check ``abstained`` first.
    """

    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    voter_agent_id: str
    decision: MeetingDecision
    rationale: str = ""
    abstained: bool = False
    voted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConsensusResult(BaseModel):
    """Final aggregated outcome of one meeting.

    ``decision_source`` records whether CTO or the DNA-weighted fallback
    produced the final verdict — essential for Rule 10 §1 context preservation
    and for operational visibility of CTO availability issues.
    """

    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    final_decision: MeetingDecision
    decision_source: DecisionSource
    weighted_tally: dict[str, float]
    votes: list[MeetingVote]
    cto_reason: str = ""
    fallback_reason: str = ""
    abstain_count: int = 0
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

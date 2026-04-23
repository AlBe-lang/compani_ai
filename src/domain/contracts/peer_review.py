"""Peer review contracts — Part 7 Stage 2.

Task-level code review performed by a different-role agent after the producer
marks a WorkItem as DONE. Distinct from ``ReviewResult`` (Part 1) which is a
project-level gate decision (CONTINUE / REPLAN / ABORT).

Rule 10 §1 (context preservation): ``PeerReviewRequest`` carries a full snapshot
of the ``TaskResult`` at review time so the review record is self-contained —
future refactors of the producer code don't invalidate past review context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PeerReviewDecision(str, Enum):
    """Top-level review verdict."""

    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class PeerReviewSeverity(str, Enum):
    """Severity of requested changes.

    Only meaningful when ``decision == REQUEST_CHANGES``. Used by the
    WorkItem state-transition matrix:
      MINOR    → DONE 유지, 기록만
      MAJOR    → DONE 유지, pending_rework=True (Stage 3 재실행 대상)
      CRITICAL → DONE 유지, pending_rework=True (Stage 3 재실행 대상,
                 status 전이는 Stage 3에서 추가)
    """

    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class PeerReviewRequest(BaseModel):
    """Snapshot captured when the review starts."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    work_item_id: str
    task_id: str
    author_agent_id: str
    reviewer_agent_id: str
    task_result_snapshot: dict[str, object]
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PeerReviewResult(BaseModel):
    """Outcome of one peer review.

    ``pending_rework`` is set True for MAJOR/CRITICAL REQUEST_CHANGES so
    Stage 3 rework scheduler can find items needing re-execution. Stage 2
    writes this flag but does not act on it.
    """

    model_config = ConfigDict(extra="forbid")

    review_id: str
    work_item_id: str
    task_id: str
    author_agent_id: str
    reviewer_agent_id: str
    decision: PeerReviewDecision
    severity: PeerReviewSeverity = PeerReviewSeverity.MINOR
    comments: list[str] = Field(default_factory=list)
    suggested_changes: list[str] = Field(default_factory=list)
    pending_rework: bool = False
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

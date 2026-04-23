"""Contract tests for PeerReview Pydantic models — Part 7 Stage 2."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domain.contracts import (
    PeerReviewDecision,
    PeerReviewRequest,
    PeerReviewResult,
    PeerReviewSeverity,
)


def test_peer_review_decision_enum_values() -> None:
    assert {d.value for d in PeerReviewDecision} == {
        "APPROVE",
        "REQUEST_CHANGES",
        "REJECT",
    }


def test_peer_review_severity_enum_values() -> None:
    assert {s.value for s in PeerReviewSeverity} == {"MINOR", "MAJOR", "CRITICAL"}


def test_peer_review_request_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        PeerReviewRequest(
            review_id="r1",
            work_item_id="wi_1",
            task_id="t1",
            author_agent_id="backend",
            reviewer_agent_id="frontend",
            task_result_snapshot={},
            unexpected="field",  # type: ignore[call-arg]
        )


def test_peer_review_result_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        PeerReviewResult(
            review_id="r1",
            work_item_id="wi_1",
            task_id="t1",
            author_agent_id="backend",
            reviewer_agent_id="frontend",
            decision=PeerReviewDecision.APPROVE,
            unknown="x",  # type: ignore[call-arg]
        )


def test_peer_review_result_defaults() -> None:
    result = PeerReviewResult(
        review_id="r1",
        work_item_id="wi_1",
        task_id="t1",
        author_agent_id="backend",
        reviewer_agent_id="frontend",
        decision=PeerReviewDecision.APPROVE,
    )
    assert result.severity is PeerReviewSeverity.MINOR
    assert result.comments == []
    assert result.suggested_changes == []
    assert result.pending_rework is False

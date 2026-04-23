"""Contract tests for Meeting Pydantic models — Part 7 Stage 1."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domain.contracts import (
    ConsensusResult,
    DecisionSource,
    MeetingDecision,
    MeetingRequest,
    MeetingVote,
)


def test_meeting_decision_enum_values() -> None:
    assert {d.value for d in MeetingDecision} == {"RETRY", "REROUTE", "ESCALATE", "ABORT"}


def test_decision_source_enum_values() -> None:
    assert {s.value for s in DecisionSource} == {"cto", "dna_fallback"}


def test_meeting_request_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        MeetingRequest(
            meeting_id="m1",
            blocking_item_id="wi_1",
            blocking_owner_agent_id="backend",
            participant_agent_ids=["backend"],
            unexpected="field",  # type: ignore[call-arg]
        )


def test_meeting_vote_abstained_default_false() -> None:
    vote = MeetingVote(
        meeting_id="m1",
        voter_agent_id="backend",
        decision=MeetingDecision.RETRY,
    )
    assert vote.abstained is False
    assert vote.rationale == ""


def test_meeting_vote_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        MeetingVote(
            meeting_id="m1",
            voter_agent_id="backend",
            decision=MeetingDecision.RETRY,
            extra_field="x",  # type: ignore[call-arg]
        )


def test_consensus_result_forbid_extra() -> None:
    with pytest.raises(ValidationError):
        ConsensusResult(
            meeting_id="m1",
            final_decision=MeetingDecision.RETRY,
            decision_source=DecisionSource.CTO,
            weighted_tally={"RETRY": 1.0},
            votes=[],
            unknown="x",  # type: ignore[call-arg]
        )


def test_consensus_result_defaults() -> None:
    result = ConsensusResult(
        meeting_id="m1",
        final_decision=MeetingDecision.RETRY,
        decision_source=DecisionSource.CTO,
        weighted_tally={"RETRY": 1.0},
        votes=[],
    )
    assert result.cto_reason == ""
    assert result.fallback_reason == ""
    assert result.abstain_count == 0

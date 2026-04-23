"""Unit tests for EmergencyMeeting — Part 7 Stage 1.

Mocks MessageQueuePort / LLMProvider / StoragePort / KnowledgeGraphPort so the
tests don't require Ollama or Qdrant. Focus areas:
  1. participant selection (3-way structure, deduplication)
  2. vote collection (ABSTAIN on timeout / invalid / receive error)
  3. DNA-weighted tally and fallback winner resolution (tie → owner)
  4. CTO-with-retry → success / fallback / metrics recording
  5. full convene() round-trip persistence + participation count
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.emergency_meeting import EmergencyMeeting, EmergencyMeetingConfig
from domain.contracts import AgentDNA, DecisionSource, MeetingDecision, Message, MessageType

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_queue() -> MagicMock:
    mock = MagicMock()
    mock.send = AsyncMock(return_value="msg_id")
    mock.receive = AsyncMock(return_value=None)
    return mock


def _make_storage() -> MagicMock:
    mock = MagicMock()
    mock.save = AsyncMock()
    mock.load = AsyncMock(return_value=None)
    return mock


def _make_kg(best_responder: str | None = None) -> MagicMock:
    mock = MagicMock()
    mock.find_best_responder = AsyncMock(return_value=best_responder)
    return mock


def _make_llm(responses: list[str] | list[Exception]) -> MagicMock:
    mock = MagicMock()
    iterator = iter(responses)

    async def _gen(*args: Any, **kwargs: Any) -> str:
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, str)
        return item

    mock.generate = AsyncMock(side_effect=_gen)
    return mock


def _make_dna_manager(weights: dict[str, tuple[float, float]] | None = None) -> MagicMock:
    """Returns (collaboration, precision) per agent; default neutral 0.5/0.5."""
    mock = MagicMock()
    weights = weights or {}

    async def _load(agent_id: str, role: str) -> AgentDNA:
        collab, precision = weights.get(agent_id, (0.5, 0.5))
        dna = AgentDNA(agent_id=agent_id, role=role)
        dna.genes["collaboration"] = collab
        dna.genes["precision"] = precision
        return dna

    mock.load = AsyncMock(side_effect=_load)
    mock.update_meeting_participation = AsyncMock()
    return mock


def _make_meeting(
    queue: MagicMock | None = None,
    storage: MagicMock | None = None,
    kg: MagicMock | None = None,
    llm: MagicMock | None = None,
    dna_manager: MagicMock | None = None,
    metrics: MagicMock | None = None,
    config: EmergencyMeetingConfig | None = None,
) -> EmergencyMeeting:
    return EmergencyMeeting(
        queue=queue or _make_queue(),
        storage=storage or _make_storage(),
        knowledge_graph=kg,
        llm=llm or _make_llm(['{"decision":"RETRY","reason":"default"}']),
        run_id="run_test",
        config=config
        or EmergencyMeetingConfig(
            response_timeout_sec=0.1,
            cto_max_retries=1,
            cto_retry_interval_sec=0.0,
            cto_model="test-model",
        ),
        dna_manager=dna_manager,
        qdrant=None,
        metrics=metrics,
    )


# ------------------------------------------------------------------
# 1. Participant selection
# ------------------------------------------------------------------


async def test_select_participants_three_way_with_kg_expert() -> None:
    meeting = _make_meeting(kg=_make_kg(best_responder="mlops"))
    blocking: dict[str, object] = {
        "item_id": "wi_1",
        "agent_id": "backend",
        "dep_source_agent_id": "frontend",
        "reason": "waiting for docker build",
    }
    participants = await meeting._select_participants(blocking)
    assert participants == ["backend", "frontend", "mlops"]


async def test_select_participants_dedup_when_expert_is_owner() -> None:
    meeting = _make_meeting(kg=_make_kg(best_responder="backend"))
    blocking: dict[str, object] = {
        "item_id": "wi_1",
        "agent_id": "backend",
        "reason": "api error",
    }
    participants = await meeting._select_participants(blocking)
    assert participants == ["backend"]


async def test_select_participants_owner_only_when_no_kg() -> None:
    meeting = _make_meeting(kg=None)
    blocking: dict[str, object] = {
        "item_id": "wi_1",
        "agent_id": "mlops",
        "reason": "anything",
    }
    participants = await meeting._select_participants(blocking)
    assert participants == ["mlops"]


# ------------------------------------------------------------------
# 2. Vote collection
# ------------------------------------------------------------------


async def test_collect_votes_marks_timeout_as_abstain() -> None:
    queue = _make_queue()
    queue.receive = AsyncMock(return_value=None)  # simulate timeout
    meeting = _make_meeting(queue=queue)

    from domain.contracts import MeetingRequest

    request = MeetingRequest(
        meeting_id="m1",
        blocking_item_id="wi_1",
        blocking_owner_agent_id="backend",
        participant_agent_ids=["backend", "frontend"],
    )
    votes = await meeting._collect_votes(request)
    assert len(votes) == 2
    assert all(v.abstained for v in votes)
    assert {v.rationale for v in votes} == {"timeout"}


async def test_collect_votes_parses_decision_from_context() -> None:
    queue = _make_queue()
    msg = Message(
        id="m_reply",
        from_agent="backend",
        to_agent="emergency_meeting",
        type=MessageType.ANSWER,
        content="We should retry after fixing the dep",
        context={"decision": "retry"},
    )
    queue.receive = AsyncMock(side_effect=[msg, None])
    meeting = _make_meeting(queue=queue)

    from domain.contracts import MeetingRequest

    request = MeetingRequest(
        meeting_id="m1",
        blocking_item_id="wi_1",
        blocking_owner_agent_id="backend",
        participant_agent_ids=["backend", "frontend"],
    )
    votes = await meeting._collect_votes(request)
    assert len(votes) == 2
    # Note: receive() returns in asyncio.gather order, both tasks share one inbox
    non_abstain = [v for v in votes if not v.abstained]
    assert len(non_abstain) == 1
    assert non_abstain[0].decision is MeetingDecision.RETRY


async def test_collect_votes_invalid_decision_becomes_abstain() -> None:
    queue = _make_queue()
    msg = Message(
        id="m_reply",
        from_agent="backend",
        to_agent="emergency_meeting",
        type=MessageType.ANSWER,
        content="MAYBE_RESTART",  # not a valid decision
        context={},
    )
    queue.receive = AsyncMock(side_effect=[msg])
    meeting = _make_meeting(queue=queue)

    from domain.contracts import MeetingRequest

    request = MeetingRequest(
        meeting_id="m1",
        blocking_item_id="wi_1",
        blocking_owner_agent_id="backend",
        participant_agent_ids=["backend"],
    )
    votes = await meeting._collect_votes(request)
    assert len(votes) == 1
    assert votes[0].abstained is True
    assert votes[0].rationale == "invalid_vote"


# ------------------------------------------------------------------
# 3. DNA-weighted tally and fallback winner
# ------------------------------------------------------------------


async def test_weighted_tally_ignores_abstentions() -> None:
    from domain.contracts import MeetingVote

    meeting = _make_meeting(dna_manager=_make_dna_manager())
    votes = [
        MeetingVote(meeting_id="m1", voter_agent_id="backend", decision=MeetingDecision.RETRY),
        MeetingVote(
            meeting_id="m1",
            voter_agent_id="frontend",
            decision=MeetingDecision.ABORT,
            abstained=True,
        ),
    ]
    tally = await meeting._weighted_tally(votes)
    # backend (neutral 0.5/0.5 → weight 0.5) votes RETRY
    assert tally["RETRY"] == pytest.approx(0.5)
    assert tally["ABORT"] == 0.0


async def test_weighted_tally_uses_dna_weights() -> None:
    from domain.contracts import MeetingVote

    dna = _make_dna_manager(
        weights={
            "backend": (0.9, 0.9),  # weight = 0.9
            "frontend": (0.1, 0.1),  # weight = 0.1
        }
    )
    meeting = _make_meeting(dna_manager=dna)
    votes = [
        MeetingVote(meeting_id="m1", voter_agent_id="backend", decision=MeetingDecision.RETRY),
        MeetingVote(
            meeting_id="m1",
            voter_agent_id="frontend",
            decision=MeetingDecision.ABORT,
        ),
    ]
    tally = await meeting._weighted_tally(votes)
    assert tally["RETRY"] == pytest.approx(0.9)
    assert tally["ABORT"] == pytest.approx(0.1)


async def test_fallback_winner_tie_prefers_blocking_owner() -> None:
    from domain.contracts import MeetingRequest, MeetingVote

    meeting = _make_meeting()
    request = MeetingRequest(
        meeting_id="m1",
        blocking_item_id="wi_1",
        blocking_owner_agent_id="backend",
        participant_agent_ids=["backend", "frontend"],
    )
    votes = [
        MeetingVote(meeting_id="m1", voter_agent_id="backend", decision=MeetingDecision.RETRY),
        MeetingVote(meeting_id="m1", voter_agent_id="frontend", decision=MeetingDecision.ABORT),
    ]
    tally = {"RETRY": 0.5, "ABORT": 0.5, "REROUTE": 0.0, "ESCALATE": 0.0}
    winner = meeting._resolve_fallback_winner(tally, request, votes)
    assert winner is MeetingDecision.RETRY  # owner's vote wins tie


async def test_fallback_winner_all_abstain_returns_escalate() -> None:
    from domain.contracts import MeetingRequest

    meeting = _make_meeting()
    request = MeetingRequest(
        meeting_id="m1",
        blocking_item_id="wi_1",
        blocking_owner_agent_id="backend",
        participant_agent_ids=["backend"],
    )
    tally = {"RETRY": 0.0, "ABORT": 0.0, "REROUTE": 0.0, "ESCALATE": 0.0}
    winner = meeting._resolve_fallback_winner(tally, request, [])
    assert winner is MeetingDecision.ESCALATE


# ------------------------------------------------------------------
# 4. CTO retry + fallback metrics
# ------------------------------------------------------------------


async def test_cto_success_on_first_try_uses_cto_source() -> None:
    llm = _make_llm(['{"decision":"REROUTE","reason":"try frontend"}'])
    meeting = _make_meeting(llm=llm)
    from domain.contracts import MeetingRequest

    request = MeetingRequest(
        meeting_id="m1",
        blocking_item_id="wi_1",
        blocking_owner_agent_id="backend",
        participant_agent_ids=["backend"],
    )
    outcome = await meeting._invoke_cto_with_retry(request, [], {"RETRY": 0.5})
    assert outcome is not None
    decision, reason = outcome
    assert decision is MeetingDecision.REROUTE
    assert reason == "try frontend"


async def test_cto_three_failures_falls_back_and_records_metric() -> None:
    # All 3 attempts return invalid JSON
    llm = _make_llm(["not json 1", "not json 2", "not json 3"])
    metrics = MagicMock()
    metrics.record_fallback = MagicMock()

    config = EmergencyMeetingConfig(
        response_timeout_sec=0.1,
        cto_max_retries=3,
        cto_retry_interval_sec=0.0,
        cto_model="test-model",
    )
    meeting = _make_meeting(llm=llm, metrics=metrics, config=config)

    from domain.contracts import MeetingRequest, MeetingVote

    request = MeetingRequest(
        meeting_id="m1",
        blocking_item_id="wi_1",
        blocking_owner_agent_id="backend",
        participant_agent_ids=["backend"],
    )
    votes = [
        MeetingVote(meeting_id="m1", voter_agent_id="backend", decision=MeetingDecision.RETRY),
    ]
    result = await meeting._aggregate(request, votes)
    assert result.decision_source is DecisionSource.DNA_FALLBACK
    assert result.fallback_reason == "cto_unavailable_after_retries"
    assert metrics.record_fallback.called
    call_kwargs = metrics.record_fallback.call_args.kwargs
    assert call_kwargs["component"] == "emergency_meeting"
    assert call_kwargs["reason"] == "cto_max_retries"
    # 3 LLM attempts were made
    assert llm.generate.call_count == 3


async def test_parse_cto_response_rejects_unknown_decision() -> None:
    meeting = _make_meeting()
    assert meeting._parse_cto_response('{"decision":"NUKE","reason":"x"}') is None


async def test_parse_cto_response_rejects_non_json() -> None:
    meeting = _make_meeting()
    assert meeting._parse_cto_response("not json at all") is None


# ------------------------------------------------------------------
# 5. convene() full round-trip
# ------------------------------------------------------------------


async def test_convene_persists_to_storage_and_counts_participation() -> None:
    queue = _make_queue()
    # Participant returns a RETRY vote
    msg = Message(
        id="m_reply",
        from_agent="backend",
        to_agent="emergency_meeting",
        type=MessageType.ANSWER,
        content="retry",
        context={"decision": "RETRY"},
    )
    queue.receive = AsyncMock(side_effect=[msg])
    storage = _make_storage()
    dna = _make_dna_manager()
    llm = _make_llm(['{"decision":"RETRY","reason":"dep will finish soon"}'])

    meeting = _make_meeting(queue=queue, storage=storage, dna_manager=dna, llm=llm)
    blocking: dict[str, object] = {
        "item_id": "wi_1",
        "agent_id": "backend",
        "reason": "waiting",
    }
    result = await meeting.convene(blocking)

    # Decision was CTO-backed
    assert result.decision_source is DecisionSource.CTO
    assert result.final_decision is MeetingDecision.RETRY
    # SQLite save called with meeting:... key
    saved_key, saved_payload = storage.save.call_args[0]
    assert saved_key.startswith("meeting:")
    assert saved_payload["final_decision"] == "RETRY"
    assert saved_payload["decision_source"] == "cto"
    # Participation increment called once (1 participant: owner only)
    assert dna.update_meeting_participation.await_count == 1

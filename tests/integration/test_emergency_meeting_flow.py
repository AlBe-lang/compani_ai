"""Integration test for Part 7 Stage 1 — StageGate ↔ EmergencyMeeting wiring.

Exercises the full path from ``StageGateMeeting.evaluate_emergency`` through
``EmergencyMeeting.convene`` using real SQLiteStorage + real SQLiteMessageQueue
+ real InProcessEventBus. LLM and KnowledgeGraph are mocked so no Ollama/Qdrant
is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.event_bus import InProcessEventBus
from adapters.sqlite_message_queue import SQLiteMessageQueue
from adapters.sqlite_storage import SQLiteStorage
from application.emergency_meeting import EmergencyMeeting, EmergencyMeetingConfig
from application.stage_gate import GateConfig, GateVerdict, StageGateMeeting
from domain.contracts import Message, MessageType


@pytest.fixture
async def storage() -> SQLiteStorage:
    s = SQLiteStorage(":memory:")
    await s.init()
    return s


@pytest.fixture
def queue(storage: SQLiteStorage) -> SQLiteMessageQueue:
    return SQLiteMessageQueue(storage)


def _make_mock_cto() -> MagicMock:
    """CTOAgent stub — only review_progress used by StageGate.evaluate()."""
    mock = MagicMock()
    mock.review_progress = AsyncMock()
    return mock


def _make_llm_returning(decision: str, reason: str) -> MagicMock:
    mock = MagicMock()

    async def _gen(*args: Any, **kwargs: Any) -> str:
        return f'{{"decision":"{decision}","reason":"{reason}"}}'

    mock.generate = AsyncMock(side_effect=_gen)
    return mock


async def test_stage_gate_delegates_emergency_to_meeting_retry_maps_to_replan(
    storage: SQLiteStorage,
    queue: SQLiteMessageQueue,
) -> None:
    """RETRY decision from meeting → GateVerdict.REPLAN."""
    # Prime the participant's reply BEFORE convening (inbox is pre-seeded)
    reply = Message(
        id="m_reply_1",
        from_agent="backend",
        to_agent="emergency_meeting",
        type=MessageType.ANSWER,
        content="retry please",
        context={"decision": "RETRY"},
    )
    await queue._inbox("emergency_meeting").put(reply)

    llm = _make_llm_returning("RETRY", "dep will finish soon")
    meeting = EmergencyMeeting(
        queue=queue,
        storage=storage,
        knowledge_graph=None,
        llm=llm,
        run_id="run_integration",
        config=EmergencyMeetingConfig(
            response_timeout_sec=0.5,
            cto_max_retries=1,
            cto_retry_interval_sec=0.0,
            cto_model="test",
        ),
    )

    gate = StageGateMeeting(
        cto=_make_mock_cto(),
        event_bus=InProcessEventBus(),
        storage=storage,
        run_id="run_integration",
        config=GateConfig(),
        emergency_meeting=meeting,
    )

    result = await gate.evaluate_emergency(
        {"item_id": "wi_1", "agent_id": "backend", "reason": "waiting for docker build"}
    )

    assert result.verdict is GateVerdict.REPLAN
    assert "meeting_" in result.reason
    assert "source=cto" in result.reason


async def test_stage_gate_delegates_emergency_to_meeting_abort_maps_to_abort(
    storage: SQLiteStorage,
    queue: SQLiteMessageQueue,
) -> None:
    """ABORT decision from meeting → GateVerdict.ABORT (the only halting verdict)."""
    reply = Message(
        id="m_reply_2",
        from_agent="mlops",
        to_agent="emergency_meeting",
        type=MessageType.ANSWER,
        content="cannot recover",
        context={"decision": "ABORT"},
    )
    await queue._inbox("emergency_meeting").put(reply)

    llm = _make_llm_returning("ABORT", "hardware failure")
    meeting = EmergencyMeeting(
        queue=queue,
        storage=storage,
        knowledge_graph=None,
        llm=llm,
        run_id="run_integration_abort",
        config=EmergencyMeetingConfig(
            response_timeout_sec=0.5,
            cto_max_retries=1,
            cto_retry_interval_sec=0.0,
            cto_model="test",
        ),
    )

    gate = StageGateMeeting(
        cto=_make_mock_cto(),
        event_bus=InProcessEventBus(),
        storage=storage,
        run_id="run_integration_abort",
        emergency_meeting=meeting,
    )

    result = await gate.evaluate_emergency(
        {"item_id": "wi_2", "agent_id": "mlops", "reason": "catastrophic failure"}
    )
    assert result.verdict is GateVerdict.ABORT


async def test_stage_gate_without_meeting_falls_back_to_fixed_replan(
    storage: SQLiteStorage,
) -> None:
    """Backward compat: without emergency_meeting injection, legacy REPLAN path."""
    gate = StageGateMeeting(
        cto=_make_mock_cto(),
        event_bus=InProcessEventBus(),
        storage=storage,
        run_id="run_no_meeting",
        emergency_meeting=None,
    )
    result = await gate.evaluate_emergency(
        {"item_id": "wi_3", "agent_id": "frontend", "reason": "ui frozen"}
    )
    assert result.verdict is GateVerdict.REPLAN
    assert "blocking detected on item wi_3" in result.reason

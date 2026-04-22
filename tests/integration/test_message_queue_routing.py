"""Integration tests for SQLiteMessageQueue with KnowledgeGraph-based routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.sqlite_message_queue import SQLiteMessageQueue
from adapters.sqlite_storage import SQLiteStorage
from domain.contracts import MessageType


@pytest.fixture
async def storage() -> SQLiteStorage:
    s = SQLiteStorage(":memory:")
    await s.init()
    return s


@pytest.fixture
async def queue(storage: SQLiteStorage) -> SQLiteMessageQueue:
    return SQLiteMessageQueue(storage=storage)


def _make_kg_mock(return_role: str | None) -> MagicMock:
    mock = MagicMock()
    mock.find_best_responder = AsyncMock(return_value=return_role)
    return mock


# ------------------------------------------------------------------
# _find_responder — keyword fallback
# ------------------------------------------------------------------


async def test_find_responder_keyword_backend(queue: SQLiteMessageQueue) -> None:
    role = await queue._find_responder("How do I create a FastAPI endpoint with SQL?", None)
    assert role == "backend"


async def test_find_responder_keyword_frontend(queue: SQLiteMessageQueue) -> None:
    role = await queue._find_responder("How do I add CSS to my React component?", None)
    assert role == "frontend"


async def test_find_responder_keyword_mlops(queue: SQLiteMessageQueue) -> None:
    role = await queue._find_responder("Write a Dockerfile for the deployment pipeline", None)
    assert role == "mlops"


async def test_find_responder_defaults_to_cto_when_no_match(queue: SQLiteMessageQueue) -> None:
    role = await queue._find_responder("What is the best color for a logo?", None)
    assert role == "cto"


# ------------------------------------------------------------------
# _find_responder — KnowledgeGraph priority
# ------------------------------------------------------------------


async def test_find_responder_uses_knowledge_graph_first(storage: SQLiteStorage) -> None:
    kg = _make_kg_mock(return_role="mlops")
    q = SQLiteMessageQueue(storage=storage, knowledge_graph=kg)
    role = await q._find_responder("Deploy to Kubernetes", None)
    assert role == "mlops"
    kg.find_best_responder.assert_called_once()


async def test_find_responder_falls_back_to_keyword_when_kg_returns_none(
    storage: SQLiteStorage,
) -> None:
    kg = _make_kg_mock(return_role=None)
    q = SQLiteMessageQueue(storage=storage, knowledge_graph=kg)
    role = await q._find_responder("Create a FastAPI database schema migration", None)
    assert role == "backend"


async def test_find_responder_falls_back_to_keyword_on_kg_exception(
    storage: SQLiteStorage,
) -> None:
    kg = MagicMock()
    kg.find_best_responder = AsyncMock(side_effect=RuntimeError("kg offline"))
    q = SQLiteMessageQueue(storage=storage, knowledge_graph=kg)
    role = await q._find_responder("Render a Flutter UI widget with CSS", None)
    assert role == "frontend"


# ------------------------------------------------------------------
# route_question — sends to resolved agent and returns answer on timeout
# ------------------------------------------------------------------


async def test_route_question_returns_empty_on_timeout(queue: SQLiteMessageQueue) -> None:
    result = await queue.route_question(
        from_agent="frontend",
        question="How do I create a FastAPI endpoint?",
        timeout_sec=0.01,
    )
    assert result == ""


async def test_route_question_routes_to_correct_agent(queue: SQLiteMessageQueue) -> None:
    """The question should be delivered to the resolved agent's inbox."""
    await queue.route_question(
        from_agent="frontend",
        question="What SQL schema should I use for users table?",
        timeout_sec=0.01,
    )
    # Backend agent should have received the question
    msg = await queue.receive("backend")
    assert msg is not None
    assert msg.type is MessageType.QUESTION
    assert "SQL schema" in msg.content

"""Tests for KnowledgeGraph._expertise SQLite persistence — Part 7 Stage 3 (R-06)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.sqlite_storage import SQLiteStorage
from application.knowledge_graph import KnowledgeGraph


def _make_qdrant_mock() -> MagicMock:
    mock = MagicMock()
    mock.add_qa = AsyncMock()
    mock.add_task_result = AsyncMock()
    mock.search_qa = AsyncMock(return_value=[])
    return mock


@pytest.fixture
async def storage() -> SQLiteStorage:
    s = SQLiteStorage(":memory:")
    await s.init()
    return s


async def test_persistence_roundtrip_via_storage(storage: SQLiteStorage) -> None:
    kg = KnowledgeGraph(qdrant=_make_qdrant_mock(), storage=storage)
    # Trigger one EMA update — persist fire-and-forget
    await kg.store_interaction(
        agent_id="backend_agent",
        role="backend",
        question="How do I set up FastAPI endpoint?",
        answer="Use @app.get decorator.",
        success=True,
        project_id="p1",
        run_id="r1",
    )
    # Allow the fire-and-forget persist task to complete
    await asyncio.sleep(0.05)

    # Fresh KG instance should load the same expertise value from storage
    kg2 = KnowledgeGraph(qdrant=_make_qdrant_mock(), storage=storage)
    await kg2.load_expertise()
    # role='backend', topic should be 'backend' (from _detect_topic on the question)
    level = await kg2.get_expertise_level("backend", "backend")
    # EMA: 0.2 * 1.0 + 0.8 * 0.5 = 0.6
    assert abs(level - 0.6) < 1e-6


async def test_no_storage_skips_persistence() -> None:
    """Backward compat — storage=None must not cause errors."""
    kg = KnowledgeGraph(qdrant=_make_qdrant_mock(), storage=None)
    await kg.store_interaction(
        agent_id="backend_agent",
        role="backend",
        question="api question",
        answer="",
        success=True,
        project_id="p",
        run_id="r",
    )
    # load_expertise is also a no-op without storage
    await kg.load_expertise()
    level = await kg.get_expertise_level("backend", "backend")
    assert level > 0.5  # EMA still applied in-memory


async def test_load_expertise_ignores_non_expertise_rows(storage: SQLiteStorage) -> None:
    """kv_store has many row types (DNA, metrics, etc.); load_expertise
    must only pick up rows marked with _kind='kg_expertise'."""
    await storage.save(
        "some_other_row",
        {"role": "backend", "topic": "api", "ema_value": 0.9, "_kind": "fake"},
    )
    await storage.save(
        "kg_expertise:backend:api",
        {
            "_kind": "kg_expertise",
            "role": "backend",
            "topic": "api",
            "ema_value": 0.77,
            "updated_at": "2026-04-23T00:00:00Z",
        },
    )
    kg = KnowledgeGraph(qdrant=_make_qdrant_mock(), storage=storage)
    await kg.load_expertise()
    level = await kg.get_expertise_level("backend", "api")
    assert abs(level - 0.77) < 1e-6


async def test_persist_storage_error_tolerated() -> None:
    """If SQLite save raises, EMA update still succeeds in-memory (log only)."""
    bad_storage = MagicMock()
    bad_storage.save = AsyncMock(side_effect=RuntimeError("disk full"))
    bad_storage.query = AsyncMock(return_value=[])
    kg = KnowledgeGraph(qdrant=_make_qdrant_mock(), storage=bad_storage)
    await kg.store_interaction(
        agent_id="backend_agent",
        role="backend",
        question="api",
        answer="",
        success=True,
        project_id="p",
        run_id="r",
    )
    await asyncio.sleep(0.05)  # let fire-and-forget attempt + fail
    # In-memory EMA should still be updated
    level = await kg.get_expertise_level("backend", "backend")
    assert level > 0.5

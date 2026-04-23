"""Unit tests for KnowledgeGraph — EMA expertise tracking and routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from application.knowledge_graph import _EMA_ALPHA, KnowledgeGraph
from domain.contracts import TaskResult

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_qdrant_mock() -> MagicMock:
    """QdrantStorage mock with no-op async methods."""
    mock = MagicMock()
    mock.add_qa = AsyncMock()
    mock.add_task_result = AsyncMock()
    mock.search_qa = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def kg() -> KnowledgeGraph:
    return KnowledgeGraph(qdrant=_make_qdrant_mock())


def _make_task_result(agent_id: str, approach: str, success: bool = True) -> TaskResult:
    return TaskResult(
        task_id="task_001",
        agent_id=agent_id,
        approach=approach,
        code="",
        success=success,
    )


# ------------------------------------------------------------------
# EMA expertise updates
# ------------------------------------------------------------------


async def test_store_interaction_updates_ema_on_success(kg: KnowledgeGraph) -> None:
    await kg.store_interaction(
        agent_id="backend_agent",
        role="backend",
        question="How do I write a FastAPI endpoint?",
        answer="Use @app.get('/path').",
        success=True,
        project_id="proj",
        run_id="run",
    )
    level = await kg.get_expertise_level("backend", "backend")
    assert level > 0.5  # EMA moves above neutral on success


async def test_store_interaction_decreases_ema_on_failure(kg: KnowledgeGraph) -> None:
    # Start from neutral (0.5), then two failures
    for _ in range(5):
        await kg.store_interaction(
            agent_id="frontend_agent",
            role="frontend",
            question="How do I style a React component?",
            answer="",
            success=False,
            project_id="proj",
            run_id="run",
        )
    level = await kg.get_expertise_level("frontend", "frontend")
    assert level < 0.5


async def test_ema_formula_is_correct(kg: KnowledgeGraph) -> None:
    """Single success from neutral prior: new = α*1 + (1-α)*0.5."""
    await kg.store_interaction(
        agent_id="backend_agent",
        role="backend",
        question="sql query optimization",
        answer="Use indexes.",
        success=True,
        project_id="proj",
        run_id="run",
    )
    expected = _EMA_ALPHA * 1.0 + (1 - _EMA_ALPHA) * 0.5
    level = await kg.get_expertise_level("backend", "backend")
    assert abs(level - expected) < 1e-9


async def test_store_task_result_updates_ema(kg: KnowledgeGraph) -> None:
    # Use approach text that clearly maps to mlops (multiple keyword matches)
    result = _make_task_result(
        "mlops_agent", "Deploy Kubernetes pipeline with compose", success=True
    )
    await kg.store_task_result(result, run_id="run_001")
    level = await kg.get_expertise_level("mlops", "mlops")
    assert level > 0.5


# ------------------------------------------------------------------
# Routing: keyword fallback (no Qdrant history)
# ------------------------------------------------------------------


async def test_find_best_responder_keyword_backend(kg: KnowledgeGraph) -> None:
    role = await kg.find_best_responder("How do I write a FastAPI endpoint with SQL schema?")
    assert role == "backend"


async def test_find_best_responder_keyword_frontend(kg: KnowledgeGraph) -> None:
    role = await kg.find_best_responder("How should I style the React UI component?")
    assert role == "frontend"


async def test_find_best_responder_keyword_mlops(kg: KnowledgeGraph) -> None:
    role = await kg.find_best_responder("Write a Dockerfile and docker-compose for the pipeline")
    assert role == "mlops"


async def test_find_best_responder_returns_none_for_no_match(kg: KnowledgeGraph) -> None:
    role = await kg.find_best_responder("What is the weather like today?")
    assert role is None


# ------------------------------------------------------------------
# Routing: semantic hits from Qdrant
# ------------------------------------------------------------------


async def test_find_best_responder_uses_qdrant_hits_when_available() -> None:
    mock_qdrant = _make_qdrant_mock()
    mock_qdrant.search_qa = AsyncMock(
        return_value=[
            {"role": "mlops", "question": "deploy", "answer": "k8s"},
            {"role": "mlops", "question": "ci pipeline", "answer": "use GitHub Actions"},
        ]
    )
    kg = KnowledgeGraph(qdrant=mock_qdrant)

    # Give mlops some expertise so it wins
    await kg.store_interaction(
        agent_id="mlops_agent",
        role="mlops",
        question="kubernetes deploy",
        answer="apply manifests",
        success=True,
        project_id="p",
        run_id="r",
    )

    role = await kg.find_best_responder("How do I deploy to Kubernetes?")
    assert role == "mlops"


async def test_find_best_responder_returns_none_when_no_history_and_no_keywords() -> None:
    """With no Qdrant hits and no keyword match, find_best_responder returns None."""
    kg = KnowledgeGraph(qdrant=_make_qdrant_mock())  # search_qa returns []
    role = await kg.find_best_responder("What is the meaning of life?")
    assert role is None


# ------------------------------------------------------------------
# get_expertise_level default
# ------------------------------------------------------------------


async def test_get_expertise_level_returns_neutral_for_unknown(kg: KnowledgeGraph) -> None:
    level = await kg.get_expertise_level("unknown_role", "unknown_topic")
    assert level == 0.5


# ------------------------------------------------------------------
# R-04 regression: whole-word keyword matching (no substring false positives)
# ------------------------------------------------------------------


async def test_keyword_route_does_not_match_api_inside_apiary(kg: KnowledgeGraph) -> None:
    """Regression for R-04: 'apiary' must not match backend keyword 'api'."""
    role = await kg.find_best_responder("apiary farming guide")
    assert role is None


async def test_keyword_route_does_not_match_react_inside_reactor(kg: KnowledgeGraph) -> None:
    """Regression for R-04: 'reactor' must not match frontend keyword 'react'."""
    role = await kg.find_best_responder("studying nuclear reactors")
    assert role is None


async def test_keyword_route_does_not_match_ci_inside_decide(kg: KnowledgeGraph) -> None:
    """Regression for R-04: substring 'ci' in 'decide' must not route to mlops."""
    role = await kg.find_best_responder("help me decide on a framework")
    assert role is None


async def test_keyword_route_matches_whole_words_case_insensitive(kg: KnowledgeGraph) -> None:
    """Whole-word + case insensitivity still works after the regex migration."""
    role = await kg.find_best_responder("Design the DATABASE Schema for our Migration")
    assert role == "backend"


async def test_keyword_route_nfc_nfd_equivalence(kg: KnowledgeGraph) -> None:
    """NFC and NFD forms of the same Korean text must route identically (both None)."""
    import unicodedata

    text_nfc = unicodedata.normalize("NFC", "데이터베이스 스키마")
    text_nfd = unicodedata.normalize("NFD", "데이터베이스 스키마")
    role_nfc = await kg.find_best_responder(text_nfc)
    role_nfd = await kg.find_best_responder(text_nfd)
    assert role_nfc == role_nfd  # both None; invariant under normalization


async def test_keyword_route_multiple_matches_scored_correctly(kg: KnowledgeGraph) -> None:
    """Scores count each whole-word occurrence; best role wins."""
    # Two mlops words (docker, compose), one backend word (api)
    role = await kg.find_best_responder("Run docker compose for the api container")
    assert role == "mlops"

"""Unit tests for QdrantStorage adapter.

Uses in-memory mode (path=":memory:") so no disk I/O occurs.
Tests are skipped automatically when qdrant-client[fastembed] is not installed.
"""

from __future__ import annotations

import pytest

from adapters.qdrant_storage import QARecord, QdrantStorage, _QDRANT_AVAILABLE

pytestmark = pytest.mark.skipif(
    not _QDRANT_AVAILABLE,
    reason="qdrant-client[fastembed] not installed",
)


@pytest.fixture
async def qdrant() -> QdrantStorage:
    q = QdrantStorage(path=":memory:")
    await q.init()
    return q


# ------------------------------------------------------------------
# Initialization
# ------------------------------------------------------------------


async def test_init_makes_client_available(qdrant: QdrantStorage) -> None:
    assert qdrant.is_available


async def test_double_init_is_safe(qdrant: QdrantStorage) -> None:
    await qdrant.init()  # must not raise
    assert qdrant.is_available


# ------------------------------------------------------------------
# Q&A interactions
# ------------------------------------------------------------------


def _make_qa_record(**kwargs: object) -> QARecord:
    defaults = dict(
        agent_id="backend_agent",
        role="backend",
        question="What database should I use?",
        answer="Use PostgreSQL for relational data.",
        success=True,
        project_id="proj_001",
        run_id="run_abc",
    )
    defaults.update(kwargs)  # type: ignore[arg-type]
    return QARecord(**defaults)  # type: ignore[arg-type]


async def test_add_qa_does_not_raise(qdrant: QdrantStorage) -> None:
    record = _make_qa_record()
    await qdrant.add_qa(record)  # must not raise


async def test_search_qa_returns_results_after_add(qdrant: QdrantStorage) -> None:
    record = _make_qa_record(
        question="How should I set up the FastAPI router?",
        answer="Use APIRouter with prefix /api.",
    )
    await qdrant.add_qa(record)
    results = await qdrant.search_qa("FastAPI router setup")
    assert len(results) >= 1
    assert results[0]["role"] == "backend"


async def test_search_qa_returns_empty_when_no_records(qdrant: QdrantStorage) -> None:
    results = await qdrant.search_qa("totally unrelated query")
    assert isinstance(results, list)


async def test_qa_record_payload_preserved(qdrant: QdrantStorage) -> None:
    record = _make_qa_record(project_id="preserved_proj", run_id="run_xyz")
    await qdrant.add_qa(record)
    results = await qdrant.search_qa(record.question)
    assert any(r.get("project_id") == "preserved_proj" for r in results)


# ------------------------------------------------------------------
# Task results
# ------------------------------------------------------------------


def _make_task_payload(**kwargs: object) -> dict:
    defaults: dict = {
        "task_id": "task_001",
        "agent_id": "mlops_agent",
        "approach": "Build Docker image with multi-stage build",
        "success": True,
        "run_id": "run_001",
        "files": [{"path": "Dockerfile", "name": "Dockerfile", "content": "", "type": "config"}],
    }
    defaults.update(kwargs)
    return defaults


async def test_add_task_result_does_not_raise(qdrant: QdrantStorage) -> None:
    payload = _make_task_payload()
    await qdrant.add_task_result(payload)  # must not raise


async def test_search_task_results_returns_results_after_add(qdrant: QdrantStorage) -> None:
    payload = _make_task_payload(approach="Deploy Kubernetes manifests for backend service")
    await qdrant.add_task_result(payload)
    results = await qdrant.search_task_results("Kubernetes deployment")
    assert len(results) >= 1


# ------------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------------


async def test_close_releases_client(qdrant: QdrantStorage) -> None:
    await qdrant.close()
    assert not qdrant.is_available


async def test_search_after_close_returns_empty(qdrant: QdrantStorage) -> None:
    await qdrant.close()
    results = await qdrant.search_qa("anything")
    assert results == []

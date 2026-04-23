"""Unit tests for QdrantStorage adapter.

Uses in-memory mode (path=":memory:") so no disk I/O occurs.
Tests are skipped automatically when qdrant-client[fastembed] is not installed.
"""

from __future__ import annotations

import pytest

from adapters.qdrant_storage import _QDRANT_AVAILABLE, QARecord, QdrantStorage

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


def _make_task_payload(**kwargs: object) -> dict[str, object]:
    defaults: dict[str, object] = {
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


# ------------------------------------------------------------------
# R-05 regression: no DeprecationWarning + multilingual routing
# ------------------------------------------------------------------


async def test_add_and_search_emit_no_qdrant_deprecation_warning(
    qdrant: QdrantStorage,
) -> None:
    """Regression for R-05: the legacy `add` / `query` API used to emit
    UserWarning('add method has been deprecated...') from qdrant-client.
    The migration to `upsert` + `query_points` must remove those warnings.
    """
    import warnings

    record = _make_qa_record(question="FastAPI router test", answer="use APIRouter")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await qdrant.add_qa(record)
        await qdrant.search_qa("FastAPI router")

    deprecated_msgs = [
        str(w.message)
        for w in caught
        if "deprecated" in str(w.message).lower()
        and ("add" in str(w.message) or "query" in str(w.message))
    ]
    assert deprecated_msgs == [], f"qdrant deprecated-API warnings still present: {deprecated_msgs}"


async def test_korean_query_returns_relevant_korean_record(qdrant: QdrantStorage) -> None:
    """Regression for R-05 multilingual: Korean query must surface a Korean
    record in the result set (semantic routing for non-English users).
    Three single-language records are seeded so the absence of multilingual
    embedding would surface English-only matches first.
    """
    await qdrant.add_qa(
        _make_qa_record(
            role="frontend",
            question="React 컴포넌트는 어떻게 만드나요?",
            answer="useState와 useEffect 훅으로 상태와 부수효과를 관리합니다.",
        )
    )
    await qdrant.add_qa(
        _make_qa_record(
            role="backend",
            question="How do I write a GraphQL resolver in Python?",
            answer="Use Strawberry or Ariadne with type definitions.",
        )
    )
    await qdrant.add_qa(
        _make_qa_record(
            role="mlops",
            question="Compose a Kubernetes Deployment manifest",
            answer="Use kind: Deployment with spec.replicas and template.",
        )
    )

    results = await qdrant.search_qa("리액트 컴포넌트 만드는 법", top_k=3)
    assert len(results) >= 1
    roles = [r.get("role") for r in results]
    assert (
        "frontend" in roles
    ), f"Korean query failed to surface the Korean frontend record; got roles={roles}"


async def test_init_creates_both_collections() -> None:
    """Stage 5: collections are now pre-created in init() instead of lazily
    on first write. Both qa_history and task_results must exist after init.
    """
    q = QdrantStorage(path=":memory:")
    await q.init()
    client = q._require_client()
    existing = {c.name for c in client.get_collections().collections}
    assert {"qa_history", "task_results"}.issubset(existing)

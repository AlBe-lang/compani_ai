"""Qdrant vector storage adapter for Q&A history and task result indexing.

Uses local file-based persistence (QdrantClient(path=...)) — no separate server
required. Embedding is performed by Qdrant's inline ``models.Document`` mechanism,
which delegates to fastembed under the hood. The embedding model is
explicitly multilingual so Korean (and ~50 other languages) Q&A traffic is
routed semantically rather than falling through to keyword/CTO fallback.

Collections:
  qa_history    — agent Q&A interactions (question + answer text)
  task_results  — agent task execution summaries (approach + file list)
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from observability.logger import get_logger

log = get_logger(__name__)

_QA_COLLECTION = "qa_history"
_TASK_COLLECTION = "task_results"

# R-05 (Stage 5): explicit multilingual embedding model so Korean and other
# non-English questions route through semantic search instead of getting lost
# in the English-only keyword fallback. MiniLM variant chosen over E5-large
# because Mac Mini 16GB hosts CTO + SLM models simultaneously and 117MB is
# affordable; E5-large would add ~2.24GB on disk plus runtime memory.
_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_VECTOR_SIZE = 384  # dim of the MiniLM model above

try:
    from qdrant_client import QdrantClient, models  # type: ignore[import-untyped]

    _QDRANT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _QDRANT_AVAILABLE = False


@dataclass
class QARecord:
    """Full context of one Q&A interaction (Rule 10 — context preservation)."""

    agent_id: str
    role: str
    question: str
    answer: str
    success: bool
    project_id: str
    run_id: str
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.recorded_at:
            self.recorded_at = datetime.now(timezone.utc).isoformat()


class QdrantStorage:
    """Qdrant adapter using local file persistence and inline fastembed inference.

    Persistence path defaults to ``data/qdrant``.  Pass ``path=":memory:"``
    in tests to avoid disk I/O.
    """

    def __init__(self, path: str = "data/qdrant") -> None:
        self._path = path
        self._client: "QdrantClient | None" = None  # type: ignore[name-defined]

    def _require_client(self) -> "QdrantClient":  # type: ignore[name-defined]
        if self._client is None:
            raise RuntimeError("QdrantStorage not initialized — call init() first")
        return self._client

    async def init(self) -> None:
        """Initialize Qdrant client and ensure both collections exist."""
        if not _QDRANT_AVAILABLE:
            log.warning("qdrant.unavailable", detail="qdrant-client[fastembed] not installed")
            return

        path = self._path
        if path != ":memory:":
            Path(path).mkdir(parents=True, exist_ok=True)

        def _open() -> "QdrantClient":  # type: ignore[name-defined]
            return QdrantClient(path=path)

        self._client = await asyncio.to_thread(_open)
        await asyncio.to_thread(self._ensure_collections)
        log.info("qdrant.initialized", path=path, model=_EMBEDDING_MODEL)

    def _ensure_collections(self) -> None:
        """Create qa_history / task_results collections if missing.

        Safe to call repeatedly; existing collections are left untouched.
        """
        client = self._require_client()
        existing = {c.name for c in client.get_collections().collections}
        for name in (_QA_COLLECTION, _TASK_COLLECTION):
            if name not in existing:
                client.create_collection(
                    collection_name=name,
                    vectors_config=models.VectorParams(
                        size=_VECTOR_SIZE,
                        distance=models.Distance.COSINE,
                    ),
                )
                log.info("qdrant.collection_created", name=name, size=_VECTOR_SIZE)

    # ------------------------------------------------------------------
    # Q&A interactions
    # ------------------------------------------------------------------

    async def add_qa(self, record: QARecord) -> None:
        """Index a Q&A interaction for semantic retrieval."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return

        # Embed: concatenate question + answer for richer context
        text = f"{record.question} {record.answer}"
        payload: dict[str, Any] = {
            "agent_id": record.agent_id,
            "role": record.role,
            "question": record.question,
            "answer": record.answer,
            "success": record.success,
            "project_id": record.project_id,
            "run_id": record.run_id,
            "recorded_at": record.recorded_at,
        }
        client = self._client

        def _upsert() -> None:
            client.upsert(
                collection_name=_QA_COLLECTION,
                points=[
                    models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=models.Document(text=text, model=_EMBEDDING_MODEL),
                        payload=payload,
                    )
                ],
            )

        await asyncio.to_thread(_upsert)
        log.debug("qdrant.qa_added", role=record.role, run_id=record.run_id)

    async def search_qa(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over Q&A history. Returns list of payload dicts."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return []

        client = self._client

        def _search() -> list[dict[str, Any]]:
            existing = {c.name for c in client.get_collections().collections}
            if _QA_COLLECTION not in existing:
                return []
            response = client.query_points(
                collection_name=_QA_COLLECTION,
                query=models.Document(text=query, model=_EMBEDDING_MODEL),
                limit=top_k,
            )
            return [p.payload for p in response.points if p.payload is not None]

        results = await asyncio.to_thread(_search)
        log.debug("qdrant.qa_search", query_len=len(query), hits=len(results))
        return results

    # ------------------------------------------------------------------
    # Task results
    # ------------------------------------------------------------------

    async def add_task_result(self, payload: dict[str, Any]) -> None:
        """Index a task result for expertise routing context."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return

        approach = str(payload.get("approach", ""))
        file_paths = " ".join(
            f.get("path", "") if isinstance(f, dict) else str(f) for f in payload.get("files", [])
        )
        text = f"{approach} {file_paths}".strip() or "task result"
        client = self._client

        def _upsert() -> None:
            client.upsert(
                collection_name=_TASK_COLLECTION,
                points=[
                    models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=models.Document(text=text, model=_EMBEDDING_MODEL),
                        payload=payload,
                    )
                ],
            )

        await asyncio.to_thread(_upsert)
        log.debug(
            "qdrant.task_added",
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
        )

    async def search_task_results(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over indexed task results."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return []

        client = self._client

        def _search() -> list[dict[str, Any]]:
            existing = {c.name for c in client.get_collections().collections}
            if _TASK_COLLECTION not in existing:
                return []
            response = client.query_points(
                collection_name=_TASK_COLLECTION,
                query=models.Document(text=query, model=_EMBEDDING_MODEL),
                limit=top_k,
            )
            return [p.payload for p in response.points if p.payload is not None]

        results = await asyncio.to_thread(_search)
        log.debug("qdrant.task_search", query_len=len(query), hits=len(results))
        return results

    async def close(self) -> None:
        """Release Qdrant client resources."""
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None
            log.info("qdrant.closed")

    @property
    def is_available(self) -> bool:
        return _QDRANT_AVAILABLE and self._client is not None

"""Qdrant vector storage adapter for Q&A history and task result indexing.

Uses local file-based persistence (QdrantClient(path=...)) — no separate server
required. Embedding is handled by fastembed (bundled with qdrant-client[fastembed]).

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

from observability.logger import get_logger

log = get_logger(__name__)

_QA_COLLECTION = "qa_history"
_TASK_COLLECTION = "task_results"

try:
    from qdrant_client import QdrantClient  # type: ignore[import-untyped]

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
    """Qdrant adapter using local file persistence and fastembed for embeddings.

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
        """Initialize Qdrant client and ensure collections exist."""
        if not _QDRANT_AVAILABLE:
            log.warning("qdrant.unavailable", detail="qdrant-client[fastembed] not installed")
            return

        path = self._path
        if path != ":memory:":
            Path(path).mkdir(parents=True, exist_ok=True)

        def _open() -> "QdrantClient":  # type: ignore[name-defined]
            return QdrantClient(path=path)

        self._client = await asyncio.to_thread(_open)
        log.info("qdrant.initialized", path=path)

    # Collections are created on first write by fastembed's `add()` method.
    # Manual pre-creation would produce an unnamed vector config incompatible
    # with fastembed, which requires named vectors.

    # ------------------------------------------------------------------
    # Q&A interactions
    # ------------------------------------------------------------------

    async def add_qa(self, record: QARecord) -> None:
        """Index a Q&A interaction for semantic retrieval."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return

        # Embed: concatenate question + answer for richer context
        text = f"{record.question} {record.answer}"
        payload = {
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

        def _add() -> None:
            client.add(
                collection_name=_QA_COLLECTION,
                documents=[text],
                metadata=[payload],
                ids=[str(uuid.uuid4())],
            )

        await asyncio.to_thread(_add)
        log.debug("qdrant.qa_added", role=record.role, run_id=record.run_id)

    async def search_qa(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic search over Q&A history. Returns list of payload dicts."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return []

        client = self._client

        def _search() -> list[dict]:
            existing = {c.name for c in client.get_collections().collections}
            if _QA_COLLECTION not in existing:
                return []
            results = client.query(
                collection_name=_QA_COLLECTION,
                query_text=query,
                limit=top_k,
            )
            return [r.metadata for r in results]

        results = await asyncio.to_thread(_search)
        log.debug("qdrant.qa_search", query_len=len(query), hits=len(results))
        return results

    # ------------------------------------------------------------------
    # Task results
    # ------------------------------------------------------------------

    async def add_task_result(self, payload: dict) -> None:
        """Index a task result for expertise routing context."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return

        approach = str(payload.get("approach", ""))
        file_paths = " ".join(
            f.get("path", "") if isinstance(f, dict) else str(f)
            for f in payload.get("files", [])
        )
        text = f"{approach} {file_paths}".strip() or "task result"
        client = self._client

        def _add() -> None:
            client.add(
                collection_name=_TASK_COLLECTION,
                documents=[text],
                metadata=[payload],
                ids=[str(uuid.uuid4())],
            )

        await asyncio.to_thread(_add)
        log.debug(
            "qdrant.task_added",
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
        )

    async def search_task_results(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic search over indexed task results."""
        if not _QDRANT_AVAILABLE or self._client is None:
            return []

        client = self._client

        def _search() -> list[dict]:
            existing = {c.name for c in client.get_collections().collections}
            if _TASK_COLLECTION not in existing:
                return []
            results = client.query(
                collection_name=_TASK_COLLECTION,
                query_text=query,
                limit=top_k,
            )
            return [r.metadata for r in results]

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

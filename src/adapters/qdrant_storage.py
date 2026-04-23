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

# Part 6 S5 default — multilingual MiniLM. Part 8 Stage 1 upgraded default
# to mpnet-base-v2 for +15% MTEB 다국어 quality on Mac Mini 16GB budget
# (~420MB). Callers can override via QdrantStorage(embedding_model=...).
# EmbeddingPreset enum lives in application.agent_factory to keep this
# adapter layer free of application-config knowledge.
_DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
_DEFAULT_VECTOR_SIZE = 768  # dim of mpnet-base-v2

# Known model → vector dimension mapping. Updated alongside EmbeddingPreset.
_MODEL_DIMENSIONS: dict[str, int] = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": 768,
    "intfloat/multilingual-e5-large": 1024,
}

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

    Part 8 Stage 1 added ``embedding_model`` parameter (R-05B/C). When the
    requested model's vector dimension differs from an existing collection's
    configured dimension, ``init()`` recreates the collection if
    ``allow_recreate=True`` (WARN log + data loss) or raises a clear
    ``AdapterError`` otherwise. Default ``allow_recreate=True`` matches
    Part 6 Stage 5 behaviour where no accumulated data existed; production
    deployments with real data should set ``allow_recreate=False``.
    """

    def __init__(
        self,
        path: str = "data/qdrant",
        embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
        *,
        allow_recreate: bool = True,
    ) -> None:
        self._path = path
        self._embedding_model = embedding_model
        self._vector_size = _MODEL_DIMENSIONS.get(embedding_model, _DEFAULT_VECTOR_SIZE)
        self._allow_recreate = allow_recreate
        self._client: "QdrantClient | None" = None  # type: ignore[name-defined]

    def _require_client(self) -> "QdrantClient":  # type: ignore[name-defined]
        if self._client is None:
            raise RuntimeError("QdrantStorage not initialized — call init() first")
        return self._client

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    @property
    def vector_size(self) -> int:
        return self._vector_size

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
        log.info(
            "qdrant.initialized",
            path=path,
            model=self._embedding_model,
            vector_size=self._vector_size,
        )

    def _ensure_collections(self) -> None:
        """Create or reconcile qa_history / task_results collections.

        Dimension reconciliation (Part 8 Stage 1):
          - Missing collection           → create with current vector_size.
          - Collection with same size    → leave alone.
          - Collection with wrong size   → if allow_recreate=True, delete+recreate
            with WARN; otherwise raise ``AdapterError`` with clear guidance.
        """
        client = self._require_client()
        existing_names = {c.name for c in client.get_collections().collections}
        for name in (_QA_COLLECTION, _TASK_COLLECTION):
            if name in existing_names:
                current_size = self._get_collection_vector_size(name)
                if current_size == self._vector_size:
                    continue
                if not self._allow_recreate:
                    raise RuntimeError(
                        f"Qdrant collection '{name}' uses vector size {current_size} "
                        f"but embedding model '{self._embedding_model}' requires "
                        f"{self._vector_size}. To migrate (destructive), re-create "
                        f"QdrantStorage with allow_recreate=True or delete the "
                        f"collection manually."
                    )
                log.warning(
                    "qdrant.collection_recreating",
                    name=name,
                    old_size=current_size,
                    new_size=self._vector_size,
                    reason="embedding_model_changed",
                )
                client.delete_collection(collection_name=name)
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=self._vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            log.info("qdrant.collection_created", name=name, size=self._vector_size)

    def _get_collection_vector_size(self, name: str) -> int:
        """Extract configured vector size from an existing collection.

        Qdrant exposes vector params under ``collection.config.params.vectors``
        which can be a single ``VectorParams`` or a dict (named vectors) — the
        type stub also permits ``None``. We assume the unnamed (default)
        configuration this adapter creates and fall back to the configured
        size if the shape is unexpected.
        """
        client = self._require_client()
        info = client.get_collection(collection_name=name)
        vectors = info.config.params.vectors
        if vectors is None:
            return self._vector_size
        size_attr = getattr(vectors, "size", None)
        if size_attr is not None:
            return int(size_attr)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            return int(getattr(first, "size", self._vector_size))
        return self._vector_size

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
                        vector=models.Document(text=text, model=self._embedding_model),
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
                query=models.Document(text=query, model=self._embedding_model),
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
                        vector=models.Document(text=text, model=self._embedding_model),
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
                query=models.Document(text=query, model=self._embedding_model),
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

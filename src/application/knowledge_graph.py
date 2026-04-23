"""Knowledge graph for agent expertise tracking and Q&A routing.

Implements KnowledgeGraphPort using QdrantStorage for vector retrieval.

Expertise is tracked per (role, topic) pair using Exponential Moving Average
(EMA, α=0.2) — per Rule 10: simple replacement discards learning history.

Routing priority:
  1. KnowledgeGraph.find_best_responder() — semantic similarity + expertise_level
  2. Keyword fallback — deterministic role assignment by topic keywords
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from adapters.qdrant_storage import QARecord, QdrantStorage
from domain.contracts import TaskResult
from observability.logger import get_logger

if TYPE_CHECKING:
    from domain.ports import StoragePort

log = get_logger(__name__)

_EMA_ALPHA = 0.2  # Rule 10: EMA instead of simple replacement
_MIN_HITS_FOR_ROUTING = 2  # minimum matching records before trusting KnowledgeGraph
_SIMILARITY_THRESHOLD = 0.65  # minimum cosine similarity to consider a result useful
# Part 7 Stage 3 (R-06): SQLite persistence key prefix for expertise EMA values.
# Same kv_store row pattern as DNAManager uses (no dedicated table lookup),
# so the 005_expertise.sql migration is declarative only — schema exists for
# future direct SQL analytics but runtime data flows through kv_store.
_EXPERTISE_KEY_PREFIX = "kg_expertise:"

# Keyword fallback routing table (from SYSTEM_ARCHITECTURE.md §4.5).
# R-04 (Stage 4): matched with whole-word boundaries, not substring — prevents
# false positives like "apiary" → api or "reactor" → react. Korean queries are
# intentionally not routed by keyword; they fall through to semantic search
# (multilingual embedding, R-05) and finally to the CTO fallback.
_KEYWORD_ROUTING: dict[str, list[str]] = {
    "backend": ["api", "database", "sql", "endpoint", "schema", "model", "migration", "fastapi"],
    "frontend": ["ui", "component", "css", "react", "flutter", "widget", "style", "render"],
    "mlops": ["deploy", "docker", "dockerfile", "compose", "ci", "pipeline", "kubernetes"],
}


def _compile_keyword_patterns(
    routing: dict[str, list[str]],
) -> dict[str, re.Pattern[str]]:
    """Pre-compile one whole-word regex per role for O(1) lookup per call."""
    return {
        role: re.compile(
            r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")\b",
            re.IGNORECASE,
        )
        for role, keywords in routing.items()
    }


_KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = _compile_keyword_patterns(_KEYWORD_ROUTING)


def _normalize(text: str) -> str:
    """NFC-normalize input so NFD-encoded Korean (or other) text matches consistently."""
    return unicodedata.normalize("NFC", text)


class KnowledgeGraph:
    """Expertise-aware Q&A router backed by Qdrant vector search.

    Wraps QdrantStorage and maintains an in-memory EMA table for fast
    expertise lookups between Qdrant queries.
    """

    def __init__(
        self,
        qdrant: QdrantStorage,
        storage: "StoragePort | None" = None,
    ) -> None:
        self._qdrant = qdrant
        self._storage = storage  # Part 7 Stage 3: optional — enables EMA persistence
        # {role: {topic: ema_expertise_level}}
        self._expertise: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------
    # KnowledgeGraphPort interface
    # ------------------------------------------------------------------

    async def store_interaction(
        self,
        agent_id: str,
        role: str,
        question: str,
        answer: str,
        success: bool,
        project_id: str,
        run_id: str,
    ) -> None:
        """Persist Q&A interaction to Qdrant and update expertise EMA.

        Stores full context (question, answer, success, agent_id, project_id,
        run_id, timestamp) per Rule 10 — context preservation.
        """
        record = QARecord(
            agent_id=agent_id,
            role=role,
            question=question,
            answer=answer,
            success=success,
            project_id=project_id,
            run_id=run_id,
        )
        await self._qdrant.add_qa(record)

        # Update expertise EMA for detected topic keywords
        topic = self._detect_topic(question)
        self._update_expertise_ema(role, topic, success)

        log.info(
            "knowledge_graph.interaction_stored",
            role=role,
            topic=topic,
            success=success,
            run_id=run_id,
        )

    async def store_task_result(self, result: TaskResult, run_id: str) -> None:
        """Index task result for future routing context.

        Called after each successful task so KnowledgeGraph can route
        similar future questions to the agent that succeeded on related work.
        """
        payload = {
            "task_id": result.task_id,
            "agent_id": result.agent_id,
            "approach": result.approach,
            "success": result.success,
            "run_id": run_id,
            "files": [f.model_dump(mode="json") for f in result.files],
        }
        await self._qdrant.add_task_result(payload)

        # Update expertise EMA based on task result success
        role = self._role_from_agent_id(result.agent_id)
        topic = self._detect_topic(result.approach)
        self._update_expertise_ema(role, topic, result.success)

        log.info(
            "knowledge_graph.task_result_stored",
            agent_id=result.agent_id,
            task_id=result.task_id,
            success=result.success,
        )

    async def find_best_responder(
        self,
        question: str,
        context: dict[str, object] | None = None,
    ) -> str | None:
        """Return the agent role best suited to answer the question.

        Strategy:
          1. Semantic search in qa_history for similar past Q&A
          2. Among results with score ≥ threshold, pick role with highest expertise
          3. If not enough history, fall back to keyword routing
          4. Return None if no match found (caller should route to CTO)
        """
        # Step 1: semantic search
        hits = await self._qdrant.search_qa(query=question, top_k=5)

        if len(hits) >= _MIN_HITS_FOR_ROUTING:
            # Step 2: aggregate expertise by role from hits
            role_scores: dict[str, float] = {}
            for hit in hits:
                role = str(hit.get("role", ""))
                if not role:
                    continue
                topic = self._detect_topic(question)
                expertise = self._get_expertise(role, topic)
                role_scores[role] = max(role_scores.get(role, 0.0), expertise)

            if role_scores:
                best_role = max(role_scores, key=lambda r: role_scores[r])
                log.info(
                    "knowledge_graph.routing.semantic",
                    question_len=len(question),
                    best_role=best_role,
                    expertise=role_scores[best_role],
                )
                return best_role

        # Step 3: keyword fallback
        keyword_role = self._keyword_route(question)
        if keyword_role:
            log.info(
                "knowledge_graph.routing.keyword_fallback",
                question_len=len(question),
                best_role=keyword_role,
            )
            return keyword_role

        return None

    async def get_expertise_level(self, role: str, topic: str) -> float:
        """Return EMA expertise level [0.0, 1.0] for a role on a topic."""
        return self._get_expertise(role, topic)

    async def load_expertise(self) -> None:
        """Part 7 Stage 3 (R-06) — populate in-memory expertise from SQLite.

        Call once at startup before normal routing begins. Missing storage
        or empty results are silently tolerated (first-run / testing).
        No-op when ``storage`` was not injected at construction.
        """
        if self._storage is None:
            return
        try:
            rows = await self._storage.query()
        except Exception as exc:
            log.warning("knowledge_graph.load_expertise_error", detail=str(exc))
            return
        loaded = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            # Rows we care about must look like the record we save; other
            # kv_store rows (DNA, metrics, etc.) are ignored by field presence.
            if (
                "role" in row
                and "topic" in row
                and "ema_value" in row
                and "_kind" in row
                and row.get("_kind") == "kg_expertise"
            ):
                role = str(row["role"])
                topic = str(row["topic"])
                try:
                    value = float(row["ema_value"])  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
                self._expertise.setdefault(role, {})[topic] = value
                loaded += 1
        log.info("knowledge_graph.expertise_loaded", count=loaded)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_expertise_ema(self, role: str, topic: str, success: bool) -> None:
        """Apply EMA update: new = α * current_sample + (1 − α) * previous.

        When ``storage`` is injected (Stage 3), the new value is persisted to
        SQLite via a fire-and-forget asyncio task so the hot path stays sync.
        Crashes may lose the last in-flight update — acceptable given EMA
        self-heals over samples (Rule 10 §1 context preservation policy).
        """
        if role not in self._expertise:
            self._expertise[role] = {}
        prev = self._expertise[role].get(topic, 0.5)  # neutral prior
        sample = 1.0 if success else 0.0
        new_value = _EMA_ALPHA * sample + (1 - _EMA_ALPHA) * prev
        self._expertise[role][topic] = new_value

        if self._storage is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_expertise(role, topic, new_value))
            except RuntimeError:
                # No running loop (e.g. during sync test setup) — skip persist.
                log.debug("knowledge_graph.persist_skip_no_loop", role=role, topic=topic)

    async def _persist_expertise(self, role: str, topic: str, value: float) -> None:
        """SQLite save for one (role, topic) EMA. Tolerates storage errors."""
        if self._storage is None:
            return
        key = f"{_EXPERTISE_KEY_PREFIX}{role}:{topic}"
        payload: dict[str, object] = {
            "_kind": "kg_expertise",
            "role": role,
            "topic": topic,
            "ema_value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._storage.save(key, payload)
        except Exception as exc:
            log.warning("knowledge_graph.persist_error", role=role, topic=topic, detail=str(exc))

    def _get_expertise(self, role: str, topic: str) -> float:
        return self._expertise.get(role, {}).get(topic, 0.5)  # neutral default

    def _detect_topic(self, text: str) -> str:
        """Detect primary topic from text using whole-word keyword matching."""
        normalized = _normalize(text)
        best_role = "general"
        best_count = 0
        for role, pattern in _KEYWORD_PATTERNS.items():
            count = len(pattern.findall(normalized))
            if count > best_count:
                best_count = count
                best_role = role
        return best_role

    def _keyword_route(self, question: str) -> str | None:
        """Deterministic keyword-based routing (fallback path, whole-word match)."""
        normalized = _normalize(question)
        scores: dict[str, int] = {
            role: len(pattern.findall(normalized)) for role, pattern in _KEYWORD_PATTERNS.items()
        }
        best_role = max(scores, key=lambda r: scores[r])
        return best_role if scores[best_role] > 0 else None

    def _role_from_agent_id(self, agent_id: str) -> str:
        """Infer role from agent_id string (e.g. 'backend_agent' → 'backend')."""
        for role in _KEYWORD_ROUTING:
            if role in agent_id.lower():
                return role
        return "general"

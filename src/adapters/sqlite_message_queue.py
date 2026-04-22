"""SQLite-backed message queue adapter with KnowledgeGraph-based routing.

Routing priority (per 04_SYSTEM_ARCHITECTURE.md §4.5):
  1. KnowledgeGraph.find_best_responder()  — semantic + expertise_level
  2. Keyword-based fallback                — deterministic topic matching
  3. Explicit to_agent                     — direct addressing always wins
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from domain.contracts import Message, MessageStatus, MessageType
from domain.ports import StoragePort
from observability.ids import generate_message_id
from observability.logger import get_logger

if TYPE_CHECKING:
    from domain.ports import KnowledgeGraphPort

log = get_logger(__name__)

# Keyword fallback table (mirrors knowledge_graph.py for consistency)
_KEYWORD_ROUTING: dict[str, list[str]] = {
    "backend": ["api", "database", "sql", "endpoint", "schema", "model", "migration", "fastapi"],
    "frontend": ["ui", "component", "css", "react", "flutter", "widget", "style", "render"],
    "mlops": ["deploy", "docker", "dockerfile", "compose", "ci", "pipeline", "kubernetes"],
}


class SQLiteMessageQueue:
    """MessageQueuePort implementation: asyncio delivery + SQLite history.

    Accepts an optional ``knowledge_graph`` for expertise-based routing.
    When ``knowledge_graph`` is provided, ``route_question()`` uses semantic
    search + EMA expertise before falling back to keyword matching.
    """

    def __init__(
        self,
        storage: StoragePort,
        knowledge_graph: "KnowledgeGraphPort | None" = None,
    ) -> None:
        self._storage = storage
        self._knowledge_graph = knowledge_graph
        self._inboxes: dict[str, asyncio.Queue[Message]] = {}

    def _inbox(self, agent_id: str) -> asyncio.Queue[Message]:
        if agent_id not in self._inboxes:
            self._inboxes[agent_id] = asyncio.Queue()
        return self._inboxes[agent_id]

    async def send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: MessageType = MessageType.NOTIFICATION,
        context: dict[str, object] | None = None,
    ) -> str:
        msg = Message(
            id=generate_message_id(),
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            type=message_type,
            context=context or {},
            status=MessageStatus.PENDING,
        )
        await self._storage.save(msg.id, msg.model_dump(mode="json"))
        await self._inbox(to_agent).put(msg)
        log.info("queue.msg.sent", msg_id=msg.id, from_=from_agent, to=to_agent, type=message_type)
        return msg.id

    async def receive(
        self,
        agent_id: str,
        timeout_sec: float = 0.0,
    ) -> Message | None:
        q = self._inbox(agent_id)
        try:
            if timeout_sec <= 0:
                return q.get_nowait()
            return await asyncio.wait_for(q.get(), timeout=timeout_sec)
        except (asyncio.QueueEmpty, asyncio.TimeoutError):
            return None

    async def ask(
        self,
        from_agent: str,
        to_agent: str,
        question: str,
        context: dict[str, object] | None = None,
        timeout_sec: float = 30.0,
    ) -> str:
        await self.send(
            from_agent=from_agent,
            to_agent=to_agent,
            content=question,
            message_type=MessageType.QUESTION,
            context=context,
        )
        try:
            msg = await asyncio.wait_for(self._inbox(from_agent).get(), timeout=timeout_sec)
            return msg.content
        except asyncio.TimeoutError:
            log.warning("queue.qa.timeout", from_agent=from_agent, to_agent=to_agent)
            return ""

    async def route_question(
        self,
        from_agent: str,
        question: str,
        context: dict[str, object] | None = None,
        timeout_sec: float = 30.0,
    ) -> str:
        """Route a question to the best-suited agent using KnowledgeGraph.

        Routing order:
          1. KnowledgeGraph.find_best_responder() (semantic + expertise_level)
          2. Keyword-based fallback
          3. Default: "cto" (always available as final fallback)
        """
        to_agent = await self._find_responder(question, context)
        log.info(
            "queue.route_question",
            from_agent=from_agent,
            routed_to=to_agent,
            question_len=len(question),
        )
        return await self.ask(
            from_agent=from_agent,
            to_agent=to_agent,
            question=question,
            context=context,
            timeout_sec=timeout_sec,
        )

    async def _find_responder(
        self,
        question: str,
        context: dict[str, object] | None,
    ) -> str:
        """Determine best responder: KnowledgeGraph → keyword → cto fallback."""
        # 1. KnowledgeGraph-based routing (expertise_level priority)
        if self._knowledge_graph is not None:
            try:
                role = await self._knowledge_graph.find_best_responder(question, context)
                if role is not None:
                    return role
            except Exception as exc:
                log.warning("queue.routing.kg_error", detail=str(exc))

        # 2. Keyword fallback
        lower = question.lower()
        best_role: str | None = None
        best_score = 0
        for role, keywords in _KEYWORD_ROUTING.items():
            score = sum(1 for kw in keywords if kw in lower)
            if score > best_score:
                best_score = score
                best_role = role

        if best_role and best_score > 0:
            return best_role

        # 3. CTO as final fallback
        return "cto"

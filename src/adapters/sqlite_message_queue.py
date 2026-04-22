"""SQLite-backed message queue adapter."""

from __future__ import annotations

import asyncio

from domain.contracts import Message, MessageStatus, MessageType
from domain.ports import StoragePort
from observability.ids import generate_message_id
from observability.logger import get_logger

log = get_logger(__name__)


class SQLiteMessageQueue:
    """MessageQueuePort implementation: asyncio delivery + SQLite history."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage
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

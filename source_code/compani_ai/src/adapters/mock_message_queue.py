"""Mock message queue implementation for tests."""

from __future__ import annotations

import asyncio

from domain.contracts import Message, MessageStatus, MessageType
from observability.ids import generate_message_id


class MockMessageQueue:
    """In-memory queue with deterministic ask timeout behavior."""

    def __init__(self) -> None:
        self._inboxes: dict[str, asyncio.Queue[Message]] = {}

    def _get_inbox(self, agent_id: str) -> asyncio.Queue[Message]:
        if agent_id not in self._inboxes:
            self._inboxes[agent_id] = asyncio.Queue()
        return self._inboxes[agent_id]

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
        # Tests should not wait for full timeout duration.
        await asyncio.sleep(min(timeout_sec, 0.001))
        return ""

    async def send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: MessageType = MessageType.NOTIFICATION,
        context: dict[str, object] | None = None,
    ) -> str:
        message = Message(
            id=generate_message_id(),
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            type=message_type,
            context=context or {},
            status=MessageStatus.PENDING,
        )
        await self._get_inbox(to_agent).put(message)
        return message.id

    async def receive(
        self,
        agent_id: str,
        timeout_sec: float = 0.0,
    ) -> Message | None:
        inbox = self._get_inbox(agent_id)
        try:
            if timeout_sec <= 0:
                return inbox.get_nowait()
            return await asyncio.wait_for(inbox.get(), timeout=timeout_sec)
        except (asyncio.QueueEmpty, asyncio.TimeoutError):
            return None

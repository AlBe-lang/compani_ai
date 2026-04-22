"""In-process event bus adapter."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from domain.ports import EventHandler, EventPayload
from observability.logger import get_logger

log = get_logger(__name__)


class InProcessEventBus:
    """EventBusPort implementation using asyncio in-process delivery."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, payload: EventPayload) -> None:
        log.debug("event.published", event_type=event_type)
        for handler in list(self._handlers.get(event_type, [])):
            try:
                result = handler(event_type, payload)
                if asyncio.iscoroutine(result):
                    await result
                log.debug("event.handled", event_type=event_type, handler=handler.__name__)
            except Exception:
                log.exception("event.handler_error", event_type=event_type)

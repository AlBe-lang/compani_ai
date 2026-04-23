from __future__ import annotations

from adapters.event_bus import InProcessEventBus


async def test_subscribe_and_publish_calls_handler() -> None:
    bus = InProcessEventBus()
    received: list[tuple[str, object]] = []

    def handler(event_type: str, payload: object) -> None:
        received.append((event_type, payload))

    bus.subscribe("item.updated", handler)
    await bus.publish("item.updated", {"id": "1"})

    assert len(received) == 1
    assert received[0][0] == "item.updated"
    assert received[0][1] == {"id": "1"}


async def test_multiple_subscribers_all_called() -> None:
    bus = InProcessEventBus()
    calls: list[str] = []

    bus.subscribe("ev", lambda t, p: calls.append("h1"))
    bus.subscribe("ev", lambda t, p: calls.append("h2"))
    await bus.publish("ev", {})

    assert "h1" in calls
    assert "h2" in calls


async def test_publish_unknown_event_no_error() -> None:
    bus = InProcessEventBus()
    await bus.publish("unknown.event", {"x": 1})  # must not raise


async def test_async_handler_supported() -> None:
    bus = InProcessEventBus()
    received: list[str] = []

    async def async_handler(event_type: str, payload: object) -> None:
        received.append(event_type)

    bus.subscribe("async.ev", async_handler)
    await bus.publish("async.ev", {})

    assert received == ["async.ev"]


async def test_payload_passed_to_handler() -> None:
    bus = InProcessEventBus()
    payloads: list[object] = []

    bus.subscribe("ev", lambda t, p: payloads.append(p))
    await bus.publish("ev", {"key": "value", "count": 42})

    assert payloads[0] == {"key": "value", "count": 42}

"""Mock-LLM pipeline benchmarks — Part 8 Stage 1 (Q1 mock half).

ROLE: **regression detection** — relative comparison between commits using a
controlled, deterministic mock LLM. Absolute numbers are MEANINGLESS here
because the mock returns instantly; treat this suite as a guardrail against
code-path regression (e.g. a new inefficient loop, unintended serial I/O),
not as a proxy for real user-facing latency.

For absolute latency measurements that reflect real user experience, run
``make bench-real`` (see ``scripts/benchmark_real.py``). Do **not** compare
numbers between these two suites.

Marker ``benchmark`` is excluded from default ``make test`` via
``-m "not slow and not benchmark"``. Run explicitly with ``make bench-mock``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.event_bus import InProcessEventBus
from adapters.sqlite_message_queue import SQLiteMessageQueue
from adapters.sqlite_storage import SQLiteStorage
from application.concurrency import LLMConcurrencyLimiter

pytestmark = pytest.mark.benchmark


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _mock_llm(response: str = '{"result": "ok"}') -> MagicMock:
    """Mock LLM that returns instantly. For relative timing comparison only."""
    mock = MagicMock()

    async def _gen(*args: Any, **kwargs: Any) -> str:
        # Yield control so async scheduling overhead is measurable
        await asyncio.sleep(0)
        return response

    mock.generate = AsyncMock(side_effect=_gen)
    return mock


# ------------------------------------------------------------------
# Benchmarks
# ------------------------------------------------------------------


async def test_bench_concurrency_limiter_noop_overhead() -> None:
    """Entering/exiting the LLMConcurrencyLimiter should add negligible
    overhead per call (target: < 1ms). Regression check — if someone adds
    heavy state or locking, this catches it.

    MODE: mock (relative regression only).
    """
    limiter = LLMConcurrencyLimiter(cto=1, slm=1, mlops=1, total=2)
    iterations = 1000
    t0 = time.perf_counter()
    for _ in range(iterations):
        async with limiter.limit("backend"):
            pass
    elapsed = time.perf_counter() - t0
    per_call_ms = (elapsed / iterations) * 1000
    print(f"\n[bench mock] limiter overhead: {per_call_ms:.3f} ms/call ({iterations} iters)")
    # Regression guard: fail if > 2ms per call (was ~0.1ms on dev machine).
    assert per_call_ms < 2.0, f"Limiter overhead regression: {per_call_ms:.3f} ms/call"


async def test_bench_concurrency_limiter_parallel_throughput() -> None:
    """Parallel execution through limiter vs serial baseline.

    With total=2, slm=1 and two backend tasks, execution should be serial
    (one slot). With total=2, slm=2, execution should be parallel (~2x).
    MODE: mock (relative throughput sanity only).
    """

    async def _work() -> None:
        await asyncio.sleep(0.01)  # simulate 10ms LLM call

    # Serial case
    limiter_serial = LLMConcurrencyLimiter(cto=1, slm=1, mlops=1, total=2)

    async def _run(limiter: LLMConcurrencyLimiter) -> float:
        t0 = time.perf_counter()

        async def _one() -> None:
            async with limiter.limit("backend"):
                await _work()

        await asyncio.gather(*[_one() for _ in range(4)])
        return time.perf_counter() - t0

    serial_time = await _run(limiter_serial)

    limiter_parallel = LLMConcurrencyLimiter(cto=1, slm=2, mlops=1, total=3)
    parallel_time = await _run(limiter_parallel)

    print(
        f"\n[bench mock] serial (slm=1): {serial_time * 1000:.1f}ms, "
        f"parallel (slm=2): {parallel_time * 1000:.1f}ms"
    )
    # Parallel should be roughly half — loose tolerance for CI noise
    assert parallel_time < serial_time * 0.8, (
        f"Parallel slot did not improve throughput: serial={serial_time:.3f}s "
        f"parallel={parallel_time:.3f}s"
    )


async def test_bench_message_queue_roundtrip() -> None:
    """SQLite MessageQueue send+receive roundtrip latency.

    MODE: mock (DB-only, no LLM). Uses :memory: SQLite. Absolute numbers
    depend on disk vs memory; we assert < 5ms/roundtrip as regression guard.
    """
    storage = SQLiteStorage(":memory:")
    await storage.init()
    queue = SQLiteMessageQueue(storage=storage)
    iterations = 100
    t0 = time.perf_counter()
    for i in range(iterations):
        await queue.send(
            from_agent="bench_sender",
            to_agent="bench_receiver",
            content=f"msg_{i}",
        )
        await queue.receive("bench_receiver")
    elapsed = time.perf_counter() - t0
    per_msg_ms = (elapsed / iterations) * 1000
    print(f"\n[bench mock] MQ roundtrip: {per_msg_ms:.3f} ms/msg ({iterations} iters)")
    assert per_msg_ms < 5.0, f"MQ regression: {per_msg_ms:.3f} ms/msg"
    await storage.close()


async def test_bench_event_bus_publish_fanout() -> None:
    """EventBus publish to N subscribers latency.

    MODE: mock (in-memory only). Baseline: ~microseconds per handler.
    """
    bus = InProcessEventBus()
    received = 0

    def handler(event_type: str, payload: object) -> None:
        nonlocal received
        received += 1

    for _ in range(10):
        bus.subscribe("bench.event", handler)

    iterations = 500
    t0 = time.perf_counter()
    for i in range(iterations):
        await bus.publish("bench.event", {"i": i})
    elapsed = time.perf_counter() - t0
    per_publish_ms = (elapsed / iterations) * 1000
    print(
        f"\n[bench mock] EventBus fanout (10 subs): {per_publish_ms:.3f} ms/publish "
        f"({iterations} iters)"
    )
    assert received == iterations * 10
    assert per_publish_ms < 3.0

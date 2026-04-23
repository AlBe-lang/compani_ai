"""Unit tests for LLMConcurrencyLimiter — Part 8 Stage 1.

Covers:
  1. Defaults (Mac Mini safe): cto=1, slm=1, mlops=1, total=2
  2. Per-role serialization (slm=1 → 2 backend tasks serial)
  3. Total cap enforcement (total=2 → 3rd concurrent blocked)
  4. Different roles share total but own per-role
  5. Unknown role bypasses limiting (defensive)
  6. Invalid constructor args rejected
"""

from __future__ import annotations

import asyncio
import time

import pytest

from application.concurrency import LLMConcurrencyLimiter


async def test_defaults_mac_mini_safe() -> None:
    lim = LLMConcurrencyLimiter()
    assert lim.config == {"cto": 1, "slm": 1, "mlops": 1, "total": 2}


async def test_invalid_args_rejected() -> None:
    with pytest.raises(ValueError):
        LLMConcurrencyLimiter(cto=0)
    with pytest.raises(ValueError):
        LLMConcurrencyLimiter(total=0)


async def test_per_role_serialization_slm_one() -> None:
    """With slm=1 two backend tasks must run serially."""
    lim = LLMConcurrencyLimiter(slm=1, total=2)
    order: list[str] = []

    async def _task(name: str) -> None:
        async with lim.limit("backend"):
            order.append(f"start-{name}")
            await asyncio.sleep(0.02)
            order.append(f"end-{name}")

    await asyncio.gather(_task("A"), _task("B"))
    # Serial pattern: startA endA startB endB  OR  startB endB startA endA
    assert order[1] in ("end-A", "end-B")
    assert order[1].startswith("end-")  # second slot only starts after first ends


async def test_total_cap_enforced() -> None:
    """total=2 with cto=2+slm=2: 3rd concurrent slot blocks on total."""
    lim = LLMConcurrencyLimiter(cto=2, slm=2, mlops=2, total=2)

    active_count = 0
    peak = 0
    lock = asyncio.Lock()

    async def _task(role: str) -> None:
        nonlocal active_count, peak
        async with lim.limit(role):
            async with lock:
                active_count += 1
                peak = max(peak, active_count)
            await asyncio.sleep(0.02)
            async with lock:
                active_count -= 1

    # 5 concurrent: total=2 enforces max 2 simultaneously
    await asyncio.gather(
        _task("backend"),
        _task("frontend"),
        _task("mlops"),
        _task("backend"),
        _task("cto"),
    )
    assert peak == 2, f"total cap violated: peak={peak}"


async def test_different_roles_share_total_not_per_role() -> None:
    """cto=1 and slm=1 separate semaphores — both can be held simultaneously
    if total allows. With total=2 one cto + one slm = 2 concurrent OK."""
    lim = LLMConcurrencyLimiter(cto=1, slm=1, mlops=1, total=2)

    async def _inside_cto() -> None:
        async with lim.limit("cto"):
            await asyncio.sleep(0.05)

    async def _inside_slm() -> None:
        async with lim.limit("backend"):
            await asyncio.sleep(0.05)

    t0 = time.perf_counter()
    await asyncio.gather(_inside_cto(), _inside_slm())
    elapsed = time.perf_counter() - t0
    # Parallel would be ~0.05s; serial would be ~0.10s
    assert elapsed < 0.09, f"cto+slm did not run in parallel: {elapsed:.3f}s"


async def test_unknown_role_bypasses() -> None:
    """Unknown role yields without limiting (defensive behavior + warn log)."""
    lim = LLMConcurrencyLimiter(cto=1, slm=1, mlops=1, total=1)

    async def _task(role: str) -> None:
        async with lim.limit(role):
            await asyncio.sleep(0.01)

    # Even with total=1, unknown role should not be gated
    t0 = time.perf_counter()
    await asyncio.gather(
        _task("unknown_role_foo"),
        _task("unknown_role_bar"),
    )
    elapsed = time.perf_counter() - t0
    # Both should run in parallel since unknown roles bypass
    assert elapsed < 0.03

"""LLM concurrency control — Part 8 Stage 1.

Wraps ``asyncio.Semaphore`` per agent role + a global total limit so Mac Mini
M4 16GB (주 환경) 에서 동시 모델 메모리 합계가 swap 임계값을 넘지 않는다.
참조: 04_INFRASTRUCTURE_RULES.md I-04 ("동시에 2개 이상 큰 모델 금지"),
      04_SYSTEM_ARCHITECTURE.md §7.3 전략 1 (모델 순차 로드).

기본값 근거 (Mac Mini 16GB, llama3.1:8b + gemma4:e4b 기준):
  CTO 8B        ≈ 4.7GB
  SLM gemma4:e4b ≈ 9.6GB
  합계           ≈ 14.3GB  (OS + Python 1.5GB 포함 15.8GB, swap 직전)
  → 동시 2개 모델까지만 허용 (CTO + 1 SLM). 2 SLM 병렬은 swap 확정.

32GB+ 데스크탑 환경에선 SystemConfig 필드를 상향 조정해 2 SLM 병렬 가능.
CEO 대시보드(Part 8 Stage 2)에서 runtime 토글로 노출 예정.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from observability.logger import get_logger

log = get_logger(__name__)


class LLMConcurrencyLimiter:
    """Per-role semaphore + global total semaphore.

    Usage::

        limiter = LLMConcurrencyLimiter(cto=1, slm=1, mlops=1, total=2)
        async with limiter.limit("backend"):
            await agent.execute_task(task)

    ``role`` is resolved to the backing semaphore via an internal map:
      - "cto"                 → cto semaphore
      - "backend" | "frontend" → slm semaphore (shared)
      - "mlops"               → mlops semaphore
      - unknown role          → no limiting (caller proceeds uncontrolled)
    """

    def __init__(
        self,
        cto: int = 1,
        slm: int = 1,
        mlops: int = 1,
        total: int = 2,
    ) -> None:
        if cto < 1 or slm < 1 or mlops < 1 or total < 1:
            raise ValueError("concurrency limits must be >= 1")
        self._cto = asyncio.Semaphore(cto)
        self._slm = asyncio.Semaphore(slm)
        self._mlops = asyncio.Semaphore(mlops)
        self._total = asyncio.Semaphore(total)
        self._config = {"cto": cto, "slm": slm, "mlops": mlops, "total": total}

    def update_limits(
        self,
        *,
        cto: int | None = None,
        slm: int | None = None,
        mlops: int | None = None,
        total: int | None = None,
    ) -> None:
        """Part 8 Stage 2 (Q5 hot-reload): swap semaphores so the next
        ``limit()`` call honours the new caps.

        In-flight ``async with limit(...)`` holders keep using the OLD
        semaphore they entered — no risk of under-release. Waiters queued
        on the old semaphore drain naturally as holders exit. This is
        the same pattern used by asyncio's own connection pools.
        """
        if cto is not None:
            if cto < 1:
                raise ValueError("cto limit must be >= 1")
            self._cto = asyncio.Semaphore(cto)
            self._config["cto"] = cto
        if slm is not None:
            if slm < 1:
                raise ValueError("slm limit must be >= 1")
            self._slm = asyncio.Semaphore(slm)
            self._config["slm"] = slm
        if mlops is not None:
            if mlops < 1:
                raise ValueError("mlops limit must be >= 1")
            self._mlops = asyncio.Semaphore(mlops)
            self._config["mlops"] = mlops
        if total is not None:
            if total < 1:
                raise ValueError("total limit must be >= 1")
            self._total = asyncio.Semaphore(total)
            self._config["total"] = total
        log.info("llm_concurrency.limits_updated", **self._config)

    @asynccontextmanager
    async def limit(self, role: str) -> AsyncIterator[None]:
        """Acquire (total → per-role) semaphore pair for the given role.

        Unknown role yields without limiting — defensive to avoid blocking
        downstream if an unexpected role string arrives.
        """
        sem_map = {
            "cto": self._cto,
            "backend": self._slm,
            "frontend": self._slm,
            "mlops": self._mlops,
        }
        per_role = sem_map.get(role)
        if per_role is None:
            log.warning("llm_concurrency.unknown_role", role=role)
            yield
            return
        async with self._total:
            async with per_role:
                yield

    @property
    def config(self) -> dict[str, int]:
        """Return the configured limits (for observability / dashboards)."""
        return dict(self._config)

"""In-memory metrics collector with optional SQLite flush."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.ports import StoragePort
from observability.logger import get_logger
from observability.tracing import get_trace_id

log = get_logger(__name__)


@dataclass
class TaskMetric:
    run_id: str
    task_id: str
    agent_id: str
    success: bool
    duration_sec: float
    retries: int = 0
    trace_id: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class FallbackMetric:
    """Records when a component degraded to a fallback path (Part 7 Stage 1).

    Primary use: emergency meeting's CTO-unavailable → DNA-weighted fallback.
    Persisted alongside task metrics so operational dashboards can surface
    CTO availability issues.
    """

    run_id: str
    component: str  # e.g. "emergency_meeting"
    reason: str  # e.g. "cto_max_retries"
    trace_id: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RunSummary:
    run_id: str
    total_tasks: int
    success_count: int
    fail_count: int
    avg_duration_sec: float
    total_retries: int
    fallback_count: int = 0
    # Part 8 Stage 2 (R-10A): peak process memory usage in GB across this run.
    # Updated opportunistically via MetricsCollector.sample_memory(); remains 0.0
    # if psutil is unavailable or sampling never invoked.
    memory_peak_gb: float = 0.0


try:
    import psutil  # type: ignore[import-untyped]

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PSUTIL_AVAILABLE = False


class MetricsCollector:
    """Accumulate per-task metrics in memory; flush to SQLite on demand."""

    def __init__(self) -> None:
        self._metrics: list[TaskMetric] = []
        self._fallbacks: list[FallbackMetric] = []
        # Part 8 Stage 2 (R-10A): per-run peak memory sample (GB).
        self._memory_peak_by_run: dict[str, float] = {}

    def record_task(
        self,
        run_id: str,
        task_id: str,
        agent_id: str,
        *,
        success: bool,
        duration_sec: float,
        retries: int = 0,
    ) -> None:
        metric = TaskMetric(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            success=success,
            duration_sec=duration_sec,
            retries=retries,
            trace_id=get_trace_id(),
        )
        self._metrics.append(metric)
        log.info(
            "metrics.task_recorded",
            run_id=run_id,
            task_id=task_id,
            success=success,
            duration_sec=round(duration_sec, 3),
        )

    def sample_memory(self, run_id: str) -> float:
        """Part 8 Stage 2 (R-10A) — sample current process RSS in GB.

        Updates per-run peak. Returns the peak-so-far for this run. No-op
        (returns 0.0) when psutil isn't installed.
        """
        if not _PSUTIL_AVAILABLE:
            return 0.0
        try:
            rss_bytes = psutil.Process().memory_info().rss
        except Exception as exc:  # pragma: no cover
            log.warning("metrics.memory_sample_error", detail=str(exc))
            return 0.0
        gb = rss_bytes / (1024**3)
        prev = self._memory_peak_by_run.get(run_id, 0.0)
        if gb > prev:
            self._memory_peak_by_run[run_id] = gb
        return self._memory_peak_by_run[run_id]

    def record_fallback(self, run_id: str, component: str, reason: str) -> None:
        """Part 7 Stage 1 — record a degraded-path activation event."""
        metric = FallbackMetric(
            run_id=run_id,
            component=component,
            reason=reason,
            trace_id=get_trace_id(),
        )
        self._fallbacks.append(metric)
        log.warning(
            "metrics.fallback_recorded",
            run_id=run_id,
            component=component,
            reason=reason,
        )

    def get_run_summary(self, run_id: str) -> RunSummary:
        run_metrics = [m for m in self._metrics if m.run_id == run_id]
        fallback_count = sum(1 for m in self._fallbacks if m.run_id == run_id)
        if not run_metrics:
            return RunSummary(
                run_id=run_id,
                total_tasks=0,
                success_count=0,
                fail_count=0,
                avg_duration_sec=0.0,
                total_retries=0,
                fallback_count=fallback_count,
            )
        success_count = sum(1 for m in run_metrics if m.success)
        avg_duration = sum(m.duration_sec for m in run_metrics) / len(run_metrics)
        return RunSummary(
            run_id=run_id,
            total_tasks=len(run_metrics),
            success_count=success_count,
            fail_count=len(run_metrics) - success_count,
            avg_duration_sec=round(avg_duration, 3),
            total_retries=sum(m.retries for m in run_metrics),
            fallback_count=fallback_count,
            memory_peak_gb=round(self._memory_peak_by_run.get(run_id, 0.0), 3),
        )

    async def flush(self, storage: StoragePort) -> None:
        """Persist unflushed metrics to storage (upsert — duplicate flush is safe)."""
        flushed = 0
        for metric in self._metrics:
            key = f"metric_{metric.run_id}_{metric.task_id}"
            # save() uses INSERT OR REPLACE — idempotent on duplicate keys
            await storage.save(
                key,
                {
                    "run_id": metric.run_id,
                    "task_id": metric.task_id,
                    "agent_id": metric.agent_id,
                    "success": metric.success,
                    "duration_sec": metric.duration_sec,
                    "retries": metric.retries,
                    "trace_id": metric.trace_id,
                    "recorded_at": metric.recorded_at,
                },
            )
            flushed += 1
        for i, fb in enumerate(self._fallbacks):
            key = f"fallback_{fb.run_id}_{fb.component}_{i}"
            await storage.save(
                key,
                {
                    "run_id": fb.run_id,
                    "component": fb.component,
                    "reason": fb.reason,
                    "trace_id": fb.trace_id,
                    "recorded_at": fb.recorded_at,
                },
            )
        log.info("metrics.flushed", count=flushed, fallback_count=len(self._fallbacks))
        # Clear after successful flush so duplicate calls don't re-persist
        self._metrics.clear()
        self._fallbacks.clear()

"""Initial WebSocket snapshot builder — Part 8 Stage 2 (Q2 보강).

When a dashboard client first opens the WebSocket, the server sends a
SnapshotPayload *before* any event push. This solves the "blank screen on
first connect" UX issue identified during Q2 analysis.

Snapshot content (all optional — if a dependency isn't available the field
is omitted rather than filled with placeholder zeros):
  * ``run``     — current run id + wall-clock start
  * ``config``  — serialised SystemConfig with reload metadata
  * ``dna``     — all agent DNA loaded from DNAManager cache
  * ``metrics`` — current RunSummary
  * ``workitems`` — open + recently completed WorkItems

The payload is produced fresh on each connection; clients can rely on it
reflecting server state at connect time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from observability.logger import get_logger

from .config_mutation import serialise_config

if TYPE_CHECKING:
    from application.agent_factory import SystemConfig

    from .app import DashboardDeps

log = get_logger(__name__)


async def build_snapshot(deps: "DashboardDeps") -> dict[str, Any]:
    """Assemble a self-contained snapshot of server state for a new WS client."""
    snapshot: dict[str, Any] = {
        "type": "snapshot",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": deps.config.run_id,
    }
    snapshot["config"] = serialise_config(deps.config)
    snapshot["dna"] = await _dna_snapshot(deps)
    snapshot["metrics"] = _metrics_snapshot(deps)
    snapshot["workitems"] = await _workitems_snapshot(deps)
    return snapshot


async def _dna_snapshot(deps: "DashboardDeps") -> list[dict[str, Any]]:
    if deps.dna_manager is None:
        return []
    # DNAManager caches per agent id — surface whatever is already loaded.
    entries: list[dict[str, Any]] = []
    try:
        cache = getattr(deps.dna_manager, "_cache", {})
        for agent_id, dna in cache.items():
            entries.append(
                {
                    "agent_id": agent_id,
                    "role": dna.role,
                    "success_rate": dna.success_rate,
                    "avg_duration": dna.avg_duration,
                    "total_tasks": dna.total_tasks,
                    "genes": dict(dna.genes),
                    "meeting_participation_count": dna.meeting_participation_count,
                    "review_count": dna.review_count,
                }
            )
    except Exception as exc:
        log.warning("snapshot.dna_error", detail=str(exc))
    return entries


def _metrics_snapshot(deps: "DashboardDeps") -> dict[str, Any] | None:
    if deps.metrics is None:
        return None
    summary = deps.metrics.get_run_summary(deps.config.run_id)
    return {
        "run_id": summary.run_id,
        "total_tasks": summary.total_tasks,
        "success_count": summary.success_count,
        "fail_count": summary.fail_count,
        "avg_duration_sec": summary.avg_duration_sec,
        "total_retries": summary.total_retries,
        "fallback_count": summary.fallback_count,
        "memory_peak_gb": summary.memory_peak_gb,
    }


async def _workitems_snapshot(deps: "DashboardDeps") -> list[dict[str, Any]]:
    if deps.workspace is None:
        return []
    # SharedWorkspace exposes an in-memory cache; reach through it to avoid
    # an additional storage query. If the attribute isn't present (MockWorkSpace
    # or future replacement), fall back to an empty list.
    cache: dict[str, Any] = getattr(deps.workspace, "_cache", {})
    items: list[dict[str, Any]] = []
    for work_item_id, item in cache.items():
        items.append(
            {
                "id": work_item_id,
                "task_id": item.task_id,
                "agent_id": item.agent_id,
                "status": item.status.value,
                "rework_count": item.rework_count,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
        )
    return items


def environment_snapshot(config: "SystemConfig") -> dict[str, Any]:
    """Part 8 Stage 2 (R-10F): surface total system memory so the UI can
    flag EmbeddingPreset.E5_BEST as unavailable on Mac Mini 16GB.

    Returns ``{"total_memory_gb": float | None, "can_use_e5_large": bool}``.
    """
    try:
        import psutil  # type: ignore[import-untyped]

        total_gb = psutil.virtual_memory().total / (1024**3)
    except Exception as exc:  # pragma: no cover — psutil missing
        log.warning("snapshot.env_error", detail=str(exc))
        total_gb = None
    # e5-large is 2.24 GB on disk + runtime overhead; require 24 GB total as a
    # conservative fit threshold on macOS/Windows home machines.
    can_use_e5 = bool(total_gb and total_gb >= 24.0)
    return {
        "total_memory_gb": round(total_gb, 2) if total_gb is not None else None,
        "can_use_e5_large": can_use_e5,
        "current_embedding_preset": config.embedding_preset.value,
    }

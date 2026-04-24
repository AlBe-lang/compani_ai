"""E2E harness — Part 8 Stage 3.

Provides:
  * Preflight diagnostic (Ollama reachable, required models present, free
    disk/RAM above thresholds)
  * Result classification (Green / Yellow / Red) against PROJECT_PLAN §10.1
    MVP KPI thresholds
  * A JSON report writer per project under ``benchmarks/reports/e2e/<name>/``

The harness intentionally does NOT own fixtures for SharedWorkspace / Qdrant
/ Redis etc. — individual ``test_*_app.py`` files wire those up so each
project can isolate its SQLite file and output dir under ``tmp_path``.

All real LLM calls live behind ``@pytest.mark.slow`` and skip gracefully if
Ollama is unavailable. The ``preflight()`` helper is what decides whether a
test body should run; callers should call it first and ``pytest.skip`` on
failure with the returned human-readable reason.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import psutil  # type: ignore[import-untyped]

from observability.logger import get_logger

if TYPE_CHECKING:
    from main import ProjectResult

    from observability.metrics import MetricsCollector

log = get_logger(__name__)

# PROJECT_PLAN §10.1 — MVP KPI thresholds. Secondary signals recorded for
# every run regardless of pass/fail; Primary DoD (pipeline completes +
# produces files) is evaluated separately in ``classify_result``.
KPI_THRESHOLDS = {
    "completion_pct": 60.0,  # 생성된 코드가 요구사항의 60%+ 반영
    "task_success_rate_pct": 80.0,  # 완료 WorkItem / 전체 WorkItem
    "collab_success_rate_pct": 70.0,  # 성공한 Q&A / 전체 Q&A 요청
    "stability_pct": 90.0,  # 에러 없이 완료된 실행 / 전체
    "executable_code_pct": 50.0,  # 실행 가능한 코드 비율
    "duration_budget_sec": 30 * 60,  # 프로젝트당 30분 이내
}

DEFAULT_OLLAMA_URL = "http://localhost:11434"
REQUIRED_MODELS = ("qwen3:8b", "gemma4:e4b", "llama3.2:3b")

# Free-resource thresholds — below these the preflight warns; tests still
# run so the user can override with force=True.
MIN_FREE_DISK_GB = 5.0
MIN_FREE_RAM_GB = 3.0


@dataclass(frozen=True)
class PreflightReport:
    """Outcome of the E2E environment check."""

    ollama_ok: bool
    installed_models: tuple[str, ...]
    missing_models: tuple[str, ...]
    free_disk_gb: float
    free_ram_gb: float
    warnings: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.ollama_ok and not self.missing_models

    def skip_reason(self) -> str | None:
        if not self.ollama_ok:
            return "Ollama unreachable — start with `ollama serve`"
        if self.missing_models:
            missing = ", ".join(self.missing_models)
            return f"Missing models: {missing} — run `ollama pull <model>`"
        return None


@dataclass
class E2EResult:
    """Classified outcome of a single project E2E run."""

    project: str
    classification: str  # "green" | "yellow" | "red"
    primary_passed: bool
    kpi: dict[str, float] = field(default_factory=dict)
    kpi_targets_met: int = 0
    duration_sec: float = 0.0
    files_generated: int = 0
    notes: list[str] = field(default_factory=list)


async def preflight(
    base_url: str = DEFAULT_OLLAMA_URL,
    required_models: tuple[str, ...] = REQUIRED_MODELS,
) -> PreflightReport:
    """Check Ollama reachability, model presence, and local resources.

    Returns the report even on partial failure so the caller can log it
    (and ``pytest.skip`` with ``report.skip_reason()`` when not ready).
    """
    warnings: list[str] = []

    ollama_ok = False
    installed: tuple[str, ...] = ()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{base_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    installed = tuple(m.get("name", "") for m in data.get("models", []))
                    ollama_ok = True
    except Exception as exc:  # noqa: BLE001 — preflight must not raise
        warnings.append(f"Ollama health check error: {exc!r}")

    missing = tuple(m for m in required_models if m not in installed)

    free_disk_gb = shutil.disk_usage(Path.cwd()).free / (1024**3)
    if free_disk_gb < MIN_FREE_DISK_GB:
        warnings.append(f"Free disk {free_disk_gb:.1f}GB < {MIN_FREE_DISK_GB}GB threshold")

    vm = psutil.virtual_memory()
    free_ram_gb = vm.available / (1024**3)
    if free_ram_gb < MIN_FREE_RAM_GB:
        warnings.append(f"Available RAM {free_ram_gb:.1f}GB < {MIN_FREE_RAM_GB}GB threshold")

    return PreflightReport(
        ollama_ok=ollama_ok,
        installed_models=installed,
        missing_models=missing,
        free_disk_gb=free_disk_gb,
        free_ram_gb=free_ram_gb,
        warnings=tuple(warnings),
    )


def classify_result(
    project: str,
    project_result: "ProjectResult",
    metrics: "MetricsCollector",
    collab_success: int = 0,
    collab_total: int = 0,
) -> E2EResult:
    """Apply Primary DoD + Secondary KPI rules to a completed run.

    Primary DoD (Q2(B)): pipeline ran end-to-end AND produced files.
    Secondary KPI (Q2(A)): six §10.1 indicators; count how many meet target.
    Classification:
      red    = Primary failed (pipeline aborted or 0 files)
      yellow = Primary passed, fewer than 3 KPI targets met
      green  = Primary passed and at least 3 KPI targets met
    """
    summary = metrics.get_run_summary(project_result.output_dir.name)

    task_success_rate = (
        100.0 * summary.success_count / summary.total_tasks if summary.total_tasks else 0.0
    )
    collab_success_rate = 100.0 * collab_success / collab_total if collab_total else 100.0
    stability = 100.0 if project_result.success else task_success_rate
    completion_pct = (
        100.0 * project_result.completed_tasks / project_result.total_tasks
        if project_result.total_tasks
        else 0.0
    )
    # Executable-code ratio is not auto-measurable without running generated
    # code; harness records a placeholder NaN-equivalent (-1.0) that the
    # journal author fills in after manual verification.
    kpi = {
        "completion_pct": completion_pct,
        "task_success_rate_pct": task_success_rate,
        "collab_success_rate_pct": collab_success_rate,
        "stability_pct": stability,
        "executable_code_pct": -1.0,  # manual post-run fill
        "duration_sec": project_result.duration_seconds,
    }

    primary_passed = project_result.success and len(project_result.files_generated) > 0

    targets_met = 0
    if kpi["completion_pct"] >= KPI_THRESHOLDS["completion_pct"]:
        targets_met += 1
    if kpi["task_success_rate_pct"] >= KPI_THRESHOLDS["task_success_rate_pct"]:
        targets_met += 1
    if kpi["collab_success_rate_pct"] >= KPI_THRESHOLDS["collab_success_rate_pct"]:
        targets_met += 1
    if kpi["stability_pct"] >= KPI_THRESHOLDS["stability_pct"]:
        targets_met += 1
    if kpi["duration_sec"] <= KPI_THRESHOLDS["duration_budget_sec"]:
        targets_met += 1
    # executable_code_pct skipped — manual

    if not primary_passed:
        classification = "red"
    elif targets_met >= 3:
        classification = "green"
    else:
        classification = "yellow"

    return E2EResult(
        project=project,
        classification=classification,
        primary_passed=primary_passed,
        kpi=kpi,
        kpi_targets_met=targets_met,
        duration_sec=project_result.duration_seconds,
        files_generated=len(project_result.files_generated),
    )


def write_report(result: E2EResult, reports_root: Path) -> Path:
    """Write a JSON report under ``reports_root/<project>/run-<ts>.json``."""
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = reports_root / result.project
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"run-{ts}.json"
    out_path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    log.info(
        "e2e.report.written",
        project=result.project,
        classification=result.classification,
        path=str(out_path),
    )
    return out_path


def format_preflight(report: PreflightReport) -> str:
    """Human-readable preflight summary for CLI banners."""
    lines = [
        "=== E2E Pre-flight Check ===",
        f"  Ollama:   {'OK' if report.ollama_ok else 'UNREACHABLE'} " f"({DEFAULT_OLLAMA_URL})",
        f"  Models:   {len(report.installed_models)} installed",
    ]
    for m in REQUIRED_MODELS:
        mark = "✓" if m in report.installed_models else "✗"
        lines.append(f"            {mark} {m}")
    lines.append(f"  RAM:      {report.free_ram_gb:.1f} GB available")
    lines.append(f"  Disk:     {report.free_disk_gb:.1f} GB free")
    for w in report.warnings:
        lines.append(f"  WARN:     {w}")
    lines.append("=" * 30)
    return "\n".join(lines)

"""E2E — Todo CRUD app generation via real Ollama.

This is the smallest of the three Stage 3 reference projects (PROJECT_PLAN
§7.5 — 낮음 복잡도, 30분 목표). It exercises the golden path: strategy →
decompose → parallel SLM execution → file writeout. No peer-review / rework
is expected on the happy path, but the pipeline must not abort either way.

Classification (harness.classify_result):
  green  : primary passed + ≥3 KPI targets met
  yellow : primary passed + <3 KPI targets
  red    : pipeline aborted or 0 files generated

Reports written to ``benchmarks/reports/e2e/todo/run-<ts>.json``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from main import orchestrate_project

from adapters.event_bus import InProcessEventBus
from adapters.ollama_provider import OllamaProvider
from adapters.shared_workspace import SharedWorkspace
from adapters.sqlite_message_queue import SQLiteMessageQueue
from adapters.sqlite_storage import SQLiteStorage
from application.agent_factory import SystemConfig
from application.dna_manager import DNAManager
from observability.metrics import MetricsCollector

from .harness import classify_result, format_preflight, preflight, write_report

TODO_REQUEST = (
    "간단한 Todo CRUD 웹 애플리케이션을 만들어주세요. "
    "FastAPI 백엔드 + SQLite 저장 + React 프런트엔드 + 기본 단위 테스트."
)
REPORTS_ROOT = Path("benchmarks/reports/e2e")


@pytest.mark.slow
async def test_todo_app_e2e(tmp_path: Path) -> None:
    """Run Todo generation end-to-end, classify KPI, write JSON report."""
    report = await preflight()
    skip = report.skip_reason()
    if skip:
        pytest.skip(skip)
    print("\n" + format_preflight(report))

    output_dir = tmp_path / "outputs"
    db_path = str(tmp_path / "e2e.db")
    config = SystemConfig(
        run_id="e2e-todo",
        output_dir=output_dir,
        db_path=db_path,
    )

    storage = SQLiteStorage(db_path)
    await storage.init()

    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    queue = SQLiteMessageQueue(storage=storage)
    dna_manager = DNAManager(storage=storage)
    metrics = MetricsCollector()

    async with OllamaProvider(base_url=config.ollama_base_url) as llm:
        result = await orchestrate_project(
            request=TODO_REQUEST,
            config=config,
            storage=storage,
            workspace=workspace,
            queue=queue,
            llm=llm,
            dna_manager=dna_manager,
        )

    await storage.close()

    classified = classify_result(
        project="todo",
        project_result=result,
        metrics=metrics,
    )
    report_path = write_report(classified, REPORTS_ROOT)
    print(f"\nE2E Todo classification: {classified.classification.upper()}")
    print(f"KPI targets met: {classified.kpi_targets_met}/5 (executable manual)")
    print(f"Report: {report_path}")

    assert classified.classification != "red", f"Todo E2E pipeline aborted — see {report_path}"

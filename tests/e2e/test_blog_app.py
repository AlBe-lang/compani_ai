"""E2E — 간단한 블로그 앱 (협업 기능 검증 목표).

PROJECT_PLAN §7.5 기준: 중간 복잡도, 1시간 예상. Todo 대비 의존성/QA 루프가
발생하기 쉬운 요청 문자열 — Backend↔Frontend 간 API 계약 조율, MLOps CI
연동 등으로 peer review 또는 blocking.detected 가 실제 발현할지 측정.

분류 기준은 harness.classify_result — Todo와 동일하지만 collab KPI(Q&A
성공률) 가중치가 상대적으로 이 프로젝트에서 중요.
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

BLOG_REQUEST = (
    "여러 사용자가 글을 작성·수정·삭제할 수 있는 간단한 블로그 플랫폼을 만들어주세요. "
    "FastAPI 백엔드(게시글 CRUD + 사용자 인증) + React 프런트엔드(목록/상세/에디터) "
    "+ SQLite 저장 + GitHub Actions CI. 프런트와 백엔드의 API 스펙은 서로 일치해야 합니다."
)
REPORTS_ROOT = Path("benchmarks/reports/e2e")


@pytest.mark.slow
async def test_blog_app_e2e(tmp_path: Path) -> None:
    """Run Blog generation end-to-end, classify KPI, write JSON report."""
    report = await preflight()
    skip = report.skip_reason()
    if skip:
        pytest.skip(skip)
    print("\n" + format_preflight(report))

    output_dir = tmp_path / "outputs"
    db_path = str(tmp_path / "e2e.db")
    config = SystemConfig(
        run_id="e2e-blog",
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
            request=BLOG_REQUEST,
            config=config,
            storage=storage,
            workspace=workspace,
            queue=queue,
            llm=llm,
            dna_manager=dna_manager,
        )

    await storage.close()

    classified = classify_result(
        project="blog",
        project_result=result,
        metrics=metrics,
    )
    report_path = write_report(classified, REPORTS_ROOT)
    print(f"\nE2E Blog classification: {classified.classification.upper()}")
    print(f"KPI targets met: {classified.kpi_targets_met}/5 (executable manual)")
    print(f"Report: {report_path}")

    assert classified.classification != "red", f"Blog E2E pipeline aborted — see {report_path}"

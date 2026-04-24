"""E2E — 방명록 앱 (전체 시스템 안정성 검증 목표).

PROJECT_PLAN §7.5 기준: 낮음~중간 복잡도, 45분 예상. Todo/Blog 사이에
위치한 요청으로, 단순 저장/조회만 있지만 UX 요소(페이지네이션·스팸 필터)가
약간 추가되어 MLOps 배포 스크립트까지 end-to-end 로 통과하는지 확인하는
용도. Primary DoD 관점에서 3건 중 가장 '실행-완료율' 이 높게 나와야 함.
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

GUESTBOOK_REQUEST = (
    "간단한 방명록 웹 애플리케이션을 만들어주세요. "
    "FastAPI 백엔드(방명록 글 작성/목록 조회, 페이지네이션) + 간단한 HTML/JS 프런트엔드 "
    "+ SQLite 저장 + 배포용 Dockerfile. 인증은 불필요."
)
REPORTS_ROOT = Path("benchmarks/reports/e2e")


@pytest.mark.slow
async def test_guestbook_app_e2e(tmp_path: Path) -> None:
    """Run Guestbook generation end-to-end, classify KPI, write JSON report."""
    report = await preflight()
    skip = report.skip_reason()
    if skip:
        pytest.skip(skip)
    print("\n" + format_preflight(report))

    output_dir = tmp_path / "outputs"
    db_path = str(tmp_path / "e2e.db")
    config = SystemConfig(
        run_id="e2e-guestbook",
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
            request=GUESTBOOK_REQUEST,
            config=config,
            storage=storage,
            workspace=workspace,
            queue=queue,
            llm=llm,
            dna_manager=dna_manager,
        )

    await storage.close()

    classified = classify_result(
        project="guestbook",
        project_result=result,
        metrics=metrics,
    )
    report_path = write_report(classified, REPORTS_ROOT)
    print(f"\nE2E Guestbook classification: {classified.classification.upper()}")
    print(f"KPI targets met: {classified.kpi_targets_met}/5 (executable manual)")
    print(f"Report: {report_path}")

    assert classified.classification != "red", f"Guestbook E2E pipeline aborted — see {report_path}"

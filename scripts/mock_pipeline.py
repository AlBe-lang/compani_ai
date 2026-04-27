#!/usr/bin/env python
"""Mock pipeline for live demo / presentation (v2 — rich storytelling).

같은 CLI 인터페이스(``python scripts/mock_pipeline.py "<request>"``)와
stderr JSON 이벤트 포맷(structlog 호환)을 사용해 ``main.py`` 를 대체.

특징:
- Ollama / 실제 LLM 호출 없음 → 네트워크/하드웨어 변수 제거 (시연 안전)
- ~45초 안에 전체 파이프라인 시각화
- ``outputs/<project_slug>/`` 에 실제 산출물 파일 트리 생성
- 각 통신(QA / 회의 / 피어 리뷰)에 풍부한 컨텍스트 데이터 emit
  (왜 발생했나, 누가 무엇을 말했나, 어떤 결정이 내려졌나)
- 각 stage 의 sub-status 이벤트 추가 (UI 가 라이브 진행 메시지 표시 가능)

이벤트 시퀀스는 ``main.py`` / orchestrator 실 흐름의 이벤트명을 그대로 사용
(orchestrator.*, cto.*, slm.*, queue.*, peer_review.*, meeting.*) — 데모 UI
``DemoPage.tsx`` 의 분기 로직과 호환.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ────────────────────────────────────────────────────────────────────
# 상수
# ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "outputs" / ".demo_mock_template"
OUTPUTS_ROOT = PROJECT_ROOT / "outputs"

# 시연용 시간 가속 배수: 1.0 = 정상(~45s), 0.5 = 2배 빠름(~22s).
SPEED = float(os.environ.get("MOCK_SPEED", "1.0"))


def _emit(level: str, event: str, **fields: object) -> None:
    """structlog JSON-per-line 포맷으로 stderr 에 emit."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def _sleep(sec: float) -> None:
    time.sleep(sec * SPEED)


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "project"


# ────────────────────────────────────────────────────────────────────
# 이벤트 시퀀스 (시연 스크립트)
# ────────────────────────────────────────────────────────────────────


def run_pipeline(request: str) -> int:
    project_name = "Todo REST API (mock)"
    project_slug = "todo-rest-api-mock"  # 실제 데모와 폴더 충돌 방지
    output_dir = OUTPUTS_ROOT / project_slug
    run_id = "mock" + datetime.now().strftime("%H%M%S")

    _emit(
        "info",
        "orchestrator.start",
        run_id=run_id,
        request_chars=len(request),
        mode="mock-demo",
    )
    _sleep(0.4)

    # ── Stage 1: CTO 전략 수립 ─────────────────────────────────────
    _emit("info", "ollama.health_check", host="http://localhost:11434", ok=True)
    _sleep(0.3)
    _emit(
        "info",
        "orchestrator.strategy.start",
        request_length=len(request),
        sub_status="CTO 가 사용자 요청 분석 시작",
    )
    _emit(
        "info",
        "cto.thinking",
        sub_status="요구사항 정리: REST + CRUD + auth 식별",
    )
    _sleep(0.8)
    _emit(
        "info",
        "llm.generate.start",
        model="qwen3:8b",
        component="cto",
        prompt_tokens=512,
        sub_status="qwen3:8b 추론 호출 (전략 생성)",
    )
    _sleep(2.5)
    _emit(
        "info",
        "llm.generate.done",
        model="qwen3:8b",
        component="cto",
        completion_tokens=387,
        duration_sec=2.4,
    )
    _emit(
        "info",
        "cto.strategy.done",
        project_name=project_name,
        complexity="medium",
        estimated_files=11,
        sub_status="전략 확정: backend(FastAPI)+frontend(React)+deploy(Docker)",
    )
    _emit("info", "orchestrator.strategy.done", project_name=project_name)
    _sleep(0.4)

    # ── Stage 2: 작업 분해 ────────────────────────────────────────
    _emit(
        "info",
        "cto.decompose.start",
        sub_status="전략을 실행 가능 task 단위로 분해 중",
    )
    _emit(
        "info",
        "llm.generate.start",
        model="qwen3:8b",
        component="cto",
        prompt_tokens=634,
    )
    _sleep(1.8)
    _emit(
        "info",
        "llm.generate.done",
        model="qwen3:8b",
        component="cto",
        completion_tokens=521,
        duration_sec=1.7,
    )
    _emit(
        "info",
        "cto.decompose.done",
        task_count=5,
        sub_status="5개 task 생성: backend 2 / frontend 1 / mlops 2",
    )
    _emit("info", "orchestrator.decompose.done", task_count=5)
    _sleep(0.4)

    # ── Stage 3: 에이전트 병렬 실행 ───────────────────────────────
    tasks = [
        ("T-001", "backend", "FastAPI Todo CRUD endpoints (GET/POST/PUT/DELETE)"),
        ("T-002", "frontend", "React Todo list UI with TypeScript"),
        ("T-003", "mlops", "Dockerfile + docker-compose.yml"),
        ("T-004", "backend", "JWT auth middleware + login endpoint"),
        ("T-005", "mlops", "GitHub Actions CI workflow"),
    ]

    # 첫 3개 동시 시작
    for tid, role, desc in tasks[:3]:
        _emit(
            "info",
            "slm.task.start",
            task_id=tid,
            role=role,
            agent_id=role,
            description=desc,
            model="gemma4:e4b" if role != "mlops" else "llama3.2:3b",
        )
        _sleep(0.15)

    _sleep(1.8)

    # ── QA #1: backend → frontend (PATCH 형식 협의) ─────────────
    qa1_id = "qa-001"
    _emit(
        "info",
        "queue.qa.sent",
        qa_id=qa1_id,
        from_agent="backend",
        to_agent="frontend",
        task_id="T-001",
        task_context="FastAPI Todo CRUD 엔드포인트 작성 중",
        reason="PATCH 응답 형식이 frontend 와 호환되는지 사전 확인 필요",
        question=(
            "Todo 항목의 부분 업데이트 시 어떤 PATCH 형식을 사용하는 게 좋을까요? "
            "JSON Patch (RFC 6902, op 기반) 또는 JSON Merge Patch (RFC 7396, "
            "단순 객체 머지) 중 선택해야 합니다."
        ),
    )
    _sleep(1.4)
    _emit(
        "info",
        "queue.qa.received",
        qa_id=qa1_id,
        from_agent="frontend",
        to_agent="backend",
        task_id="T-001",
        answer="JSON Merge Patch (RFC 7396) 사용을 권장합니다.",
        reasoning=(
            "JSON Patch 는 op 배열 기반이라 frontend 코드가 복잡해집니다. "
            "Merge Patch 는 변경된 필드만 객체로 보내면 되어 React 의 setState "
            "결과를 그대로 직렬화 가능합니다. Todo 같은 단순 리소스에 적합합니다."
        ),
    )
    _sleep(0.6)

    # ── QA #2: frontend → mlops (CORS) ──────────────────────────
    qa2_id = "qa-002"
    _emit(
        "info",
        "queue.qa.sent",
        qa_id=qa2_id,
        from_agent="frontend",
        to_agent="mlops",
        task_id="T-002",
        task_context="React 개발 서버에서 backend API 호출 준비",
        reason="개발 환경에서 CORS 미설정 시 API 호출 차단 우려",
        question="개발 모드에서 CORS 설정이 필요한가요? backend 가 어떤 origin 을 허용해야 합니까?",
    )
    _sleep(0.7)
    _emit(
        "info",
        "queue.qa.received",
        qa_id=qa2_id,
        from_agent="mlops",
        to_agent="frontend",
        task_id="T-002",
        answer="네, 필요합니다. docker-compose.yml 에 환경변수로 ALLOW_ORIGINS=http://localhost:5173 설정하겠습니다.",
        reasoning=(
            "Vite dev server 가 5173 포트를 쓰고 backend 는 8000 이라 cross-origin. "
            "프로덕션에서는 같은 도메인 또는 reverse proxy 로 회피 가능."
        ),
    )
    _sleep(2.2)

    # ── T-001 완료 (backend CRUD) ─────────────────────────────
    _emit(
        "info",
        "slm.task.done",
        task_id="T-001",
        role="backend",
        agent_id="backend",
        files=4,
        duration_sec=6.8,
        retries=0,
    )
    _sleep(0.3)

    # ── T-001 의존하는 T-004 (auth) 시작 ──────────────────────
    _emit(
        "info",
        "slm.task.start",
        task_id="T-004",
        role="backend",
        agent_id="backend",
        description=tasks[3][2],
        model="gemma4:e4b",
    )
    _sleep(1.5)

    # ── 회의 (Emergency Meeting): Docker 빌드 충돌 ────────────
    meeting_id = "m-001"
    _emit(
        "info",
        "meeting.opened",
        meeting_id=meeting_id,
        title="Emergency: T-003 Docker 빌드 충돌",
        reason=(
            "T-001 (Backend) 산출물에서 redis 의존성을 추가했는데 "
            "T-003 (MLOps) 의 docker-compose.yml 에 redis 서비스가 빠져있음. "
            "이대로 두면 컨테이너 빌드 시 connection refused 발생 가능."
        ),
        attendees=["cto", "backend", "mlops"],
        trigger="blocking.detected",
    )
    _sleep(0.6)
    _emit(
        "info",
        "meeting.message",
        meeting_id=meeting_id,
        speaker="mlops",
        text=(
            "T-001 코드를 보니 from redis import Redis 가 추가됐는데 docker-compose 에는 redis 서비스가 없어. "
            "이대로 빌드하면 backend 가 startup 에서 ConnectionRefusedError 던질 거야."
        ),
    )
    _sleep(0.5)
    _emit(
        "info",
        "meeting.message",
        meeting_id=meeting_id,
        speaker="backend",
        text=(
            "redis 는 캐시용으로 추가했는데, 사실 v1 에서는 in-memory dict 로도 충분합니다. "
            "redis 없이 동작하는 fallback 로직을 코드에 넣을 수 있어요."
        ),
    )
    _sleep(0.5)
    _emit(
        "info",
        "meeting.message",
        meeting_id=meeting_id,
        speaker="cto",
        text=(
            "두 옵션 모두 가능. mlops 의견: 런타임 신뢰성. backend 의견: 의존성 단순화. "
            "결정: T-003 update — redis service 추가하고 backend 가 의존하게 설정. "
            "이유: 캐시는 v1.1 데모에서도 메트릭 가시화에 도움. T-001 코드는 유지."
        ),
    )
    _sleep(0.5)
    _emit(
        "info",
        "meeting.closed",
        meeting_id=meeting_id,
        decision="T-003 update — docker-compose 에 redis service 추가",
        duration_sec=5.2,
        outcome="resolved",
    )
    _sleep(0.6)

    # ── 피어 리뷰: T-001 (frontend reviewer) ──────────────────
    review_id = "pr-001"
    _emit(
        "info",
        "peer_review.opened",
        review_id=review_id,
        task_id="T-001",
        author="backend",
        reviewer="frontend",
        files_under_review=4,
        reason="T-001 산출물이 frontend 가 소비하는 API. 호환성 사전 검토 필요.",
    )
    _sleep(0.5)
    _emit(
        "info",
        "peer_review.comment",
        review_id=review_id,
        file="routers/todos.py",
        line=28,
        severity="MINOR",
        comment=(
            "POST /api/todos 응답 status code 가 200 OK 인데, REST 컨벤션상 새 리소스 "
            "생성은 201 Created 가 적절합니다. frontend Location 헤더 활용 가능성도."
        ),
    )
    _sleep(0.5)
    _emit(
        "info",
        "peer_review.comment",
        review_id=review_id,
        file="models.py",
        line=None,
        severity="INFO",
        comment="Pydantic schema 분리가 깔끔합니다. TodoOut / TodoCreate / TodoPatch 구조 그대로 frontend types 으로 옮길 수 있겠네요. 👍",
    )
    _sleep(0.5)
    _emit(
        "info",
        "peer_review.closed",
        review_id=review_id,
        verdict="PASSED",
        comment_count=2,
        highest_severity="MINOR",
        decision="병합 가능. 권고 1건 (POST 201) 은 follow-up patch 에서 처리.",
        task_id="T-001",
        reviewer="frontend",
        author="backend",
    )
    _sleep(0.6)

    # ── T-002 완료 ────────────────────────────────────────────
    _emit(
        "info",
        "slm.task.done",
        task_id="T-002",
        role="frontend",
        agent_id="frontend",
        files=3,
        duration_sec=8.2,
        retries=0,
    )
    _sleep(0.4)

    # ── T-005 시작 ────────────────────────────────────────────
    _emit(
        "info",
        "slm.task.start",
        task_id="T-005",
        role="mlops",
        agent_id="mlops",
        description=tasks[4][2],
        model="llama3.2:3b",
    )
    _sleep(1.8)

    # ── T-003 완료 ────────────────────────────────────────────
    _emit(
        "info",
        "slm.task.done",
        task_id="T-003",
        role="mlops",
        agent_id="mlops",
        files=2,
        duration_sec=9.4,
        retries=0,
    )
    _sleep(0.3)

    # ── T-004 완료 ────────────────────────────────────────────
    _emit(
        "info",
        "slm.task.done",
        task_id="T-004",
        role="backend",
        agent_id="backend",
        files=2,
        duration_sec=4.9,
        retries=0,
    )
    _sleep(1.0)

    # ── T-005 완료 ────────────────────────────────────────────
    _emit(
        "info",
        "slm.task.done",
        task_id="T-005",
        role="mlops",
        agent_id="mlops",
        files=1,
        duration_sec=3.7,
        retries=0,
    )
    _sleep(0.4)

    # ── Stage 4: Stage Gate ──────────────────────────────────
    _emit(
        "info",
        "stage_gate.evaluate.start",
        task_count=5,
        success_count=5,
        fail_count=0,
        sub_status="모든 task 결과 + peer review verdict 종합 평가",
    )
    _sleep(0.7)
    _emit(
        "info",
        "orchestrator.gate",
        verdict="pass",
        success_rate=1.0,
        avg_duration_sec=6.6,
        sub_status="게이트 통과 — 산출물 저장 단계로 진행",
    )
    _sleep(0.4)

    # ── Stage 5: 파일 저장 ──────────────────────────────────
    _emit("info", "file_storage.write.start", project=project_name)

    # 산출물 디렉토리 준비
    if output_dir.exists():
        shutil.rmtree(output_dir)
    if not TEMPLATE_DIR.exists():
        _emit(
            "error",
            "mock.template_missing",
            detail=f"template not found at {TEMPLATE_DIR}",
        )
        return 1
    shutil.copytree(TEMPLATE_DIR, output_dir)

    file_count = 0
    for f in sorted(output_dir.rglob("*")):
        if f.is_file():
            file_count += 1
            rel = f.relative_to(output_dir)
            _emit(
                "info",
                "file_storage.write",
                path=str(rel),
                bytes=f.stat().st_size,
            )
            _sleep(0.04)

    _emit(
        "info",
        "file_storage.write.done",
        project=project_name,
        files=file_count,
        output_slug=project_slug,
    )
    _sleep(0.3)

    # ── 종료 ─────────────────────────────────────────────────
    _emit(
        "info",
        "orchestrator.done",
        project_name=project_name,
        files=file_count,
        success=True,
        total_tasks=5,
        output_slug=project_slug,
    )
    _sleep(0.2)

    # main.py 와 동일한 stdout summary
    print(f"\nProject: {project_name}", file=sys.stdout, flush=True)
    print("Status:  SUCCESS (mock)", file=sys.stdout, flush=True)
    print(f"Tasks:   5/5 completed", file=sys.stdout, flush=True)
    print(f"Files:   {file_count} generated → {output_dir}", file=sys.stdout, flush=True)
    print(f"Time:    {45 * SPEED:.1f}s", file=sys.stdout, flush=True)

    return 0


def main() -> int:
    if len(sys.argv) < 2:
        _emit("error", "mock.usage", detail="usage: mock_pipeline.py '<request>'")
        return 2
    request = sys.argv[1]
    try:
        return run_pipeline(request)
    except KeyboardInterrupt:
        _emit("warning", "mock.cancelled", detail="SIGINT")
        return 130
    except Exception as exc:  # noqa: BLE001 — 시연용 안전망
        _emit("error", "mock.crash", detail=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())

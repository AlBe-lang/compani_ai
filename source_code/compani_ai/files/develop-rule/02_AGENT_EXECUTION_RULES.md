# 에이전트 실행 규칙 (AGENT EXECUTION RULES)

> 대상 파트: **SLM Agents / Execution Layer**
> 레이어 위치: `application/slm_agent.py`, `application/agents/`
> 공통 규칙(`00_COMMON_RULES.md`)을 반드시 먼저 읽으세요.

---

## 1. 역할 정의

SLM Agent는 **코드를 실제로 생성하는 유일한 주체**입니다.

```
Frontend Agent 담당:
  - React / Flutter 컴포넌트 및 화면
  - 상태 관리 (Context, Provider, MobX 등)
  - API 연동 코드 (클라이언트 측)
  - CSS / 스타일링

Backend Agent 담당:
  - FastAPI 라우터 및 엔드포인트
  - Pydantic 요청/응답 스키마
  - 비즈니스 로직 서비스 레이어
  - DB 스키마 (SQLAlchemy 모델 또는 raw SQL)

MLOps Agent 담당:
  - Dockerfile, docker-compose.yml
  - GitHub Actions CI/CD yml
  - 환경변수 템플릿 (.env.example)
  - 배포 스크립트 (shell)
  - 의존성 파일 (requirements.txt, package.json)
```

---

## 2. 모델 사용 규칙

| 항목 | Frontend | Backend | MLOps |
|------|---------|---------|-------|
| 모델 | `phi3.5` | `phi3.5` | `llama3.2:3b` |
| temperature | 0.5 (창의성 필요) | 0.2 (정확성 우선) | 0.1 (결정론적) |
| 타임아웃 | 90초 | 90초 | 60초 |
| 재시도 | 최대 3회 | 최대 3회 | 최대 3회 |

---

## 3. 클래스 구조 규칙

```python
# application/slm_agent.py

class SimpleSLM:
    """
    역할별 코드 생성 에이전트.
    LLMProvider, WorkSpacePort, MessageQueuePort를 주입받아 동작.
    """

    def __init__(
        self,
        role: AgentRole,               # "frontend" | "backend" | "mlops"
        llm: LLMProvider,
        workspace: WorkSpacePort,
        queue: MessageQueuePort,
        config: SLMConfig,
    ) -> None: ...

    # 공개 메서드
    async def execute_task(self, task: Task) -> TaskResult: ...

    # 비공개 메서드
    async def _wait_dependencies(self, deps: list[str]) -> None: ...
    async def _check_needs_info(self, task: Task) -> bool: ...
    async def _ask_question(self, question: str, context: dict) -> str: ...
    async def _build_prompt(self, task: Task, context: dict) -> str: ...
    async def _parse_response(self, raw: str) -> TaskResult: ...
    def _get_system_prompt(self) -> str: ...
```

---

## 4. execute_task() 실행 순서 — 변경 금지

아래 순서는 안정성 검증이 완료된 표준 흐름입니다. 순서 변경 금지.

```python
async def execute_task(self, task: Task) -> TaskResult:
    # 1. WorkItem 생성 및 등록 (status: PLANNED)
    work_item = await self.workspace.register(task, agent_id=self.role)

    # 2. 상태 → IN_PROGRESS
    await self.workspace.set_status(work_item.id, WorkStatus.IN_PROGRESS)

    # 3. 의존성 대기 (timeout: 300초)
    await self._wait_dependencies(task.dependencies)

    # 4. 추가 정보 필요 시 Q&A
    context = {}
    if await self._check_needs_info(task):
        answer = await self._ask_question(
            self._formulate_question(task), context
        )
        context["qa_answer"] = answer

    # 5. 프롬프트 구성
    prompt = self._build_prompt(task, context)

    # 6. LLM 호출 (재시도 포함)
    raw = await self._call_with_retry(prompt)

    # 7. 응답 파싱 및 검증
    result = await self._parse_response(raw)

    # 8. 완료 처리 (status: DONE)
    await self.workspace.set_status(work_item.id, WorkStatus.DONE)
    await self.workspace.attach_result(work_item.id, result)

    return result
```

---

## 5. System Prompt 규칙

### 5.1 역할별 System Prompt 위치

```
application/prompts/
├── frontend_system.txt
├── backend_system.txt
└── mlops_system.txt
```

코드 안에 프롬프트 문자열을 하드코딩하지 않습니다.
파일로 분리하고 `_get_system_prompt()`에서 파일을 읽어 반환합니다.

### 5.2 System Prompt 필수 포함 항목

```
[Frontend]
- 사용할 프레임워크 (React 또는 Flutter — Task에서 지정)
- 출력 형식: JSON (approach, code, files, dependencies)
- 파일 분리 기준 (컴포넌트 1개 = 파일 1개)
- 코드만 출력, 설명 최소화

[Backend]
- 사용할 프레임워크 (FastAPI)
- 타입 힌트, Pydantic 필수
- 출력 형식: JSON (approach, code, files, dependencies)
- 보안 기본 적용 (입력 검증, SQL 인젝션 방지)

[MLOps]
- 대상 환경 (로컬 Mac Mini M4 / Docker)
- 출력 형식: JSON (approach, files)
- 보안 기본 적용 (포트 최소 노출, 환경변수 사용)
```

---

## 6. 의존성 대기 규칙

```python
async def _wait_dependencies(self, deps: list[str]) -> None:
    TIMEOUT_SEC = 300
    POLL_INTERVAL_SEC = 2

    deadline = asyncio.get_event_loop().time() + TIMEOUT_SEC

    for dep_id in deps:
        while True:
            if asyncio.get_event_loop().time() > deadline:
                raise AgentError(ErrorCode.E_DEPS_TIMEOUT, dep_id=dep_id)

            item = await self.workspace.get(dep_id)

            if item is None:
                raise AgentError(ErrorCode.E_DEPS_BLOCKED, dep_id=dep_id)

            if item.status == WorkStatus.DONE:
                break

            if item.status == WorkStatus.FAILED:
                raise AgentError(ErrorCode.E_DEPS_BLOCKED, dep_id=dep_id)

            await asyncio.sleep(POLL_INTERVAL_SEC)
```

### 규칙
- 폴링 간격은 **2초 고정** (1초 미만 금지 — Ollama 부하)
- 타임아웃은 **300초 고정** (config에서 변경 가능하나 기본값 준수)
- 의존 대상이 FAILED면 즉시 에러 — 무한 대기 금지

---

## 7. Q&A 요청 규칙

```python
async def _check_needs_info(self, task: Task) -> bool:
    """
    다음 조건 중 하나라도 해당하면 Q&A 필요:
    1. task.dependencies가 있고 의존 결과에서 API 스펙이 필요한 경우
    2. task.description에 '?' 포함 (CTO가 명시한 불명확 항목)
    3. task.acceptance_criteria에 외부 인터페이스 명세가 필요한 경우
    """
    ...

async def _ask_question(self, question: str, context: dict) -> str:
    # 30초 타임아웃
    # 타임아웃 시 빈 컨텍스트로 진행 (에러로 중단하지 않음)
    try:
        return await asyncio.wait_for(
            self.queue.ask(from_agent=self.role, question=question, context=context),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        log.warning("qa.timeout", task_id=context.get("task_id"), question=question[:50])
        return ""   # 빈 컨텍스트로 계속 진행
```

---

## 8. 응답 파싱 규칙

### 8.1 필수 출력 형식 (LLM이 반환해야 하는 구조)

```json
{
  "approach": "FastAPI + SQLAlchemy ORM 사용",
  "code": {
    "main.py": "from fastapi import FastAPI\n...",
    "models.py": "from sqlalchemy import ...\n..."
  },
  "files": [
    {"name": "main.py", "path": "backend/main.py", "type": "python"},
    {"name": "models.py", "path": "backend/models.py", "type": "python"}
  ],
  "dependencies": ["fastapi", "uvicorn", "sqlalchemy"]
}
```

### 8.2 파싱 실패 시 재시도

```python
async def _parse_response(self, raw: str) -> TaskResult:
    for attempt in range(3):
        try:
            data = self._extract_json(raw)
            return TaskResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            if attempt == 2:
                raise AgentError(ErrorCode.E_PARSE_JSON, detail=str(e))
            # 재시도 전 프롬프트에 "JSON만 출력" 힌트 추가
            raw = await self._retry_with_format_hint(raw)
```

---

## 9. 로그 규칙 (SLM 전용 이벤트)

```python
log.info("slm.task.start",   run_id=run_id, task_id=task.id, role=self.role)
log.info("slm.deps.waiting", run_id=run_id, task_id=task.id, deps=task.dependencies)
log.info("slm.qa.sent",      run_id=run_id, task_id=task.id, question=q[:80])
log.info("slm.llm.call",     run_id=run_id, task_id=task.id, model=self.model)
log.info("slm.task.done",    run_id=run_id, task_id=task.id, files=len(result.files))
log.error("slm.task.failed", run_id=run_id, task_id=task.id,
          error_code=e.code, detail=e.detail)
```

---

## 10. 금지 사항 (SLM 전용)

| 번호 | 금지 사항 |
|------|---------|
| S-01 | SLM이 다른 SLM을 직접 호출 (반드시 MessageQueue 경유) |
| S-02 | SLM이 Strategy를 생성하거나 수정 (CTO 전담) |
| S-03 | 폴링 간격 1초 미만 설정 |
| S-04 | Q&A 타임아웃 발생 시 예외로 중단 (빈 컨텍스트로 계속 진행) |
| S-05 | 프롬프트 문자열을 코드에 하드코딩 |
| S-06 | 역할 경계를 넘는 코드 생성 (Backend가 Dockerfile 생성 등) |
| S-07 | LLM 응답을 검증 없이 바로 파일로 저장 |

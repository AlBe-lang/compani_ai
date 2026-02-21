# 오케스트레이션 규칙 (ORCHESTRATION RULES)

> 대상 파트: **CTO Agent / Orchestration Layer**
> 레이어 위치: `application/cto_agent.py`, `application/orchestrator.py`
> 공통 규칙(`00_COMMON_RULES.md`)을 반드시 먼저 읽으세요.

---

## 1. 역할 정의

CTO Agent는 시스템의 **유일한 오케스트레이터**입니다.

```
담당:
  - 사용자 자연어 입력 → 구조화된 Strategy 변환
  - Strategy → Task 목록으로 분해 (decompose)
  - Task를 적절한 SLM 에이전트에게 위임 (delegate)
  - 전체 진행 상황 모니터링 및 최종 결과 집계
  - Stage Gate 회의 주관 (Phase 5+)

담당하지 않는 것:
  - 실제 코드 생성 (SLM 전담)
  - WorkSpace 직접 조작 (Collaboration Layer 전담)
  - LLM API 직접 호출 (OllamaProvider 전담)
```

---

## 2. 모델 사용 규칙

| 항목 | 값 |
|------|-----|
| 모델 | `llama3.1:70b` (4bit 양자화) |
| 온도(temperature) | 0.3 — 전략 수립은 일관성이 중요 |
| 최대 토큰 | 4096 |
| 타임아웃 | 120초 (전략 수립), 60초 (작업 분해) |
| 재시도 | 최대 3회, 지수 백오프 (2s → 4s → 8s) |

CTO Agent는 **전략 수립과 조율만** 담당하므로 LLM 호출 빈도를 최소화합니다.
SLM이 처리 가능한 판단은 CTO에게 위임하지 않습니다.

---

## 3. 클래스 구조 규칙

```python
# application/cto_agent.py

class CTOAgent:
    """
    유일한 오케스트레이터. 전략 수립과 팀 조율만 담당.
    LLM 호출은 LLMProvider 인터페이스를 통해서만 수행.
    """

    def __init__(
        self,
        llm: LLMProvider,           # 인터페이스 주입 (OllamaProvider or Mock)
        workspace: WorkSpacePort,   # 인터페이스 주입
        team: dict[str, AgentPort], # role → agent 매핑
        config: CTOConfig,
    ) -> None: ...

    # 공개 메서드 — 외부에서 호출 가능
    async def orchestrate_project(self, idea: str) -> ProjectResult: ...
    async def create_strategy(self, idea: str) -> Strategy: ...
    async def decompose_tasks(self, strategy: Strategy) -> list[Task]: ...
    async def delegate_task(self, task: Task) -> TaskResult: ...

    # 비공개 메서드 — 내부 전용
    async def _build_strategy_prompt(self, idea: str) -> str: ...
    async def _validate_strategy(self, raw: str) -> Strategy: ...
    async def _select_agent(self, task: Task) -> AgentPort: ...
```

### 규칙
- `orchestrate_project()`는 전체 흐름의 **유일한 진입점**
- 각 메서드는 **단일 책임** (전략 수립 / 분해 / 위임을 혼합하지 않음)
- `_` 접두어 메서드는 외부에서 직접 호출 금지

---

## 4. Strategy 생성 규칙

### 4.1 LLM 응답 파싱 — 방어적 파싱 필수

```python
async def _validate_strategy(self, raw: str) -> Strategy:
    # 1단계: JSON 블록 추출
    json_match = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
    if not json_match:
        # JSON 블록 없으면 전체 텍스트에서 시도
        json_str = raw.strip()
    else:
        json_str = json_match.group(1)

    # 2단계: 파싱
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise AgentError(ErrorCode.E_PARSE_JSON, detail=str(e))

    # 3단계: Pydantic 검증
    try:
        return Strategy.model_validate(data)
    except ValidationError as e:
        raise AgentError(ErrorCode.E_PARSE_SCHEMA, detail=str(e))
```

### 4.2 재시도 로직 — 공통 패턴

```python
async def _with_retry(self, coro_fn, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except AgentError as e:
            if e.code in (ErrorCode.E_LLM_TIMEOUT, ErrorCode.E_PARSE_JSON):
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
            raise
    raise AgentError(ErrorCode.E_LLM_UNAVAILABLE)
```

---

## 5. 작업 분해 규칙 (Task Decomposition)

### 5.1 작업 할당 원칙

| role | 담당 |
|------|------|
| `frontend` | UI 컴포넌트, 화면, 상태 관리 |
| `backend` | API 엔드포인트, DB 스키마, 비즈니스 로직 |
| `mlops` | Dockerfile, CI/CD, 환경 설정, 배포 스크립트 |

CTO는 작업을 분해할 때 **역할 경계를 넘는 Task를 생성하지 않습니다.**
(예: backend Task에 Dockerfile 포함 금지)

### 5.2 의존성 설정 원칙

```
올바른 의존성:
  frontend.login_ui  → depends_on → backend.auth_api   ✅
  mlops.docker       → depends_on → backend.api_server  ✅

금지:
  backend → depends_on → frontend  ❌  (백엔드가 UI에 의존하면 안 됨)
  mlops   → depends_on → frontend  ❌  (인프라가 UI에 의존하면 안 됨)
```

### 5.3 Task 수 제한

- 단일 프로젝트: **최소 3개, 최대 15개** Task
- 15개 초과 시 Task 묶음 또는 단계 분리 검토

---

## 6. 오케스트레이션 흐름 규칙

```python
async def orchestrate_project(self, idea: str) -> ProjectResult:
    # 단계 1: 입력 검증 (application 레이어에서 처리)
    validated_idea = validate_user_input(idea)

    # 단계 2: 전략 수립
    strategy = await self._with_retry(
        lambda: self.create_strategy(validated_idea)
    )

    # 단계 3: 작업 등록 (WorkSpace에 위임 — CTO가 직접 조작 금지)
    await self.workspace.register_tasks(strategy.tasks)

    # 단계 4: 의존성 순서에 따라 병렬 실행
    results = await self._execute_in_order(strategy.tasks)

    # 단계 5: 결과 집계 및 반환
    return self._aggregate_results(results)
```

CTO는 WorkSpace를 **읽기 전용**으로만 사용합니다.
WorkItem 상태 변경은 SLM Agent와 WorkSpace가 처리합니다.

---

## 7. 로그 규칙 (CTO 전용 이벤트)

```python
# 전략 수립 시작
log.info("cto.strategy.start", run_id=run_id, idea_length=len(idea))

# 전략 수립 완료
log.info("cto.strategy.done", run_id=run_id, task_count=len(tasks))

# 작업 위임
log.info("cto.delegate", run_id=run_id, task_id=task.id, role=task.role)

# 프로젝트 완료
log.info("cto.project.done",
    run_id=run_id,
    success_rate=result.success_rate,
    duration_sec=result.duration_sec
)
```

---

## 8. 금지 사항 (오케스트레이션 전용)

| 번호 | 금지 사항 |
|------|---------|
| O-01 | CTO가 직접 코드를 생성하는 로직 작성 |
| O-02 | CTO가 WorkItem 상태를 직접 변경 |
| O-03 | CTO가 에이전트 간 메시지를 중계 (MessageQueue가 담당) |
| O-04 | 단일 Task에 복수 역할(role) 할당 |
| O-05 | LLM 호출 시 OllamaProvider 직접 import (인터페이스로만 접근) |
| O-06 | 재시도 없이 LLM 단발 호출 후 실패 처리 |

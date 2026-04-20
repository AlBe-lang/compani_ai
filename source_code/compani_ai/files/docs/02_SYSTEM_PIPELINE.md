# 시스템 파이프라인 설계서

> 버전: v1.0 | 작성일: 2026-02-21 | 상태: 확정

---

## 목차

1. [파이프라인 전체 구조](#1-파이프라인-전체-구조)
2. [개발 파이프라인](#2-개발-파이프라인)
3. [시스템 실행 파이프라인](#3-시스템-실행-파이프라인)
4. [에이전트 협업 파이프라인](#4-에이전트-협업-파이프라인)
5. [데이터 플로우 다이어그램](#5-데이터-플로우-다이어그램)
6. [CI/CD 파이프라인](#6-cicd-파이프라인)
7. [모니터링 파이프라인](#7-모니터링-파이프라인)
8. [에러 처리 파이프라인](#8-에러-처리-파이프라인)
9. [배포 파이프라인](#9-배포-파이프라인)

---

## 1. 파이프라인 전체 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                      파이프라인 전체 구조                         │
│                                                                   │
│   [개발 파이프라인]                                               │
│   로컬 개발 ──→ 코드 품질 검사 ──→ 테스트 ──→ CI/CD ──→ 배포     │
│                                                                   │
│              ↓ 배포 후 실행                                       │
│                                                                   │
│   [시스템 실행 파이프라인]                                        │
│   사용자 입력 ──→ 전략 수립 ──→ 작업 등록 ──→ 병렬 실행          │
│               ──→ 협업 처리 ──→ 결과 생성 ──→ 응답 반환          │
│                                                                   │
│              ↓ 실행 중                                            │
│                                                                   │
│   [모니터링 파이프라인]                                           │
│   로그 수집 ──→ 메트릭 집계 ──→ 대시보드 표시 ──→ 알림          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 개발 파이프라인

### 2.1 로컬 개발 워크플로우

```
개발자
  │
  ├── 1. 기능 브랜치 생성
  │       git checkout -b feature/phase1-cto-agent
  │
  ├── 2. 코드 작성
  │       IDE에서 개발
  │
  ├── 3. Pre-commit Hook 자동 실행
  │       ├── black (코드 포맷팅)
  │       ├── isort (임포트 정렬)
  │       ├── flake8 (린트 검사)
  │       └── mypy (타입 검사)
  │
  ├── 4. 로컬 테스트 실행
  │       make test-fast  (단위 + 통합, E2E 제외)
  │
  ├── 5. 커밋 및 푸시
  │       git commit -m "feat(cto): create_strategy 구현"
  │       git push origin feature/phase1-cto-agent
  │
  └── 6. Pull Request 생성 → 리뷰 → main 머지
```

### 2.2 브랜치 전략 (GitHub Flow)

```
main (항상 배포 가능한 상태)
  │
  ├── feature/phase1-base-agent        (BaseAgent 구현)
  │       └── PR ──→ Review ──→ Merge
  │
  ├── feature/phase1-cto-agent         (CTO Agent 구현)
  │       └── PR ──→ Review ──→ Merge
  │
  ├── feature/phase1-slm-agents        (SLM Agents 구현)
  │       └── PR ──→ Review ──→ Merge
  │
  ├── feature/phase2-workspace         (Shared Workspace)
  │       └── PR ──→ Review ──→ Merge
  │
  └── feature/phase2-message-queue     (메시지 큐)
          └── PR ──→ Review ──→ Merge
```

### 2.3 커밋 메시지 규칙 (Conventional Commits)

```
<type>(<scope>): <description>

type:
  feat     새 기능 추가
  fix      버그 수정
  docs     문서 변경
  test     테스트 추가/수정
  refactor 리팩토링 (기능 변경 없음)
  style    코드 포맷팅 (로직 변경 없음)
  chore    빌드/설정 변경

scope:
  cto       CTO Agent 관련
  slm       SLM Agent 관련
  workspace Shared Workspace 관련
  queue     메시지 큐 관련
  dna       DNA 시스템 관련
  gate      Stage Gate 관련
  infra     인프라 관련

예시:
  feat(cto): create_strategy 메서드 구현
  fix(slm): JSON 파싱 에러 수정
  test(workspace): WorkItem CRUD 단위 테스트 추가
  docs(api): FastAPI 엔드포인트 문서 업데이트
```

### 2.4 테스트 파이프라인

```
테스트 계층 구조
──────────────────────────────────────────────
E2E Tests          1–2개    (전체 시스템 검증)
────────────────────────────────────────────────
Integration Tests  5–10개   (컴포넌트 간 상호작용)
────────────────────────────────────────────────
Unit Tests         50–100개 (개별 클래스/함수)
──────────────────────────────────────────────

단위 테스트 대상:
  tests/agents/test_cto_agent.py         CTO 전략 수립, 작업 분해
  tests/agents/test_slm_agent.py         SLM 코드 생성, 역할별 처리
  tests/collaboration/test_workspace.py  WorkItem CRUD, 상태 전환
  tests/collaboration/test_queue.py      메시지 송수신, Q&A 라우팅
  tests/infrastructure/test_storage.py   SQLite 영속화
  tests/infrastructure/test_ollama.py    Ollama API 연동

통합 테스트 대상:
  tests/integration/test_agent_collab.py   에이전트 간 협업 흐름
  tests/integration/test_dependency.py     의존성 대기 메커니즘
  tests/integration/test_message_flow.py   질문-답변 전체 흐름

E2E 테스트 대상:
  tests/e2e/test_todo_app.py    Todo 앱 전체 생성
  tests/e2e/test_blog_app.py    블로그 앱 전체 생성
```

---

## 3. 시스템 실행 파이프라인

### 3.1 전체 실행 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 1: 입력 처리                                              │
│  ─────────────────────────────────────────────────────────────  │
│  사용자 입력: "실시간 채팅 앱 만들어줘"                           │
│       │                                                          │
│       ▼                                                          │
│  validate_input()                                                │
│    ├── 길이 검증 (10–500자)                                      │
│    ├── 금지어 필터링                                             │
│    └── 언어 감지 및 정규화                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │  검증된 입력
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 2: 전략 수립 (CTO Agent)                                  │
│  ─────────────────────────────────────────────────────────────  │
│  create_strategy_pipeline()                                      │
│    ├── System Prompt 구성 (CTO 역할 지정)                        │
│    ├── LLM 호출 (Llama 3.1 70B via Ollama)                      │
│    │     POST http://localhost:11434/api/chat                    │
│    ├── 응답 JSON 파싱                                            │
│    ├── Strategy 객체 검증                                        │
│    └── 실패 시 최대 3회 재시도 (Retry Logic)                     │
│                                                                  │
│  출력 예시:                                                      │
│  Strategy {                                                      │
│    project_name: "채팅 앱",                                      │
│    tech_stack: { frontend: "React", backend: "FastAPI", ... },  │
│    tasks: [                                                      │
│      Task { id: "ui_chat", role: "frontend", ... },             │
│      Task { id: "api_ws",  role: "backend",  ... },             │
│      Task { id: "docker",  role: "mlops",    ... }              │
│    ]                                                             │
│  }                                                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │  Strategy 객체
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 3: 작업 등록 (WorkSpace)                                  │
│  ─────────────────────────────────────────────────────────────  │
│  register_tasks()                                                │
│    ├── Task → WorkItem 변환                                      │
│    ├── SQLite에 WorkItem 저장 (status: PLANNED)                  │
│    ├── 의존성 그래프 구축                                         │
│    │     ui_chat  ──depends_on──→  api_ws                       │
│    │     docker   ──depends_on──→  api_ws                       │
│    └── 실행 순서 위상 정렬 (Topological Sort)                    │
│                                                                  │
│  실행 순서 결정:                                                  │
│    Level 0 (독립): api_ws (backend)                             │
│    Level 1 (의존): ui_chat (frontend), docker (mlops)           │
└──────────────────────────┬──────────────────────────────────────┘
                           │  정렬된 Task 목록
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 4: 병렬 실행 (SLM Agents)                                 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                  │
│  Level 0 실행:                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Backend Agent                                            │   │
│  │    ├── WorkItem status → IN_PROGRESS                      │   │
│  │    ├── System Prompt: "당신은 FastAPI 전문가입니다..."      │   │
│  │    ├── LLM 호출 (Phi-3.5)                                 │   │
│  │    ├── API 코드 생성                                       │   │
│  │    └── WorkItem status → DONE                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Level 1 병렬 실행 (asyncio.gather):                            │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │  Frontend Agent     │  │  MLOps Agent        │              │
│  │    ├── 의존성 대기   │  │    ├── 의존성 대기   │              │
│  │    │   (api_ws 완료) │  │    │   (api_ws 완료) │              │
│  │    ├── Q&A 처리      │  │    ├── LLM 호출      │              │
│  │    ├── LLM 호출      │  │    ├── Docker 설정   │              │
│  │    └── UI 코드 생성  │  │    └── 완료 표시     │              │
│  └─────────────────────┘  └─────────────────────┘              │
└──────────────────────────┬──────────────────────────────────────┘
                           │  모든 TaskResult
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 5: 결과 생성                                              │
│  ─────────────────────────────────────────────────────────────  │
│  generate_output_pipeline()                                      │
│    ├── 출력 디렉토리 생성                                         │
│    │     outputs/chat-app/                                       │
│    ├── 역할별 파일 저장                                          │
│    │     outputs/chat-app/frontend/ChatWindow.jsx                │
│    │     outputs/chat-app/backend/main.py                       │
│    │     outputs/chat-app/backend/schema.sql                    │
│    │     outputs/chat-app/Dockerfile                            │
│    │     outputs/chat-app/docker-compose.yml                    │
│    ├── README.md 자동 생성                                       │
│    └── 메트릭 기록                                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │  ProjectResult
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 6: 응답 반환                                              │
│  ProjectResult {                                                 │
│    success_rate: 0.87,                                           │
│    total_tasks: 3,                                               │
│    completed_tasks: 3,                                           │
│    output_dir: "outputs/chat-app",                               │
│    duration_minutes: 12.3,                                       │
│    files_generated: 5                                            │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 단계별 시간 예상

| 단계 | 작업 | 예상 시간 |
|------|------|---------|
| Stage 1 | 입력 검증 | < 1초 |
| Stage 2 | CTO 전략 수립 (LLM 호출) | 30–60초 |
| Stage 3 | 작업 등록 및 정렬 | < 1초 |
| Stage 4 | SLM 병렬 실행 (3개 에이전트) | 2–5분 |
| Stage 5 | 파일 생성 | < 5초 |
| **합계** | **전체 프로젝트** | **5–15분** |

---

## 4. 에이전트 협업 파이프라인

### 4.1 정상 협업 시나리오

```
Frontend Agent          Shared Workspace        Backend Agent
     │                        │                       │
     │  create WorkItem(ui)   │                       │
     │───────────────────────>│                       │
     │                        │                       │
     │  (의존성: api 완료 대기)│                       │
     │<- - - - - - - - - - - -│                       │
     │                        │                       │
     │                        │  create WorkItem(api) │
     │                        │<──────────────────────│
     │                        │                       │
     │                        │  update: IN_PROGRESS  │
     │                        │<──────────────────────│
     │                        │                       │
     │                        │  update: DONE         │
     │                        │<──────────────────────│
     │                        │                       │
     │  event: api DONE       │                       │
     │<───────────────────────│                       │
     │                        │                       │
     │  (작업 재개)            │                       │
     │─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ >│                       │
```

### 4.2 질문-답변 (Q&A) 파이프라인

```
Frontend Agent          Message Queue           Backend Agent
     │                        │                       │
     │  needs_info() → true   │                       │
     │                        │                       │
     │  ask("API 엔드포인트?") │                       │
     │───────────────────────>│                       │
     │                        │                       │
     │                        │ find_responder()      │
     │                        │ → keyword: "api"      │
     │                        │ → route to: backend   │
     │                        │                       │
     │                        │  forward question     │
     │                        │──────────────────────>│
     │                        │                       │
     │                        │                       │  답변 생성
     │                        │                       │  (작업 히스토리 참조)
     │                        │                       │
     │                        │  send answer          │
     │                        │<──────────────────────│
     │                        │                       │
     │  receive answer        │                       │
     │<───────────────────────│                       │
     │                        │                       │
     │  context.update(answer)│                       │
     │  → 작업 재개            │                       │
```

### 4.3 블로킹 이슈 처리 파이프라인

```
MLOps Agent           Shared Workspace        Emergency Meeting
     │                        │                       │
     │  update: BLOCKED       │                       │
     │  reason: "포트 충돌"    │                       │
     │───────────────────────>│                       │
     │                        │                       │
     │                        │ detect_blocking()     │
     │                        │ → severity: HIGH      │
     │                        │                       │
     │                        │ summon_emergency()    │
     │                        │──────────────────────>│
     │                        │                       │
     │                        │                       │  관련 에이전트 참여
     │                        │                       │  (Backend, MLOps)
     │                        │                       │
     │                        │                       │  토론 진행
     │                        │                       │  → 결론: 포트 재할당
     │                        │                       │
     │                        │                       │  액션 아이템 생성
     │  action: 포트 변경       │                       │
     │<──────────────────────────────────────────────│
     │                        │                       │
     │  update: IN_PROGRESS   │                       │
     │───────────────────────>│                       │
     │  (작업 재개)            │                       │
```

### 4.4 Stage Gate 회의 파이프라인

```
CTO Agent      Frontend SLM   Backend SLM    MLOps SLM
     │               │               │               │
     │  stage 완료   │               │               │
     │  감지         │               │               │
     │               │               │               │
     │  convene_gate_meeting()                       │
     │──────────────>│               │               │
     │──────────────────────────────>│               │
     │──────────────────────────────────────────────>│
     │               │               │               │
     │               │  review()     │               │
     │               │  (병렬 수집)  │               │
     │               │  review()     │               │
     │               │──────────────>│               │
     │               │  review()     │               │
     │               │──────────────────────────────>│
     │               │               │               │
     │  collect reviews              │               │
     │<──────────────│               │               │
     │<──────────────────────────────│               │
     │<──────────────────────────────────────────────│
     │               │               │               │
     │  synthesize() │               │               │
     │  CTO 종합 결정 │               │               │
     │               │               │               │
     │  decision: PASS / REVISION    │               │
     │  (PASS → 다음 Phase로)         │               │
```

---

## 5. 데이터 플로우 다이어그램

### 5.1 전체 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│                         입력 데이터                              │
│                                                                  │
│  User Input: str                                                 │
│  "실시간 채팅 앱 만들어줘"                                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     CTO Agent 출력                               │
│                                                                  │
│  Strategy: {                                                     │
│    project_name: str,                                            │
│    description: str,                                             │
│    tech_stack: Dict[str, str],                                   │
│    tasks: List[Task]                                             │
│  }                                                               │
│                                                                  │
│  Task: {                                                         │
│    id: str,                                                      │
│    role: "frontend" | "backend" | "mlops",                       │
│    title: str,                                                   │
│    description: str,                                             │
│    dependencies: List[str],                                      │
│    acceptance_criteria: List[str]                                │
│  }                                                               │
└────────────┬─────────────────┬──────────────────────────────────┘
             │                 │
     ┌───────┘                 └───────┐
     ▼                                 ▼
┌───────────────────┐         ┌─────────────────────────────────┐
│   WorkSpace 저장   │         │           SLM 에이전트           │
│                   │         │                                  │
│  WorkItem: {      │         │  execute_task(task) → 호출       │
│    id,            │         │                                  │
│    owner,         │         │  LLM 입력:                       │
│    status,        │◄────────│    system_prompt (역할 정의)     │
│    task,          │         │    user_prompt  (작업 명세)      │
│    result,        │────────►│    context      (의존성 결과)    │
│    dependencies,  │         │                                  │
│    created_at,    │         │  LLM 출력 (Ollama):              │
│    updated_at     │         │    approach: str                 │
│  }                │         │    code: str                     │
│                   │         │    files: List[FileInfo]         │
│  Storage: SQLite  │         │    dependencies: List[str]       │
└───────────────────┘         └──────────────┬───────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         최종 산출물                              │
│                                                                  │
│  ProjectResult: {                                                │
│    project_name: str,                                            │
│    success_rate: float,         # 0.0 ~ 1.0                     │
│    total_tasks: int,                                             │
│    completed_tasks: int,                                         │
│    failed_tasks: int,                                            │
│    output_dir: str,                                              │
│    files_generated: List[str],                                   │
│    duration_seconds: float,                                      │
│    metrics: SystemMetrics                                        │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 LLM 데이터 흐름 (Ollama)

```
에이전트 코드
     │
     │  HTTP POST http://localhost:11434/api/chat
     │
     │  Request Body:
     │  {
     │    "model": "llama3.1:70b",   또는 "phi3.5"
     │    "messages": [
     │      {"role": "system", "content": "당신은 CTO입니다..."},
     │      {"role": "user",   "content": "Todo 앱 전략을 수립하세요..."}
     │    ],
     │    "stream": false,
     │    "options": {
     │      "temperature": 0.7,
     │      "top_p": 0.9
     │    }
     │  }
     ▼
 Ollama Server (localhost:11434)
     │
     │  Response Body:
     │  {
     │    "message": {
     │      "role": "assistant",
     │      "content": "{\"project_name\": \"Todo 앱\", ...}"
     │    },
     │    "done": true,
     │    "total_duration": 45000000000
     │  }
     ▼
 에이전트 응답 파싱 (JSON 추출 및 검증)
```

### 5.3 메시지 플로우

```
에이전트 A                MessageQueue              에이전트 B
  (발신자)                                            (수신자)
     │                        │                       │
     │  ask(question, context)│                       │
     │───────────────────────>│                       │
     │                        │                       │
     │                        │  _find_responder()    │
     │                        │  keywords 분석:        │
     │                        │  "api" → backend      │
     │                        │  "ui"  → frontend     │
     │                        │  "deploy" → mlops     │
     │                        │                       │
     │                        │  send(Message)        │
     │                        │──────────────────────>│
     │                        │                       │
     │                        │                       │  처리
     │                        │  answer               │
     │                        │<──────────────────────│
     │                        │                       │
     │  answer (30s timeout)  │                       │
     │<───────────────────────│                       │
```

---

## 6. CI/CD 파이프라인

### 6.1 GitHub Actions 워크플로우

```
코드 Push / PR 생성
        │
        ▼
┌───────────────────────────────────────────────┐
│  JOB 1: lint                                  │
│  ─────────────────────────────────────────── │
│  ubuntu-latest                                │
│  ├── actions/checkout@v3                      │
│  ├── actions/setup-python@v4 (3.10)           │
│  ├── pip install black flake8 mypy isort      │
│  ├── black --check .     (포맷 검사)           │
│  ├── flake8 .            (린트)               │
│  ├── mypy .              (타입 검사)           │
│  └── isort --check .     (임포트 정렬)        │
└───────────────────┬───────────────────────────┘
                    │ (성공 시)
                    ▼
┌───────────────────────────────────────────────┐
│  JOB 2: test                                  │
│  (needs: lint)                                │
│  ─────────────────────────────────────────── │
│  ubuntu-latest                                │
│  ├── 환경 설정 (Python 3.10)                  │
│  ├── pip install -r requirements*.txt         │
│  ├── pytest tests/agents/ -v                  │
│  ├── pytest tests/collaboration/ -v           │
│  ├── pytest tests/integration/ -v             │
│  ├── pytest --cov=. --cov-report=xml          │
│  └── codecov/codecov-action@v3                │
└───────────────────┬───────────────────────────┘
                    │ (성공 시)
                    ▼
┌───────────────────────────────────────────────┐
│  JOB 3: build                                 │
│  (needs: test)                                │
│  ─────────────────────────────────────────── │
│  ubuntu-latest                                │
│  ├── python setup.py sdist bdist_wheel        │
│  └── Upload Artifacts (dist/)                 │
└───────────────────────────────────────────────┘
```

### 6.2 릴리즈 파이프라인

```
태그 Push (v*.*.*)
        │
        ▼
┌───────────────────────────────────────────────┐
│  Release Workflow                             │
│  ─────────────────────────────────────────── │
│  ├── 전체 테스트 실행                          │
│  ├── 빌드 패키지 생성                          │
│  ├── GitHub Release 생성                       │
│  │     tag_name: v1.0.0                       │
│  │     release_name: Release v1.0.0           │
│  └── 아티팩트 첨부                             │
└───────────────────────────────────────────────┘
```

---

## 7. 모니터링 파이프라인

### 7.1 로그 수집 파이프라인

```
에이전트/시스템 이벤트
        │
        ▼
StructuredLogger.log(level, event, **kwargs)
        │
        │  JSON 형식으로 직렬화:
        │  {
        │    "timestamp": "2026-02-21T14:30:00",
        │    "level": "INFO",
        │    "event": "task_completed",
        │    "task_id": "api_ws",
        │    "agent": "backend",
        │    "duration": 35.2
        │  }
        ▼
logs/system.log (로컬 파일)
        │
        ▼
(선택) 로그 분석 도구 (Phase 8: ELK Stack 또는 Grafana Loki)
```

### 7.2 메트릭 수집 파이프라인

```
실행 시작
  │  SystemMetrics 초기화
  │
  ├── task_started()       → total_tasks += 1
  ├── task_completed()     → completed_tasks += 1, duration 기록
  ├── task_failed()        → failed_tasks += 1
  ├── llm_call()           → llm_calls += 1, tokens 누적
  ├── message_sent()       → messages_sent += 1
  └── question_asked()     → questions_asked += 1
        │
        ▼
SystemMetrics.get_summary()
  {
    success_rate: 0.87,
    total_tasks: 4,
    completed: 4, failed: 0,
    total_time: 720초,
    avg_task_duration: 180초,
    llm_calls: 4,
    llm_tokens: 12500,
    messages: 3
  }
        │
        ▼
CLI Dashboard (rich 라이브러리)
  ┌──────────────────────────────┐
  │ Multi-Agent System Status    │
  ├──────────────┬───────────────┤
  │ Success Rate │ 87.0%         │
  │ Total Tasks  │ 4             │
  │ Completed    │ 4             │
  │ LLM Calls    │ 4             │
  │ Messages     │ 3             │
  └──────────────┴───────────────┘
```

---

## 8. 에러 처리 파이프라인

### 8.1 에러 유형별 처리

```
에러 발생
    │
    ├── LLM JSON 파싱 실패
    │       │
    │       ├── 재시도 횟수 < 3  →  재시도 (지수 백오프)
    │       └── 재시도 횟수 >= 3 →  TaskResult(status=FAILED, error=...)
    │
    ├── LLM 응답 타임아웃 (300초)
    │       │
    │       ├── 재시도 횟수 < 2  →  재시도
    │       └── 재시도 횟수 >= 2 →  더 작은 모델로 폴백 (8B)
    │
    ├── Q&A 타임아웃 (30초)
    │       │
    │       └── 빈 컨텍스트로 작업 진행 (베스트 게스 방식)
    │
    ├── 의존성 데드락 (60초 대기 후)
    │       │
    │       └── 의존성 무시하고 독립 실행 (경고 로그)
    │
    └── 시스템 크래시
            │
            └── 마지막 성공 WorkItem부터 재시작 (SQLite 체크포인트)
```

### 8.2 재시도 로직 (Exponential Backoff)

```
Attempt 1: 즉시 실행
Attempt 2: 2초 대기 후 실행
Attempt 3: 4초 대기 후 실행
Attempt 4: 8초 대기 후 실행 (최대)

실패 시:
  → TaskResult { status: "failed", error: "최대 재시도 초과" }
  → 로그 기록
  → 다음 작업 계속 진행 (부분 성공 허용)
```

---

## 9. 배포 파이프라인

### 9.1 로컬 배포 (MVP)

```
deploy.sh 실행
    │
    ├── 1. make test-fast  (빠른 테스트)
    │
    ├── 2. Ollama 서비스 상태 확인
    │       pgrep ollama || ollama serve &
    │
    ├── 3. 필요 모델 확인
    │       ollama list | grep llama3.1
    │       ollama list | grep phi3.5
    │
    ├── 4. SQLite DB 초기화
    │       python -c "asyncio.run(SQLiteStorage().init())"
    │
    └── 5. 메인 시스템 시작
            python main.py --mode basic
```

### 9.2 Docker 배포 (선택적)

```
docker-compose up --build
    │
    ├── [Service: multi-agent]
    │       FROM python:3.10-slim
    │       COPY requirements.txt + pip install
    │       COPY 소스 코드
    │       CMD ["python", "main.py"]
    │
    │   Volumes:
    │       ./outputs  →  /app/outputs
    │       ./data     →  /app/data
    │
    │   Environment:
    │       OLLAMA_BASE_URL=http://localhost:11434
    │       LOG_LEVEL=INFO
    │
    └── [Network: host]  (Ollama와 로컬 통신)
```

### 9.3 배포 환경별 설정

| 환경 | 설정 | 용도 |
|------|------|------|
| development | LOG_LEVEL=DEBUG, SQLite 인메모리 | 로컬 개발 |
| testing | 모의 LLM, SQLite 임시 파일 | 테스트 자동화 |
| production | LOG_LEVEL=INFO, SQLite 영구 저장, Ollama 실제 모델 | 실운영 |

---

*작성자: 시스템 설계팀 | 검토일: 2026-02-21*

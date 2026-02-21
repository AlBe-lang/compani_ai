# 시스템 아키텍처 설계서
<!-- 기준 문서 (SSOT) — 이 파일이 시스템 아키텍처의 단일 진실 공급원입니다. 변경 시 반드시 개발 일지에 기록하세요. -->

> 버전: v1.0 | 작성일: 2026-02-21 | 상태: 확정

---

## 목차

1. [아키텍처 원칙](#1-아키텍처-원칙)
2. [전체 아키텍처 다이어그램](#2-전체-아키텍처-다이어그램)
3. [4계층 레이어 구조](#3-4계층-레이어-구조)
4. [핵심 컴포넌트 상세 설계](#4-핵심-컴포넌트-상세-설계)
5. [인프라 아키텍처](#5-인프라-아키텍처)
6. [보안 아키텍처](#6-보안-아키텍처)
7. [성능 아키텍처](#7-성능-아키텍처)
8. [확장성 설계](#8-확장성-설계)
9. [Phase별 아키텍처 진화](#9-phase별-아키텍처-진화)
10. [기술 스택 매핑](#10-기술-스택-매핑)

---

## 1. 아키텍처 원칙

### 1.1 설계 원칙

#### SOLID 원칙

| 원칙 | 적용 |
|------|------|
| **S** (단일 책임) | 각 에이전트는 하나의 역할만 담당. CTOAgent는 오케스트레이션만, SimpleSLM은 코드 생성만 |
| **O** (개방-폐쇄) | BaseAgent를 상속하여 새 역할 에이전트를 추가해도 기존 코드 수정 불필요 |
| **L** (리스코프 치환) | SimpleSLM 인스턴스를 BaseAgent 타입으로 교환 가능 |
| **I** (인터페이스 분리) | execute_task() 하나의 핵심 인터페이스만 노출 |
| **D** (의존성 역전) | 에이전트는 구체적인 LLM 구현 대신 OllamaProvider 인터페이스에 의존 |

#### 추가 원칙

- **비동기 우선**: asyncio를 활용한 논블로킹 실행으로 에이전트 병렬 처리
- **느슨한 결합**: 에이전트 간 직접 참조 없이 MessageQueue, WorkSpace를 통한 간접 통신
- **명확한 계약**: Pydantic 모델로 에이전트 간 데이터 인터페이스 명시
- **관심사 분리**: 4계층 레이어 구조로 역할 명확히 분리
- **로컬 우선**: 모든 연산은 로컬에서, 외부 API 의존성 제거

### 1.2 아키텍처 스타일

| 스타일 | 설명 |
|--------|------|
| **이벤트 기반 (Event-Driven)** | 에이전트 간 비동기 메시지 교환, 이벤트 발행/구독 |
| **레이어드 (Layered)** | 4계층 명확히 분리 (Orchestration → Execution → Collaboration → Infrastructure) |
| **에이전트 기반 (Agent-Based)** | 자율적 에이전트들이 협력하여 목표 달성 |
| **파이프라인 (Pipeline)** | 입력 → 전략 → 실행 → 협업 → 출력의 명확한 처리 흐름 |

---

## 2. 전체 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           사용자 인터페이스                                   │
│                                                                               │
│    CLI: python main.py --project "Todo 앱"                                   │
│    (Future: Flutter Web CEO 대시보드)                                         │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        오케스트레이션 계층 (Orchestration Layer)              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    CTO Agent (Llama 3.1 70B)                          │  │
│  │                                                                       │  │
│  │  create_strategy()   decompose_tasks()   delegate_task()              │  │
│  │  orchestrate()       monitor_progress()  finalize()                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │  작업 분배
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         실행 계층 (Execution Layer)                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│  │  Frontend SLM   │  │  Backend SLM    │  │  MLOps SLM      │            │
│  │  (Phi-3.5 3.8B) │  │  (Phi-3.5 3.8B) │  │(Llama 3.2 3B)  │            │
│  │                 │  │                 │  │                 │            │
│  │ execute_task()  │  │ execute_task()  │  │ execute_task()  │            │
│  │ get_sys_prompt()│  │ get_sys_prompt()│  │ get_sys_prompt()│            │
│  │ _ask_question() │  │ _ask_question() │  │ _ask_question() │            │
│  │ _wait_deps()    │  │ _wait_deps()    │  │ _wait_deps()    │            │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘            │
└───────────┼──────────────────────────────────────────┼─────────────────────┘
            │                                          │
            └────────────────────┬─────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       협업 계층 (Collaboration Layer)                         │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐   │
│  │   SharedWorkspace  │  │   MessageQueue     │  │     EventBus       │   │
│  │                    │  │                    │  │                    │   │
│  │ add(WorkItem)      │  │ send(Message)      │  │ subscribe(event)   │   │
│  │ update(WorkItem)   │  │ ask(question)      │  │ publish(event)     │   │
│  │ get(id)            │  │ find_responder()   │  │ notify(agents)     │   │
│  │ subscribe(event)   │  │ route_message()    │  │                    │   │
│  │ detect_blocking()  │  │                    │  │                    │   │
│  └────────────────────┘  └────────────────────┘  └────────────────────┘   │
│                                                                              │
│  [Phase 4+]                  [Phase 5+]               [Phase 6+]            │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐   │
│  │  KnowledgeGraph    │  │  StageGateManager  │  │  EvolutionEngine   │   │
│  │  (에이전트 전문성)   │  │  (집단 지성 검증)   │  │  (DNA 진화)        │   │
│  └────────────────────┘  └────────────────────┘  └────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       인프라 계층 (Infrastructure Layer)                      │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐   │
│  │   OllamaProvider   │  │   SQLiteStorage    │  │   FileSystem       │   │
│  │                    │  │                    │  │                    │   │
│  │ generate(model,    │  │ save(WorkItem)     │  │ save_file()        │   │
│  │   messages)        │  │ load(id)           │  │ create_dir()       │   │
│  │ health_check()     │  │ query(sql)         │  │ generate_readme()  │   │
│  │                    │  │                    │  │                    │   │
│  │ http://localhost:  │  │ workspace.db       │  │ outputs/           │   │
│  │   11434/api/chat   │  │ (로컬 SQLite)      │  │ (로컬 파일 시스템)   │   │
│  └────────────────────┘  └────────────────────┘  └────────────────────┘   │
│                                                                              │
│  [Phase 3+: Redis]           [Phase 2+: Vector DB]                          │
│  ┌────────────────────┐  ┌────────────────────┐                            │
│  │   RedisCache       │  │   VectorStore      │                            │
│  │   (실시간 상태)     │  │   (Qdrant, 임베딩)  │                            │
│  └────────────────────┘  └────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 4계층 레이어 구조

### 3.1 오케스트레이션 계층 (Orchestration Layer)

**목적**: 프로젝트 전체 기획, 작업 분배, 진행 모니터링

**구성 요소**:
- `CTOAgent` — Llama 3.1 70B 기반, 전략 수립 및 조율
- `ProjectOrchestrator` — 전체 실행 흐름 관리

**책임**:
- 자연어 입력을 구조화된 Strategy로 변환
- 작업을 최적의 에이전트에게 할당
- Stage Gate 회의 주관 (Phase 5+)
- 전체 진행 상황 모니터링 및 최종 결과 집계

**다른 계층과의 인터페이스**:
- → 실행 계층: Task 객체 전달
- → 협업 계층: WorkSpace에 WorkItem 등록
- ← 실행 계층: TaskResult 수신

---

### 3.2 실행 계층 (Execution Layer)

**목적**: 역할별 전문 코드 생성 및 실행

**구성 요소**:
- `BaseAgent` (추상) — 공통 LLM 호출, 이력 저장
- `SimpleSLM` — 역할별 코드 생성 (Frontend / Backend / MLOps)

**책임**:
- 역할에 특화된 System Prompt 적용
- Task를 실행 가능한 코드로 변환
- 의존성 대기 및 협업 Q&A 처리
- WorkItem 상태 업데이트

**다른 계층과의 인터페이스**:
- ← 오케스트레이션: Task 수신
- ↕ 협업 계층: WorkSpace 읽기/쓰기, 메시지 송수신
- → 인프라 계층: LLM 호출, DB 저장

---

### 3.3 협업 계층 (Collaboration Layer)

**목적**: 에이전트 간 실시간 협업 지원

**구성 요소**:
- `SharedWorkspace` — 작업 상태 공유 및 이벤트 브로드캐스트
- `MessageQueue` — 에이전트 간 비동기 Q&A 라우팅
- `EventBus` — 이벤트 발행/구독 (관찰자 패턴)
- `KnowledgeGraph` (Phase 4+) — 에이전트 전문성 추적
- `StageGateManager` (Phase 5+) — 집단 지성 회의 관리
- `EvolutionEngine` (Phase 6+) — DNA 기반 에이전트 진화

**다른 계층과의 인터페이스**:
- ← 실행 계층: WorkItem 업데이트, 메시지 발송
- → 인프라 계층: DB 저장/조회, 캐시 읽기/쓰기

---

### 3.4 인프라 계층 (Infrastructure Layer)

**목적**: 외부 시스템 연동 및 영속화

**구성 요소**:
- `OllamaProvider` — Ollama API HTTP 클라이언트
- `SQLiteStorage` — 로컬 SQLite DB CRUD
- `FileSystem` — 생성된 코드 파일 저장
- `RedisCache` (Phase 3+) — 실시간 상태 캐시
- `VectorStore` (Phase 4+) — Qdrant 벡터 DB

---

## 4. 핵심 컴포넌트 상세 설계

### 4.1 CTOAgent

```
CTOAgent
├── 속성
│   ├── model: "llama3.1:70b"
│   ├── ollama_url: str
│   ├── workspace: SharedWorkspace
│   └── team: Dict[str, BaseAgent]
│
├── create_strategy(idea: str) → Strategy
│   ├── System Prompt: "당신은 경험 많은 CTO입니다..."
│   ├── 입력: 자연어 프로젝트 아이디어
│   ├── LLM 호출 → JSON 응답
│   └── 출력: Strategy { project_name, tech_stack, tasks }
│
├── decompose_tasks(strategy: Strategy) → List[Task]
│   ├── 각 작업에 ID 부여 (project_id + role + seq)
│   ├── 역할 할당 (frontend/backend/mlops)
│   ├── 의존성 분석 및 설정
│   └── 출력: List[Task]
│
├── delegate_task(task: Task) → TaskResult
│   ├── task.role로 적절한 SLM 찾기
│   ├── agent.execute_task(task) 호출
│   └── 결과 반환
│
└── orchestrate_project(idea: str) → ProjectResult
    ├── create_strategy()
    ├── decompose_tasks()
    ├── WorkSpace에 WorkItem 등록
    ├── asyncio.gather(*[delegate_task(t) for t in tasks])
    └── 결과 집계 및 파일 생성
```

---

### 4.2 BaseAgent (추상 클래스)

```
BaseAgent (ABC)
├── 속성
│   ├── name: str
│   ├── role: str
│   ├── model: str
│   ├── ollama_url: str
│   └── task_history: List[Dict]
│
├── call_llm(prompt, system_prompt, **kwargs) → str
│   ├── messages = [{"role": "system", ...}, {"role": "user", ...}]
│   ├── POST {ollama_url}/api/chat
│   ├── timeout: 300초
│   └── 응답 파싱 및 반환
│
├── execute_task(task: Task) → TaskResult  [abstractmethod]
│   └── 하위 클래스에서 구현
│
└── save_task_history(task, result)
    └── task_history에 기록 (메모리 + DB)
```

---

### 4.3 SimpleSLM

```
SimpleSLM (BaseAgent 상속)
├── 속성 (추가)
│   ├── role: "frontend" | "backend" | "mlops"
│   ├── workspace: SharedWorkspace
│   └── message_queue: MessageQueue
│
├── execute_task(task: Task) → TaskResult
│   ├── 1. WorkItem 생성 및 WorkSpace 등록
│   │       work_item.status = PLANNED → IN_PROGRESS
│   │
│   ├── 2. _wait_dependencies(task.dependencies)
│   │       while dep.status != DONE: await asyncio.sleep(1)
│   │
│   ├── 3. _check_needs_info(task) → bool
│   │       confidence_score < 0.6 → Q&A 필요
│   │
│   ├── 4. _ask_question(question) → answer
│   │       message_queue.ask(from=self.role, question, context)
│   │
│   ├── 5. _build_prompt(task, context) → prompt
│   │       역할별 템플릿 + 작업 명세 + 컨텍스트 정보
│   │
│   ├── 6. call_llm(prompt, get_system_prompt())
│   │       Ollama API 호출
│   │
│   ├── 7. _parse_response(raw) → TaskResult
│   │       JSON 추출, 코드 파싱, 파일 목록 구성
│   │
│   └── 8. work_item.status → DONE
│           WorkSpace 업데이트 → 이벤트 발행
│
├── get_system_prompt() → str
│   ├── frontend: "당신은 React/Flutter 전문 개발자입니다..."
│   ├── backend:  "당신은 FastAPI/SQLAlchemy 전문가입니다..."
│   └── mlops:    "당신은 Docker/Kubernetes 전문가입니다..."
│
└── _parse_response(raw: str) → TaskResult
    ├── JSON 블록 추출 (```json ... ```)
    ├── Pydantic 모델 파싱 및 검증
    └── 실패 시 재시도 (최대 3회)
```

---

### 4.4 SharedWorkspace

```
SharedWorkspace
├── 속성
│   ├── storage: SQLiteStorage
│   ├── items: Dict[str, WorkItem]   ← 인메모리 캐시
│   └── subscribers: Dict[str, List[Callable]]
│
├── add(item: WorkItem)
│   ├── items[item.id] = item
│   ├── storage.save(item)
│   └── _notify('item_added', item)
│
├── update(item: WorkItem)
│   ├── items[item.id] = item
│   ├── item.updated_at = now()
│   ├── storage.update(item)
│   └── _notify('item_updated', item)
│
├── get(item_id: str) → Optional[WorkItem]
│   ├── items에서 먼저 확인 (O(1))
│   └── 없으면 storage.load(item_id)
│
├── subscribe(event_type: str, callback: Callable)
│   └── subscribers[event_type].append(callback)
│
├── detect_blocking() → List[WorkItem]
│   └── status == 'blocked' 항목 감지
│
└── _notify(event_type: str, item: WorkItem)
    └── 구독된 모든 콜백 비동기 호출
```

---

### 4.5 MessageQueue

```
MessageQueue
├── 속성
│   ├── queues: Dict[str, asyncio.Queue]  ← 에이전트별 큐
│   └── history: List[Message]
│
├── register_agent(role: str)
│   └── queues[role] = asyncio.Queue()
│
├── send(from_role, to_role, message_type, content)
│   ├── Message 객체 생성
│   ├── queues[to_role].put(msg)
│   └── history.append(msg)
│
├── ask(from_agent, question, context) → str
│   ├── to_agent = _find_responder(question, context)
│   ├── send(from_agent, to_agent, 'question', {...})
│   ├── asyncio.wait_for(queues[from_agent].get(), timeout=30)
│   └── answer_msg.content['answer']
│
└── _find_responder(question, context) → str
    ├── 키워드 기반 라우팅
    │   "api", "database", "sql" → backend
    │   "ui", "component", "css" → frontend
    │   "deploy", "docker", "k8s" → mlops
    └── 지식 그래프 기반 라우팅 (Phase 4+)
```

---

### 4.6 OllamaProvider

```
OllamaProvider
├── 속성
│   ├── base_url: "http://localhost:11434"
│   └── session: aiohttp.ClientSession
│
├── generate(model, messages, **kwargs) → str
│   ├── POST {base_url}/api/chat
│   │   Body: {model, messages, stream: false, options: {temperature, top_p}}
│   ├── timeout: 300초
│   └── data['message']['content'] 반환
│
└── health_check() → bool
    └── GET {base_url}/api/tags → 모델 목록 확인
```

---

### 4.7 AgentDNA (Phase 6+)

```
AgentDNA
├── genes: Dict[str, float]  ← 10개 유전자 (0.0 ~ 1.0)
│   creativity, precision, speed, collaboration,
│   learning_rate, risk_taking, debugging_skill,
│   innovation, code_quality, documentation
│
├── to_system_prompt_modifier() → str
│   ├── creativity > 0.7  → "창의적이고 혁신적인 접근을 선호합니다"
│   ├── precision > 0.8   → "정확성을 최우선으로 합니다"
│   └── collaboration > 0.7 → "자주 소통하고 피드백을 요청합니다"
│
├── to_generation_params() → Dict
│   ├── creativity 높음 → temperature 증가
│   └── precision 높음  → temperature 감소
│
└── EvolutionEngine
    ├── enhance(gene, delta)     성공한 유전자 강화
    ├── mutate(gene)             성능 낮은 유전자 무작위 변이
    └── crossover(dna_a, dna_b) 우수 에이전트 DNA 교배
```

---

## 5. 인프라 아키텍처

### 5.1 하드웨어 구성

```
┌─────────────────────────────────────────────────────────────┐
│                   Mac Mini M4 16GB                           │
│                                                               │
│  메모리 할당 계획:                                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  CTO Agent (Llama 3.1 70B 4bit)  ≈ 10GB             │   │
│  │  Frontend SLM (Phi-3.5 3.8B)     ≈  2GB             │   │
│  │  Backend SLM  (Phi-3.5 3.8B)     ≈  2GB             │   │
│  │  MLOps SLM    (Llama 3.2 3B)     ≈  1.5GB           │   │
│  │  시스템 + Python + SQLite         ≈  1GB             │   │
│  │  ─────────────────────────────────────────────────   │   │
│  │  합계                             ≈ 16.5GB           │   │
│  │  → SWAP 사용 또는 on-demand 로드로 해결               │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  최적화 전략:                                                 │
│  - 모델 순차 로드 (필요할 때만 메모리에 올림)                  │
│  - CTO 작업 완료 후 SLM 작업 시 CTO 모델 언로드 고려          │
│  - 4bit 양자화 필수 적용                                      │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 소프트웨어 스택

```
┌─────────────────────────────────────────────────────────────┐
│  애플리케이션 계층                                            │
│  Python 3.10+  │  asyncio  │  Pydantic  │  aiohttp          │
├─────────────────────────────────────────────────────────────┤
│  LLM 실행 계층                                               │
│  Ollama (로컬 LLM 서버)                                      │
│  ├── llama3.1:70b  (CTO 에이전트)                            │
│  ├── phi3.5        (Frontend / Backend SLM)                  │
│  └── llama3.2:3b   (MLOps SLM)                              │
├─────────────────────────────────────────────────────────────┤
│  데이터 저장 계층                                             │
│  MVP:    SQLite (workspace.db)                               │
│  Phase3: SQLite + Redis (실시간 상태 캐시)                    │
│  Phase4: SQLite + Redis + Qdrant (벡터 DB)                   │
├─────────────────────────────────────────────────────────────┤
│  운영 체계                                                    │
│  macOS Sequoia  │  Apple Silicon M4  │  Docker (선택)        │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 프로세스 구성

```
프로세스 토폴로지:

[Process 1] ollama serve               (포트 11434)
  │  Llama 3.1 70B 모델 서빙
  │  Phi-3.5 모델 서빙
  └  Llama 3.2 3B 모델 서빙

[Process 2] python main.py             (메인 프로세스)
  ├── asyncio Event Loop
  │   ├── CTOAgent 코루틴
  │   ├── Frontend SLM 코루틴
  │   ├── Backend SLM 코루틴
  │   └── MLOps SLM 코루틴
  └── SQLite 연결 (workspace.db)

[선택: Phase 3+]
[Process 3] redis-server               (포트 6379)
[Process 4] qdrant                     (포트 6333)
```

---

## 6. 보안 아키텍처

### 6.1 완전 폐쇄망 설계

```
인터넷
  │
  X  ← 차단 (외부 통신 불필요)
  │
┌─┴──────────────────────────────────────────────────────────┐
│                   Mac Mini (로컬 네트워크)                    │
│                                                               │
│  [Ollama]          localhost:11434                           │
│  [SQLite]          /data/workspace.db (로컬 파일)            │
│  [Redis]           localhost:6379 (Phase 3+)                 │
│  [Qdrant]          localhost:6333 (Phase 4+)                 │
│  [Python App]      주 프로세스                               │
│                                                               │
│  ─────────────────────────────────────────────────────────  │
│  외부로 나가는 데이터: 없음 (Zero external data transfer)     │
│  API 키 불필요: 없음                                          │
│  네트워크 요청 없음: 완전 오프라인 가능                        │
└────────────────────────────────────────────────────────────┘
```

### 6.2 데이터 보안

| 항목 | 방법 |
|------|------|
| 코드 데이터 | 로컬 SQLite, 외부 유출 없음 |
| LLM 추론 | Ollama 로컬 실행, API 호출 없음 |
| 생성 파일 | 로컬 outputs/ 디렉토리 |
| 로그 | 로컬 logs/ 디렉토리 |
| 설정 정보 | .env 파일 (gitignore에 포함) |

### 6.3 입력 검증

```python
# 사용자 입력 검증 (인젝션 방지)
def validate_user_input(idea: str) -> str:
    # 길이 제한
    if not 10 <= len(idea) <= 500:
        raise ValueError("입력 길이 오류")
    # 특수 프롬프트 인젝션 패턴 필터링
    injection_patterns = ["ignore previous", "system:", "assistant:"]
    for pattern in injection_patterns:
        if pattern.lower() in idea.lower():
            raise SecurityError("비허용 패턴 감지")
    return idea.strip()
```

---

## 7. 성능 아키텍처

### 7.1 비동기 병렬 처리

```python
# 독립적인 작업을 병렬 실행
async def execute_parallel(independent_tasks: List[Task]):
    results = await asyncio.gather(*[
        agent_pool[task.role].execute_task(task)
        for task in independent_tasks
    ])
    return results

# 의존성 있는 작업은 순차 실행
async def execute_with_dependencies(ordered_levels):
    all_results = []
    for level in ordered_levels:
        level_results = await execute_parallel(level)  # 같은 레벨은 병렬
        all_results.extend(level_results)
    return all_results
```

### 7.2 응답 시간 목표

| 구성 요소 | 목표 응답 시간 |
|---------|-------------|
| 입력 검증 | < 10ms |
| CTO 전략 수립 (LLM 70B) | 30–60초 |
| SLM 코드 생성 (LLM 3.8B) | 20–40초/작업 |
| Q&A 처리 | 5–15초 (LLM 응답 포함) |
| WorkSpace 조회 | < 1ms (인메모리) |
| DB 저장 | < 5ms (SQLite) |
| 파일 생성 | < 100ms |
| **전체 프로젝트 (4개 작업)** | **5–15분** |

### 7.3 메모리 최적화 전략

```
전략 1: On-demand 모델 로딩
  → CTO 작업 후 Llama 70B 언로드 검토
  → SLM만 상주 (약 5.5GB)

전략 2: 스트리밍 응답 처리 (Phase 2+)
  → stream: true로 LLM 응답 받기
  → 응답 시작부터 파싱 가능

전략 3: 결과 캐싱
  → 동일한 Task 유형 재발생 시 캐시 활용
  → Redis 기반 (Phase 3+)

전략 4: 배치 처리
  → 여러 프로젝트 동시 처리 (Phase 8)
  → 에이전트 풀 관리
```

### 7.4 성능 모니터링

```python
@dataclass
class PerformanceMetrics:
    # LLM 성능
    llm_avg_latency_sec: float      # 평균 LLM 응답 시간
    llm_tokens_per_sec: float       # 초당 토큰 생성 속도
    llm_error_rate: float           # LLM 오류율

    # 시스템 성능
    task_completion_rate: float     # 작업 완료율
    avg_task_duration_sec: float    # 평균 작업 소요 시간
    collaboration_success_rate: float  # Q&A 성공률

    # 리소스 사용
    memory_usage_gb: float          # 메모리 사용량
    cpu_usage_percent: float        # CPU 사용률
```

---

## 8. 확장성 설계

### 8.1 새 에이전트 추가

```python
# 1. SimpleSLM 상속
class DesignerAgent(SimpleSLM):
    def __init__(self, **kwargs):
        super().__init__(role='designer', **kwargs)

    def get_system_prompt(self) -> str:
        return """당신은 UI/UX 디자인 전문가입니다.
        Figma 컴포넌트 설계, 색상 시스템, 타이포그래피를 담당합니다."""

# 2. CTOAgent 팀에 등록
cto.add_team_member('designer', DesignerAgent(
    name="Designer SLM",
    model="phi3.5",
    ollama_url=config.OLLAMA_URL,
    workspace=shared_workspace,
    message_queue=message_queue
))

# 3. 작업 분배 로직 자동 확인 (role='designer' → DesignerAgent)
```

### 8.2 새 LLM 모델 교체

```python
# config.yaml에서 모델 변경만으로 교체 가능
agents:
  cto:
    model: "llama3.1:70b"     # 또는 "llama3.3:70b", "qwen2.5:72b"
  frontend:
    model: "phi3.5"           # 또는 "phi4", "gemma2:9b"
  backend:
    model: "phi3.5"
  mlops:
    model: "llama3.2:3b"      # 또는 "phi3.5:3.8b"
```

### 8.3 플러그인 구조 (Phase 8+)

```
plugin_interface.py
  └── class AgentPlugin(ABC):
        @abstractmethod
        def pre_execute(task: Task) → Task      # 전처리 후크
        @abstractmethod
        def post_execute(result: TaskResult) → TaskResult  # 후처리 후크

plugins/
  ├── security_scanner.py     # 코드 보안 취약점 스캔
  ├── code_formatter.py       # 생성 코드 자동 포맷팅
  ├── test_generator.py       # 자동 테스트 코드 생성
  └── doc_generator.py        # API 문서 자동 생성
```

---

## 9. Phase별 아키텍처 진화

### Phase 1 — MVP 기본 (현재 단계)

```
[단순 아키텍처]

User → CTOAgent → [Frontend, Backend, MLOps] SLM
                              │
                         SQLiteStorage
                              │
                         FileSystem (outputs/)
```

### Phase 3 — 실시간 협업 추가

```
[협업 아키텍처]

User → CTOAgent → SharedWorkspace ← → SLMs (병렬)
                       │      │
                  EventBus  MessageQueue
                       │      │
                  SQLite   Redis (실시간 상태)
```

### Phase 5 — Stage Gate 추가

```
[검증 아키텍처]

User → CTOAgent → SLMs → SharedWorkspace
                              │
                    StageGateMeeting (단계별 검증)
                              │
                    [통과] → 다음 단계
                    [재작업] → SLMs 재실행
```

### Phase 6 — DNA 진화 추가

```
[진화 아키텍처]

User → CTOAgent → SLMs (DNA 기반 행동)
                        │
               EvolutionEngine
                  │         │
              Enhance    Mutate/Crossover
                  │         │
              AgentDNA  업데이트
                  │
               다음 프로젝트에 적용
```

### Phase 8 — 완성형 (최종)

```
[완성 아키텍처]

CEO Dashboard (Flutter Web)
        │
        │ WebSocket
        ▼
CTOAgent (오케스트레이터)
    │        │         │
    ▼        ▼         ▼
Frontend  Backend   MLOps
  SLM      SLM       SLM
    │        │         │
    └────────┼─────────┘
             │
      SharedWorkspace (Redis 기반)
      MessageQueue (Redis Pub/Sub)
      KnowledgeGraph
      StageGateManager
      EvolutionEngine
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
  SQLite   Redis   Qdrant
 (영속화)  (캐시)   (벡터)
             │
          FileSystem (outputs/)
```

---

## 10. 기술 스택 매핑

### 10.1 전체 기술 스택

| 계층 | 기술 | 버전 | 역할 |
|------|------|------|------|
| 언어 | Python | 3.10+ | 메인 개발 언어 |
| 비동기 | asyncio | stdlib | 에이전트 병렬 처리 |
| LLM 런타임 | Ollama | latest | 로컬 LLM 서빙 |
| CTO 모델 | Llama 3.1 | 70B (4bit) | 전략 수립 및 오케스트레이션 |
| SLM 모델 | Phi-3.5 | 3.8B | Frontend/Backend 코드 생성 |
| SLM 모델 | Llama 3.2 | 3B | MLOps 설정 생성 |
| HTTP 클라이언트 | aiohttp | ≥ 3.9 | Ollama API 비동기 호출 |
| 데이터 모델 | Pydantic | ≥ 2.0 | 데이터 검증 및 직렬화 |
| 로컬 DB | SQLite | stdlib | WorkItem, 프로젝트 영속화 |
| 캐시 | Redis | 7.x (Phase 3+) | 실시간 상태 공유 |
| 벡터 DB | Qdrant | latest (Phase 4+) | 지식 그래프 임베딩 |
| 파인튜닝 | Unsloth | latest (Phase 2+) | LoRA 기반 SLM 특화 학습 |
| 임베딩 | Sentence-Transformers | latest (Phase 4+) | 로컬 텍스트 임베딩 |
| API | FastAPI | ≥ 0.100 (Phase 8+) | CEO 대시보드 백엔드 |
| UI | Flutter Web | 3.x (Phase 8+) | CEO 대시보드 프론트엔드 |
| 컨테이너 | Docker | latest (선택) | 배포 패키징 |
| CI/CD | GitHub Actions | latest | 자동화 테스트/빌드 |
| 코드 품질 | Black + Flake8 + MyPy | latest | 코드 포맷팅/린팅/타입 검사 |
| 테스트 | pytest + pytest-asyncio | ≥ 7.4 | 자동화 테스트 |
| CLI 대시보드 | rich | ≥ 13.0 | 터미널 실시간 모니터링 |

### 10.2 Phase별 기술 도입 시점

| 기술 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5+ |
|------|---------|---------|---------|---------|---------|
| Python + asyncio | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ollama (Llama, Phi) | ✅ | ✅ | ✅ | ✅ | ✅ |
| SQLite | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pydantic + aiohttp | ✅ | ✅ | ✅ | ✅ | ✅ |
| Unsloth (파인튜닝) | - | ✅ | ✅ | ✅ | ✅ |
| Redis | - | - | ✅ | ✅ | ✅ |
| Qdrant + Embeddings | - | - | - | ✅ | ✅ |
| FastAPI (대시보드) | - | - | - | - | ✅ |
| Flutter Web | - | - | - | - | ✅ |

---

*작성자: 시스템 설계팀 | 검토일: 2026-02-21 | 다음 검토: Phase 1 완료 후*

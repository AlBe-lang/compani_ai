# ERD (Entity Relationship Diagram)

> 버전: v1.0 | 작성일: 2026-02-21 | 상태: 확정

---

## 목차

1. [ERD 개요](#1-erd-개요)
2. [전체 ERD (ASCII)](#2-전체-erd-ascii)
3. [엔티티 상세 정의](#3-엔티티-상세-정의)
4. [관계 정의](#4-관계-정의)
5. [데이터베이스 스키마 (DDL)](#5-데이터베이스-스키마-ddl)
6. [인덱스 전략](#6-인덱스-전략)
7. [데이터 흐름 예시](#7-데이터-흐름-예시)

---

## 1. ERD 개요

### 1.1 데이터베이스 구성

| 저장소 | 용도 | 엔티티 |
|--------|------|--------|
| SQLite (workspace.db) | 작업 상태, 프로젝트 영속화 | Project, Task, WorkItem, TaskResult, Message |
| SQLite (agent.db) | 에이전트 상태, DNA, 히스토리 | Agent, AgentDNA, AgentTaskHistory |
| SQLite (meeting.db) | 회의 기록, 결정사항 | StageGateMeeting, MeetingReview, KnowledgeNode |
| SQLite (metrics.db) | 시스템 메트릭, 로그 | SystemMetrics, LogEntry |

> **참고**: MVP 단계에서는 단일 `workspace.db`에 모든 테이블 통합 관리. Phase 3 이후 확장 가능성을 위해 논리적으로 분리 설계.

### 1.2 핵심 엔티티 목록

| 번호 | 엔티티 | 설명 |
|------|--------|------|
| 1 | Project | 생성된 소프트웨어 프로젝트 |
| 2 | Task | 프로젝트 내 개별 작업 단위 |
| 3 | WorkItem | 에이전트가 실행하는 작업 인스턴스 |
| 4 | TaskResult | 작업 실행 결과 (생성된 코드 포함) |
| 5 | Agent | AI 에이전트 (CTO, Frontend, Backend, MLOps) |
| 6 | AgentDNA | 에이전트 행동 특성 유전자 |
| 7 | AgentTaskHistory | 에이전트 작업 이력 |
| 8 | Message | 에이전트 간 통신 메시지 |
| 9 | StageGateMeeting | Stage Gate 검증 회의 |
| 10 | MeetingReview | 회의 내 개별 에이전트 리뷰 |
| 11 | KnowledgeNode | 에이전트 전문성 지식 그래프 노드 |
| 12 | SystemMetrics | 프로젝트 실행 메트릭 |

---

## 2. 전체 ERD (ASCII)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                          멀티 에이전트 시스템 ERD                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────────┐        1         N  ┌────────────────────┐
│      Project       │──────────────────────│       Task         │
├────────────────────┤                      ├────────────────────┤
│ PK  id             │                      │ PK  id             │
│     name           │                      │ FK  project_id     │
│     description    │                      │     role           │
│     status         │                      │     title          │
│     tech_stack_json│                      │     description    │
│     created_at     │                      │     acceptance_json│
│     completed_at   │                      │     priority       │
│     output_dir     │                      │     created_at     │
└────────────────────┘                      └──────────┬─────────┘
                                                        │ 1
                                                        │
                                                        │ 1
                                            ┌──────────▼─────────┐        1         1  ┌────────────────────┐
                                            │      WorkItem      │──────────────────────│    TaskResult      │
                                            ├────────────────────┤                      ├────────────────────┤
                                            │ PK  id             │                      │ PK  id             │
                                            │ FK  task_id        │                      │ FK  work_item_id   │
                                            │ FK  agent_id       │                      │     status         │
                                            │     status         │                      │     approach       │
                                            │     dependencies   │                      │     code_json      │
                                            │     created_at     │                      │     files_json     │
                                            │     updated_at     │                      │     error_message  │
                                            │     started_at     │                      │     duration_sec   │
                                            │     completed_at   │                      │     created_at     │
                                            └──────────┬─────────┘                      └────────────────────┘
                                                        │ N
                                                        │
              ┌─────────────────────────────────────────┘
              │ 1
┌─────────────▼──────────┐
│        Agent           │
├────────────────────────┤
│ PK  id                 │
│     name               │
│     role               │──────────────────────────────────────────┐
│     model_name         │                                          │ 1
│     ollama_url         │                                          │
│     system_prompt      │                             ┌────────────▼───────────┐
│     is_active          │                             │      AgentDNA          │
│     created_at         │                             ├────────────────────────┤
└────────────────────────┘                             │ PK  id                 │
          │ 1                                          │ FK  agent_id (UNIQUE)  │
          │                                            │     creativity         │
          │ N                                          │     precision          │
┌─────────▼──────────────┐                             │     speed              │
│   AgentTaskHistory     │                             │     collaboration      │
├────────────────────────┤                             │     learning_rate      │
│ PK  id                 │                             │     risk_taking        │
│ FK  agent_id           │                             │     debugging_skill    │
│ FK  task_id            │                             │     innovation         │
│     success            │                             │     code_quality       │
│     duration_sec       │                             │     documentation      │
│     quality_score      │                             │     version            │
│     created_at         │                             │     updated_at         │
└────────────────────────┘                             └────────────────────────┘

┌────────────────────┐
│      Message       │
├────────────────────┤
│ PK  id             │
│ FK  from_agent_id  │───────────────────┐
│ FK  to_agent_id    │───────────────┐   │
│ FK  work_item_id   │(nullable)     │   │  참조: Agent(id)
│     message_type   │               │   │
│     content        │               │   │
│     status         │               └───┘
│     created_at     │
│     answered_at    │
└────────────────────┘

┌────────────────────────┐         1         N   ┌────────────────────┐
│   StageGateMeeting     │────────────────────────│   MeetingReview    │
├────────────────────────┤                        ├────────────────────┤
│ PK  id                 │                        │ PK  id             │
│ FK  project_id         │                        │ FK  meeting_id     │
│     stage_name         │                        │ FK  agent_id       │
│     status             │                        │     content        │
│     decision           │                        │     vote           │
│     summary            │                        │     concerns_json  │
│     action_items_json  │                        │     created_at     │
│     started_at         │                        └────────────────────┘
│     completed_at       │
└────────────────────────┘

┌────────────────────────┐
│    KnowledgeNode       │
├────────────────────────┤
│ PK  id                 │
│ FK  agent_id           │
│     keyword            │
│     domain             │
│     expertise_level    │
│     source_task_id     │
│     created_at         │
└────────────────────────┘

┌────────────────────────┐
│    SystemMetrics       │
├────────────────────────┤
│ PK  id                 │
│ FK  project_id         │
│     total_tasks        │
│     completed_tasks    │
│     failed_tasks       │
│     llm_calls          │
│     llm_total_tokens   │
│     messages_sent      │
│     questions_asked    │
│     total_duration_sec │
│     success_rate       │
│     created_at         │
└────────────────────────┘
```

---

## 3. 엔티티 상세 정의

### 3.1 Project (프로젝트)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| name | TEXT | NOT NULL | 프로젝트 이름 |
| description | TEXT | | 프로젝트 상세 설명 |
| status | TEXT | NOT NULL | `planning` / `in_progress` / `completed` / `failed` |
| tech_stack_json | TEXT | | JSON: {"frontend": "React", "backend": "FastAPI", ...} |
| user_input | TEXT | NOT NULL | 원본 사용자 입력 |
| output_dir | TEXT | | 생성 파일 저장 경로 |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |
| completed_at | TEXT | | 완료 시각 (완료 시에만 값) |

**상태 전이**:
```
planning → in_progress → completed
                      └→ failed
```

---

### 3.2 Task (작업)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | "{project_id}_{role}_{sequence}" |
| project_id | TEXT | FK → Project.id | 소속 프로젝트 |
| role | TEXT | NOT NULL | `cto` / `frontend` / `backend` / `mlops` |
| title | TEXT | NOT NULL | 작업 제목 |
| description | TEXT | NOT NULL | 작업 상세 명세 |
| acceptance_json | TEXT | | JSON: List[str] — 완료 기준 목록 |
| dependencies_json | TEXT | | JSON: List[str] — 선행 Task ID 목록 |
| priority | INTEGER | DEFAULT 0 | 우선순위 (낮을수록 높음) |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |

**예시 데이터**:
```json
{
  "id": "proj_abc_backend_001",
  "project_id": "proj_abc",
  "role": "backend",
  "title": "인증 API 개발",
  "description": "JWT 기반 로그인/로그아웃 API 엔드포인트 구현",
  "acceptance_json": ["POST /auth/login 응답 200", "JWT 토큰 발급", "로그아웃 토큰 무효화"],
  "dependencies_json": [],
  "priority": 0
}
```

---

### 3.3 WorkItem (작업 인스턴스)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| task_id | TEXT | FK → Task.id, UNIQUE | 연결된 작업 (1:1) |
| agent_id | TEXT | FK → Agent.id | 담당 에이전트 |
| status | TEXT | NOT NULL | WorkStatus enum 값 |
| dependencies_json | TEXT | | JSON: List[WorkItem.id] — 대기 중인 의존성 |
| watchers_json | TEXT | | JSON: List[Agent.id] — 상태 변경 알림 구독자 |
| retry_count | INTEGER | DEFAULT 0 | LLM 재시도 횟수 |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |
| updated_at | TEXT | NOT NULL | 최종 업데이트 타임스탬프 |
| started_at | TEXT | | 실행 시작 시각 |
| completed_at | TEXT | | 완료 시각 |

**WorkStatus Enum**:
| 값 | 설명 |
|----|------|
| `planned` | 등록 완료, 실행 대기 중 |
| `waiting` | 의존성 완료 대기 중 |
| `in_progress` | 에이전트가 현재 실행 중 |
| `review` | 피어 리뷰 대기 중 |
| `done` | 성공적으로 완료 |
| `failed` | 실패 (retry 초과 또는 치명적 오류) |
| `blocked` | 외부 이슈로 인해 블로킹됨 |

---

### 3.4 TaskResult (작업 결과)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| work_item_id | TEXT | FK → WorkItem.id, UNIQUE | 연결된 WorkItem (1:1) |
| status | TEXT | NOT NULL | `success` / `partial` / `failed` |
| approach | TEXT | | 에이전트가 선택한 구현 방법 설명 |
| code_json | TEXT | | JSON: Dict[filename, content] — 생성 코드 맵 |
| files_json | TEXT | | JSON: List[{name, path, type}] — 파일 메타데이터 |
| dependencies_list | TEXT | | JSON: List[str] — 감지된 패키지 의존성 |
| error_message | TEXT | | 실패 시 오류 메시지 |
| llm_prompt_tokens | INTEGER | | LLM 입력 토큰 수 |
| llm_output_tokens | INTEGER | | LLM 출력 토큰 수 |
| duration_sec | REAL | | 실행 소요 시간 (초) |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |

**예시 데이터**:
```json
{
  "id": "result_xyz",
  "work_item_id": "wi_abc",
  "status": "success",
  "approach": "FastAPI + SQLAlchemy ORM 사용, Alembic 마이그레이션",
  "code_json": {
    "main.py": "from fastapi import FastAPI\napp = FastAPI()...",
    "models.py": "from sqlalchemy import Column, Integer, String..."
  },
  "files_json": [
    {"name": "main.py", "path": "backend/main.py", "type": "python"},
    {"name": "models.py", "path": "backend/models.py", "type": "python"}
  ],
  "dependencies_list": ["fastapi", "uvicorn", "sqlalchemy", "alembic"],
  "duration_sec": 38.5
}
```

---

### 3.5 Agent (에이전트)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | `cto` / `frontend` / `backend` / `mlops` (고정) |
| name | TEXT | NOT NULL | 에이전트 이름 |
| role | TEXT | NOT NULL | `cto` / `frontend` / `backend` / `mlops` |
| model_name | TEXT | NOT NULL | Ollama 모델 ID |
| ollama_url | TEXT | NOT NULL | Ollama API 기본 URL |
| system_prompt | TEXT | NOT NULL | 역할 정의 System Prompt |
| is_active | INTEGER | DEFAULT 1 | 활성 상태 (boolean) |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |

**기본 데이터 (Seed)**:
| id | name | model_name |
|----|------|-----------|
| cto | CTO Agent | llama3.1:70b |
| frontend | Frontend SLM | phi3.5 |
| backend | Backend SLM | phi3.5 |
| mlops | MLOps SLM | llama3.2:3b |

---

### 3.6 AgentDNA (에이전트 DNA)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| agent_id | TEXT | FK → Agent.id, UNIQUE | 소유 에이전트 (1:1) |
| creativity | REAL | DEFAULT 0.5 | 창의성 (0.0 ~ 1.0) |
| precision | REAL | DEFAULT 0.5 | 정확성 (0.0 ~ 1.0) |
| speed | REAL | DEFAULT 0.5 | 속도 선호도 (0.0 ~ 1.0) |
| collaboration | REAL | DEFAULT 0.5 | 협업 능력 (0.0 ~ 1.0) |
| learning_rate | REAL | DEFAULT 0.5 | 학습 속도 (0.0 ~ 1.0) |
| risk_taking | REAL | DEFAULT 0.5 | 위험 감수 성향 (0.0 ~ 1.0) |
| debugging_skill | REAL | DEFAULT 0.5 | 디버깅 능력 (0.0 ~ 1.0) |
| innovation | REAL | DEFAULT 0.5 | 혁신성 (0.0 ~ 1.0) |
| code_quality | REAL | DEFAULT 0.5 | 코드 품질 집착도 (0.0 ~ 1.0) |
| documentation | REAL | DEFAULT 0.5 | 문서화 성향 (0.0 ~ 1.0) |
| version | INTEGER | DEFAULT 1 | DNA 버전 (진화 횟수) |
| updated_at | TEXT | NOT NULL | 최종 진화 타임스탬프 |

**역할별 기본 DNA 값**:
| 유전자 | Frontend | Backend | MLOps |
|--------|---------|---------|-------|
| creativity | 0.8 | 0.5 | 0.4 |
| precision | 0.6 | 0.9 | 0.8 |
| speed | 0.5 | 0.5 | 0.8 |
| collaboration | 0.8 | 0.6 | 0.6 |
| code_quality | 0.7 | 0.9 | 0.8 |

---

### 3.7 AgentTaskHistory (에이전트 작업 이력)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| agent_id | TEXT | FK → Agent.id | 수행 에이전트 |
| task_id | TEXT | FK → Task.id | 수행 작업 |
| success | INTEGER | NOT NULL | 성공 여부 (boolean) |
| quality_score | REAL | | 품질 점수 (0.0 ~ 1.0, 피어 리뷰 기반) |
| duration_sec | REAL | | 수행 소요 시간 |
| dna_snapshot_json | TEXT | | 수행 당시 DNA 상태 (JSON) |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |

---

### 3.8 Message (메시지)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| from_agent_id | TEXT | FK → Agent.id | 발신 에이전트 |
| to_agent_id | TEXT | FK → Agent.id | 수신 에이전트 |
| work_item_id | TEXT | FK → WorkItem.id | 관련 작업 (nullable) |
| message_type | TEXT | NOT NULL | `question` / `answer` / `notification` / `review_request` / `review_response` |
| content | TEXT | NOT NULL | 메시지 본문 (자연어 또는 JSON) |
| status | TEXT | NOT NULL | `sent` / `delivered` / `answered` / `timeout` |
| answer_to_id | TEXT | FK → Message.id | 답변 대상 메시지 ID (nullable) |
| created_at | TEXT | NOT NULL | 발신 타임스탬프 |
| answered_at | TEXT | | 답변 수신 타임스탬프 |

---

### 3.9 StageGateMeeting (Stage Gate 회의)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| project_id | TEXT | FK → Project.id | 소속 프로젝트 |
| stage_name | TEXT | NOT NULL | `requirements` / `architecture` / `implementation` / `testing` / `deployment` |
| status | TEXT | NOT NULL | `pending` / `in_progress` / `completed` |
| decision | TEXT | | `pass` / `revision_needed` / `failed` |
| summary | TEXT | | CTO 종합 의사결정 요약 |
| action_items_json | TEXT | | JSON: List[str] — 후속 액션 아이템 |
| started_at | TEXT | | 회의 시작 타임스탬프 |
| completed_at | TEXT | | 회의 완료 타임스탬프 |

---

### 3.10 MeetingReview (회의 리뷰)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| meeting_id | TEXT | FK → StageGateMeeting.id | 소속 회의 |
| agent_id | TEXT | FK → Agent.id | 리뷰어 에이전트 |
| content | TEXT | NOT NULL | 리뷰 내용 (자연어) |
| vote | TEXT | NOT NULL | `approve` / `request_changes` / `abstain` |
| concerns_json | TEXT | | JSON: List[str] — 우려사항 목록 |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |

---

### 3.11 KnowledgeNode (지식 그래프 노드)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| agent_id | TEXT | FK → Agent.id | 보유 에이전트 |
| keyword | TEXT | NOT NULL | 전문성 키워드 (예: "JWT", "Redux", "Docker") |
| domain | TEXT | NOT NULL | 도메인 (예: "auth", "state_management", "containerization") |
| expertise_level | REAL | DEFAULT 0.5 | 전문도 (0.0 ~ 1.0) |
| source_task_id | TEXT | FK → Task.id | 이 전문성을 얻은 작업 (nullable) |
| created_at | TEXT | NOT NULL | ISO 8601 타임스탬프 |

**복합 UNIQUE 제약**: (agent_id, keyword)

---

### 3.12 SystemMetrics (시스템 메트릭)

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | TEXT | PK | UUID v4 |
| project_id | TEXT | FK → Project.id, UNIQUE | 소속 프로젝트 (1:1) |
| total_tasks | INTEGER | DEFAULT 0 | 전체 작업 수 |
| completed_tasks | INTEGER | DEFAULT 0 | 완료된 작업 수 |
| failed_tasks | INTEGER | DEFAULT 0 | 실패한 작업 수 |
| llm_calls | INTEGER | DEFAULT 0 | LLM API 총 호출 수 |
| llm_total_tokens | INTEGER | DEFAULT 0 | 총 사용 토큰 수 |
| llm_errors | INTEGER | DEFAULT 0 | LLM 오류 횟수 |
| messages_sent | INTEGER | DEFAULT 0 | 에이전트 간 메시지 발송 수 |
| questions_asked | INTEGER | DEFAULT 0 | Q&A 요청 수 |
| questions_answered | INTEGER | DEFAULT 0 | Q&A 성공 응답 수 |
| total_duration_sec | REAL | | 전체 프로젝트 소요 시간 (초) |
| success_rate | REAL | | 작업 완료율 (0.0 ~ 1.0) |
| created_at | TEXT | NOT NULL | 생성 타임스탬프 |
| updated_at | TEXT | NOT NULL | 최종 업데이트 타임스탬프 |

---

## 4. 관계 정의

### 4.1 관계 표

| 관계 | 유형 | 설명 |
|------|------|------|
| Project → Task | 1:N | 프로젝트는 여러 작업을 가짐 |
| Task → WorkItem | 1:1 | 각 작업은 하나의 실행 인스턴스를 가짐 |
| WorkItem → TaskResult | 1:1 | 각 실행 인스턴스는 하나의 결과를 가짐 |
| Agent → WorkItem | 1:N | 에이전트는 여러 작업을 수행 |
| Agent → AgentDNA | 1:1 | 에이전트는 하나의 DNA를 가짐 |
| Agent → AgentTaskHistory | 1:N | 에이전트는 여러 이력을 가짐 |
| Task → AgentTaskHistory | 1:1 | 각 작업은 하나의 이력 레코드를 생성 |
| Agent → Message (from) | 1:N | 에이전트는 여러 메시지를 발신 |
| Agent → Message (to) | 1:N | 에이전트는 여러 메시지를 수신 |
| WorkItem → Message | 1:N | 작업 관련 메시지는 여러 개일 수 있음 |
| Project → StageGateMeeting | 1:N | 프로젝트는 여러 Stage Gate 회의를 가짐 |
| StageGateMeeting → MeetingReview | 1:N | 회의는 여러 에이전트의 리뷰를 가짐 |
| Agent → MeetingReview | 1:N | 에이전트는 여러 회의에서 리뷰 제출 |
| Agent → KnowledgeNode | 1:N | 에이전트는 여러 전문성 노드를 가짐 |
| Project → SystemMetrics | 1:1 | 프로젝트는 하나의 메트릭 레코드를 가짐 |

### 4.2 WorkItem 의존성 (자기 참조 N:M)

WorkItem 간 의존성은 `dependencies_json` 컬럼에 JSON 배열로 저장:

```sql
-- WorkItem B가 WorkItem A에 의존하는 경우
-- WorkItem B의 dependencies_json = '["work_item_a_id"]'

-- 조회 예시 (애플리케이션 레이어에서 파싱)
SELECT id, dependencies_json
FROM work_items
WHERE project_id = 'proj_abc';
```

> **설계 결정**: 단순화를 위해 별도 조인 테이블 대신 JSON 배열 사용. Phase 3 이후 복잡한 의존성이 필요해지면 `work_item_dependencies` 조인 테이블로 정규화 가능.

---

## 5. 데이터베이스 스키마 (DDL)

```sql
-- ============================================================
-- 파일: workspace.db
-- 멀티 에이전트 시스템 전체 스키마
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ────────────────────────────────────────────────────────────
-- 에이전트 (기본 데이터, 시스템 구동 시 INSERT)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,          -- 'cto','frontend','backend','mlops'
    name            TEXT NOT NULL,
    role            TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    ollama_url      TEXT NOT NULL DEFAULT 'http://localhost:11434',
    system_prompt   TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────
-- 에이전트 DNA
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_dna (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    creativity      REAL NOT NULL DEFAULT 0.5 CHECK (creativity BETWEEN 0.0 AND 1.0),
    precision       REAL NOT NULL DEFAULT 0.5 CHECK (precision  BETWEEN 0.0 AND 1.0),
    speed           REAL NOT NULL DEFAULT 0.5 CHECK (speed      BETWEEN 0.0 AND 1.0),
    collaboration   REAL NOT NULL DEFAULT 0.5 CHECK (collaboration BETWEEN 0.0 AND 1.0),
    learning_rate   REAL NOT NULL DEFAULT 0.5 CHECK (learning_rate BETWEEN 0.0 AND 1.0),
    risk_taking     REAL NOT NULL DEFAULT 0.5 CHECK (risk_taking BETWEEN 0.0 AND 1.0),
    debugging_skill REAL NOT NULL DEFAULT 0.5 CHECK (debugging_skill BETWEEN 0.0 AND 1.0),
    innovation      REAL NOT NULL DEFAULT 0.5 CHECK (innovation BETWEEN 0.0 AND 1.0),
    code_quality    REAL NOT NULL DEFAULT 0.5 CHECK (code_quality BETWEEN 0.0 AND 1.0),
    documentation   REAL NOT NULL DEFAULT 0.5 CHECK (documentation BETWEEN 0.0 AND 1.0),
    version         INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────
-- 프로젝트
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'planning'
                        CHECK (status IN ('planning','in_progress','completed','failed')),
    tech_stack_json TEXT,                       -- JSON 객체
    user_input      TEXT NOT NULL,
    output_dir      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

-- ────────────────────────────────────────────────────────────
-- 작업
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role                TEXT NOT NULL CHECK (role IN ('cto','frontend','backend','mlops')),
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    acceptance_json     TEXT,                   -- JSON 배열: List[str]
    dependencies_json   TEXT DEFAULT '[]',      -- JSON 배열: List[task_id]
    priority            INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────
-- 작업 인스턴스 (WorkItem)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS work_items (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    status              TEXT NOT NULL DEFAULT 'planned'
                            CHECK (status IN ('planned','waiting','in_progress','review','done','failed','blocked')),
    dependencies_json   TEXT DEFAULT '[]',      -- JSON 배열: List[work_item_id]
    watchers_json       TEXT DEFAULT '[]',      -- JSON 배열: List[agent_id]
    retry_count         INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    started_at          TEXT,
    completed_at        TEXT
);

-- ────────────────────────────────────────────────────────────
-- 작업 결과
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_results (
    id                  TEXT PRIMARY KEY,
    work_item_id        TEXT NOT NULL UNIQUE REFERENCES work_items(id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'success'
                            CHECK (status IN ('success','partial','failed')),
    approach            TEXT,
    code_json           TEXT,                   -- JSON 객체: {filename: content}
    files_json          TEXT,                   -- JSON 배열: List[{name, path, type}]
    dependencies_list   TEXT DEFAULT '[]',      -- JSON 배열: List[str]
    error_message       TEXT,
    llm_prompt_tokens   INTEGER,
    llm_output_tokens   INTEGER,
    duration_sec        REAL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────────────────────────
-- 에이전트 작업 이력
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_task_history (
    id                  TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    task_id             TEXT NOT NULL REFERENCES tasks(id),
    success             INTEGER NOT NULL,       -- 0: 실패, 1: 성공
    quality_score       REAL,                   -- 0.0 ~ 1.0
    duration_sec        REAL,
    dna_snapshot_json   TEXT,                   -- 수행 당시 DNA 상태
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (agent_id, task_id)
);

-- ────────────────────────────────────────────────────────────
-- 에이전트 간 메시지
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    from_agent_id   TEXT NOT NULL REFERENCES agents(id),
    to_agent_id     TEXT NOT NULL REFERENCES agents(id),
    work_item_id    TEXT REFERENCES work_items(id),
    message_type    TEXT NOT NULL
                        CHECK (message_type IN ('question','answer','notification','review_request','review_response')),
    content         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'sent'
                        CHECK (status IN ('sent','delivered','answered','timeout')),
    answer_to_id    TEXT REFERENCES messages(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at     TEXT
);

-- ────────────────────────────────────────────────────────────
-- Stage Gate 회의
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stage_gate_meetings (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage_name          TEXT NOT NULL
                            CHECK (stage_name IN ('requirements','architecture','implementation','testing','deployment')),
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','in_progress','completed')),
    decision            TEXT CHECK (decision IN ('pass','revision_needed','failed')),
    summary             TEXT,
    action_items_json   TEXT DEFAULT '[]',
    started_at          TEXT,
    completed_at        TEXT
);

-- ────────────────────────────────────────────────────────────
-- 회의 리뷰
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meeting_reviews (
    id              TEXT PRIMARY KEY,
    meeting_id      TEXT NOT NULL REFERENCES stage_gate_meetings(id) ON DELETE CASCADE,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    content         TEXT NOT NULL,
    vote            TEXT NOT NULL CHECK (vote IN ('approve','request_changes','abstain')),
    concerns_json   TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (meeting_id, agent_id)               -- 에이전트당 1회 리뷰
);

-- ────────────────────────────────────────────────────────────
-- 지식 그래프
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_nodes (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    keyword         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    expertise_level REAL NOT NULL DEFAULT 0.5 CHECK (expertise_level BETWEEN 0.0 AND 1.0),
    source_task_id  TEXT REFERENCES tasks(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (agent_id, keyword)
);

-- ────────────────────────────────────────────────────────────
-- 시스템 메트릭
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_metrics (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    total_tasks         INTEGER NOT NULL DEFAULT 0,
    completed_tasks     INTEGER NOT NULL DEFAULT 0,
    failed_tasks        INTEGER NOT NULL DEFAULT 0,
    llm_calls           INTEGER NOT NULL DEFAULT 0,
    llm_total_tokens    INTEGER NOT NULL DEFAULT 0,
    llm_errors          INTEGER NOT NULL DEFAULT 0,
    messages_sent       INTEGER NOT NULL DEFAULT 0,
    questions_asked     INTEGER NOT NULL DEFAULT 0,
    questions_answered  INTEGER NOT NULL DEFAULT 0,
    total_duration_sec  REAL,
    success_rate        REAL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## 6. 인덱스 전략

```sql
-- 프로젝트 상태별 조회 (실행 중인 프로젝트 목록)
CREATE INDEX IF NOT EXISTS idx_projects_status
    ON projects (status);

-- 프로젝트별 작업 목록 조회
CREATE INDEX IF NOT EXISTS idx_tasks_project_id
    ON tasks (project_id);

-- 역할별 작업 조회 (에이전트 별 할당 작업)
CREATE INDEX IF NOT EXISTS idx_tasks_role
    ON tasks (role);

-- 상태별 WorkItem 조회 (대기 중 / 실행 중 항목 조회)
CREATE INDEX IF NOT EXISTS idx_work_items_status
    ON work_items (status);

-- 에이전트별 WorkItem 조회
CREATE INDEX IF NOT EXISTS idx_work_items_agent_id
    ON work_items (agent_id);

-- 에이전트 간 메시지 조회 (수신함)
CREATE INDEX IF NOT EXISTS idx_messages_to_agent
    ON messages (to_agent_id, status);

-- 발신 에이전트별 메시지 이력
CREATE INDEX IF NOT EXISTS idx_messages_from_agent
    ON messages (from_agent_id);

-- 에이전트 작업 이력 조회
CREATE INDEX IF NOT EXISTS idx_agent_history_agent
    ON agent_task_history (agent_id, created_at DESC);

-- 지식 그래프 키워드 검색
CREATE INDEX IF NOT EXISTS idx_knowledge_keyword
    ON knowledge_nodes (keyword, expertise_level DESC);

-- Stage Gate 회의 프로젝트별 조회
CREATE INDEX IF NOT EXISTS idx_meetings_project
    ON stage_gate_meetings (project_id, stage_name);
```

---

## 7. 데이터 흐름 예시

### 7.1 프로젝트 생성 → 완료 시 데이터 변화

```
1. 사용자 입력: "Todo 앱"

   INSERT INTO projects VALUES (
     'proj_001', 'Todo 앱', '...', 'planning', ...
   );
   INSERT INTO system_metrics VALUES (
     'metric_001', 'proj_001', 0, 0, 0, ...
   );

2. CTO 전략 수립 완료

   UPDATE projects SET status='in_progress' WHERE id='proj_001';

   INSERT INTO tasks VALUES
     ('proj_001_backend_001', 'proj_001', 'backend', 'CRUD API', ...),
     ('proj_001_frontend_001', 'proj_001', 'frontend', 'Todo UI', ...),
     ('proj_001_mlops_001',    'proj_001', 'mlops',    'Docker',  ...);

   INSERT INTO work_items VALUES
     ('wi_001', 'proj_001_backend_001',  'backend',  'planned', ...),
     ('wi_002', 'proj_001_frontend_001', 'frontend', 'waiting', '["wi_001"]', ...),
     ('wi_003', 'proj_001_mlops_001',    'mlops',    'waiting', '["wi_001"]', ...);

3. Backend 실행 완료

   UPDATE work_items SET status='done', completed_at='...' WHERE id='wi_001';

   INSERT INTO task_results VALUES (
     'result_001', 'wi_001', 'success', 'FastAPI 사용', '{"main.py": "..."}', ...
   );

   -- 의존성 해제: wi_002, wi_003 → 'planned'으로 전환
   UPDATE work_items SET status='planned' WHERE id IN ('wi_002', 'wi_003');

   UPDATE system_metrics SET
     completed_tasks = completed_tasks + 1,
     llm_calls = llm_calls + 1
   WHERE project_id = 'proj_001';

4. 프로젝트 완료

   UPDATE projects SET
     status='completed',
     output_dir='outputs/todo-app',
     completed_at=datetime('now')
   WHERE id='proj_001';

   UPDATE system_metrics SET
     success_rate = 1.0,
     total_duration_sec = 720.5
   WHERE project_id='proj_001';
```

### 7.2 Q&A 메시지 플로우

```
-- Frontend가 Backend에게 질문
INSERT INTO messages VALUES (
  'msg_001', 'frontend', 'backend', 'wi_002',
  'question', 'API 인증 엔드포인트가 어떻게 되나요?',
  'sent', NULL, datetime('now'), NULL
);

-- Backend가 답변
UPDATE messages SET status='answered', answered_at=datetime('now') WHERE id='msg_001';

INSERT INTO messages VALUES (
  'msg_002', 'backend', 'frontend', 'wi_002',
  'answer', 'POST /api/auth/login 으로 요청하세요. JWT 토큰 반환합니다.',
  'delivered', 'msg_001', datetime('now'), NULL
);

-- 지식 노드 업데이트 (Backend의 auth 전문성 기록)
INSERT OR REPLACE INTO knowledge_nodes VALUES (
  'kn_001', 'backend', 'JWT', 'authentication', 0.9,
  'proj_001_backend_001', datetime('now')
);
```

---

*작성자: 시스템 설계팀 | 검토일: 2026-02-21*

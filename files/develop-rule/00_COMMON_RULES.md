# 공통 규칙 (COMMON RULES)

> 모든 파트, 모든 AI 에이전트(Codex·Claude)가 반드시 준수해야 하는 규칙입니다.
> 파트별 규칙보다 이 파일이 항상 우선합니다.

---

## 0. 이 프로젝트를 작업하기 전에 반드시 읽어야 할 파일

```
files/docs/개발 일지/초기 아키텍처 설계/개발 일지(4).md   ← 현재 전략 기준 문서
files/docs/04_SYSTEM_ARCHITECTURE.md  ← SSOT (기술 결정 기준)
files/docs/03_ERD.md                  ← 데이터 모델 기준
```

작업 전 위 3개 파일을 반드시 읽고, 현재 어느 Part·Stage를 작업 중인지 파악한 뒤 시작합니다.

---

## 1. 아키텍처 계층 규칙

### 1.1 디렉토리 구조

```
project-root/
├── files/            # 문서·규칙·개발 일지 (기획 자산)
├── src/
│   ├── domain/       # 순수 모델·규칙 — 외부 의존성 금지
│   ├── application/  # 유스케이스·오케스트레이션
│   ├── adapters/     # LLM, DB, 큐, 외부 API 구현체
│   ├── interfaces/   # CLI·WebSocket·API 진입점
│   └── observability/# logger, metrics, tracing, error_codes
└── tests/
    ├── unit/         # domain 레이어 대상
    ├── integration/  # application + adapters 대상
    └── e2e/          # interfaces 전체 흐름 대상
```

### 1.2 의존성 방향 — 절대 규칙

```
허용:
  interfaces  →  application  →  domain
  adapters    →  application
  adapters    →  domain
  observability → 모든 레이어 (단방향 수집만)

금지:
  domain      →  adapters     (절대 금지)
  domain      →  application  (절대 금지)
  application →  interfaces   (절대 금지)
```

위반 시 PR 병합 금지. 의존성 방향 위반은 이슈 심각도 **S**로 분류합니다.

### 1.3 domain 레이어 금지 사항

```python
# 금지 — domain 안에서 외부 라이브러리 import
import aiohttp       # ❌
import sqlite3       # ❌
import redis         # ❌

# 허용 — 표준 라이브러리 + Pydantic만
from pydantic import BaseModel   # ✅
from enum import Enum            # ✅
from dataclasses import dataclass # ✅
from typing import Optional, List # ✅
```

---

## 2. 코드 스타일 규칙

### 2.1 언어 및 버전

- Python **3.10+** 필수
- 타입 힌트 **전면 사용** (Any 사용 최소화, 불가피한 경우 주석으로 이유 명시)
- 비동기 함수는 **async/await** 일관 사용 (threading 혼용 금지)

### 2.2 포맷팅 — 자동화 도구 기준

```bash
black .          # 코드 포맷 (line-length=100)
isort .          # import 정렬
flake8 .         # 린트 (--max-line-length=100 --ignore=E203,W503)
mypy .           # 타입 검사
```

AI가 코드를 작성한 후에는 위 4개 명령을 기준으로 위반 없이 작성합니다.

### 2.3 네이밍 규칙

| 대상 | 규칙 | 예시 |
|------|------|------|
| 클래스 | PascalCase | `CTOAgent`, `WorkItem` |
| 함수·메서드 | snake_case | `execute_task()`, `create_strategy()` |
| 상수 | UPPER_SNAKE_CASE | `MAX_RETRY`, `DEFAULT_TIMEOUT` |
| 파일 | snake_case | `cto_agent.py`, `work_item.py` |
| 디렉토리 | snake_case | `collaboration/`, `adapters/` |
| Pydantic 모델 필드 | snake_case | `task_id`, `created_at` |
| 환경변수 | UPPER_SNAKE_CASE | `OLLAMA_BASE_URL`, `LOG_LEVEL` |

### 2.4 함수 길이 제한

- 단일 함수 **50줄 이하** 권장, **100줄 초과 금지**
- 100줄 초과 시 즉시 분해 (책임 단위로)

### 2.5 주석 규칙

```python
# ✅ 허용 — "왜" 를 설명하는 주석
# Ollama는 동시 요청 시 OOM이 발생하므로 순차 실행
await self._load_model_sequentially()

# ❌ 금지 — "무엇" 을 반복하는 주석
# 모델을 순차적으로 로드한다
await self._load_model_sequentially()
```

---

## 3. 관측성 규칙 (Observability)

### 3.1 모든 실행 단위에 ID 부여

```python
# 모든 실행에 반드시 포함
run_id     : str  # 프로젝트 실행 1회 단위
task_id    : str  # 개별 작업 단위
message_id : str  # 에이전트 간 메시지 단위
```

### 3.2 구조화 로그 형식 — JSON 필수

```python
# ✅ 올바른 로그
logger.info("task_completed", extra={
    "run_id": run_id,
    "task_id": task_id,
    "agent": "backend",
    "duration_sec": 38.5,
    "stage": "Part2-Stage4"
})

# ❌ 금지 — 자유 문자열 로그
print(f"task {task_id} completed in 38.5s")
logger.info("task completed")
```

### 3.3 에러코드 — 분류형 Enum 사용 필수

```python
from observability.error_codes import ErrorCode

# ✅ 올바른 에러 처리
raise AgentError(ErrorCode.E_LLM_TIMEOUT, task_id=task_id)

# ❌ 금지 — 문자열 에러
raise Exception("LLM timeout occurred")
```

에러코드 전체 목록: `observability/error_codes.py` 참조

---

## 4. 테스트 규칙

### 4.1 테스트 없는 기능 병합 금지

- 새 함수·클래스 추가 시 단위 테스트 **최소 1개** 필수
- 외부 의존성(LLM, DB)이 있는 코드는 Mock을 사용한 단위 테스트 필수

### 4.2 Mock 사용 원칙

```python
# ✅ 단위 테스트에서 LLM 호출은 MockLLMProvider 사용
async def test_cto_create_strategy():
    llm = MockLLMProvider(response='{"project_name": "Todo"}')
    cto = CTOAgent(llm=llm)
    result = await cto.create_strategy("Todo 앱")
    assert result.project_name == "Todo"

# ❌ 금지 — 단위 테스트에서 실제 Ollama 호출
async def test_cto_create_strategy():
    cto = CTOAgent(ollama_url="http://localhost:11434")  # 실제 LLM 호출 금지
```

### 4.3 테스트 파일 위치

| 테스트 종류 | 위치 | 대상 |
|-----------|------|------|
| 단위 | `tests/unit/` | domain 레이어 |
| 통합 | `tests/integration/` | application + adapters |
| E2E | `tests/e2e/` | 전체 흐름 |

---

## 5. 커밋 규칙

### 5.1 Conventional Commits 필수

```
<type>(<scope>): <description>

type   : feat / fix / docs / test / refactor / style / chore
scope  : cto / slm / workspace / queue / dna / gate / infra / obs

예시:
  feat(cto): create_strategy 메서드 구현
  fix(slm): JSON 파싱 실패 시 재시도 로직 추가
  test(workspace): WorkItem 상태 전이 단위 테스트
  refactor(adapters): OllamaProvider LLMProvider 인터페이스 분리
```

### 5.2 스키마 변경 시 필수 태그

```
BREAKING CHANGE: WorkItem에 retry_count 필드 추가

domain/contracts/work_item.py 수정
관련 테스트 전체 통과 확인 후 병합
```

### 5.3 PR 단위

- **기능 1개, 책임 1개** 원칙
- 하나의 PR이 2개 이상의 Stage에 걸치는 것 금지

---

## 6. 금지 사항 (전체 파트 공통)

| 번호 | 금지 사항 | 이유 |
|------|---------|------|
| F-01 | `print()` 디버그 사용 | 구조화 로그로만 출력 |
| F-02 | `except Exception: pass` | 에러 묵살 금지 |
| F-03 | 하드코딩된 URL·경로 | 환경변수 또는 config.py 사용 |
| F-04 | 동기 함수 내 `time.sleep()` | `asyncio.sleep()` 사용 |
| F-05 | domain 레이어 외부 의존성 | 의존성 방향 규칙 위반 |
| F-06 | 테스트 없는 기능 병합 | 안정성 원칙 위반 |
| F-07 | 에러 문자열 직접 사용 | ErrorCode Enum 사용 |
| F-08 | `Any` 타입 무분별 사용 | 구체적 타입 또는 Union 사용 |
| F-09 | 스키마 변경 시 BREAKING CHANGE 태그 누락 | 계약 위반 |
| F-10 | 외부 API 키·URL을 코드에 직접 기입 | .env 파일 사용 |

---

## 7. 이슈 심각도 분류 기준

작업 중 발견된 모든 이슈는 아래 기준으로 분류하고 다음 개발 일지에 기록합니다.

| 축 | S | A | B | C |
|----|---|---|---|---|
| **차단성** | 실행 자체 불가 | 완료 기준 충족 불가 | 품질 저하 | 기술 부채만 |
| **전파성** | 모든 Part | 1개 Part 전체 | 특정 Stage | 파일·모듈 |
| **발현 시점** | Part 1 즉시 | Part 2 진입 직후 | Part 2 중반 | Part 3 이후 |
| **수정 비용** | 아키텍처 재설계 | 여러 파일 동시 수정 | 단일 컴포넌트 | 설정·문서 수정 |

**최종 심각도 = 4축 중 가장 높은 등급**

| 최종 등급 | 처리 원칙 |
|---------|---------|
| S | 다음 Stage 착수 전 반드시 해결 |
| A | 해당 Part 내에서 해결 |
| B | 해당 Part 종료 전 해결 (발현 시점 S면 선행 처리) |
| C | 기술 부채로 관리, 다음 Part 전 일괄 정리 |

---

## 8. 파트별 개발 일지 작성 규칙

**한 파트의 한 Stage 작업이 완료될 때마다 반드시 개발 일지를 작성합니다.**
다음 Stage 착수는 개발 일지 작성 완료 후에 허용됩니다.

### 8.1 디렉토리 및 파일 네이밍 규칙

모든 개발 일지는 `files/docs/개발 일지/` 하위에 파트별 폴더로 관리합니다.
파트 번호는 `개발 일지(4).md`의 Part 번호를 따릅니다.

```
files/docs/개발 일지/
├── 초기 아키텍처 설계/          ← 기획·전략 문서 (수정 금지)
│   ├── 개발 일지(1).md
│   ├── 개발 일지(2).md
│   ├── 개발 일지(3).md
│   └── 개발 일지(4).md          ← 현재 전략 기준 문서 (SSOT)
├── Part0 개발일지/              ← 공통 기반
│   ├── 개발 일지(1).md          ← Part0 Stage1 완료 시 작성
│   ├── 개발 일지(2).md          ← Part0 Stage2 완료 시 작성
│   └── ...
├── Part1 개발일지/              ← CTO Agent
├── Part2 개발일지/              ← Backend SLM Agent
├── Part3 개발일지/              ← Frontend SLM Agent
├── Part4 개발일지/              ← MLOps SLM Agent
├── Part5 개발일지/              ← 협업 레이어 통합
├── Part6 개발일지/              ← 시스템 고도화
└── Part7 개발일지/              ← CEO 대시보드
```

**파일 작성 규칙**:

- Stage N 완료 시 → 해당 파트 폴더에 `개발 일지(N).md` 직접 생성
- 파일 경로 예시: `files/docs/개발 일지/Part0 개발일지/개발 일지(1).md`
- Stage 번호 = 개발 일지 번호 (Stage 1 → 개발 일지(1), Stage 2 → 개발 일지(2))
- 파일명에 날짜 추가 가능: `개발 일지(1) — 2026-02-21.md`

### 8.2 개발 일지 필수 작성 항목

각 개발 일지는 아래 **4개 섹션을 모두 포함**해야 합니다.

```markdown
# [파트명] 개발 일지 (N) — [Stage명]
> 작성일: YYYY-MM-DD | Part: X | Stage: Y

---

## 1. 작업 내용
이번 Stage에서 실제로 수행한 작업을 구체적으로 기술합니다.
- 구현한 기능·모듈·클래스 목록
- 수정한 기존 코드와 수정 이유
- 주요 설계 결정 사항

## 2. 결과물
이번 Stage에서 생성·수정된 파일 목록과 각 파일의 역할을 기술합니다.
- 생성된 파일: `경로/파일명` — 역할 설명
- 수정된 파일: `경로/파일명` — 변경 내용 요약
- 통과한 테스트: `tests/unit/test_xxx.py` — 검증 항목

## 3. 결정 이유
이번 작업에서 내린 주요 기술적 결정과 그 근거를 기술합니다.
- 왜 이 구조(또는 패턴, 알고리즘)를 선택했는가?
- 고려했으나 채택하지 않은 대안과 기각 이유
- 전략 문서(개발 일지(4).md)의 어느 결정을 따랐는가?
- 전략 변경 이력: 작업 시작 시 제시한 전략과 달라진 부분 및 변경 이유 (변경 없으면 "없음")

## 4. 발생한 리스크
이 구현으로 인해 새롭게 생성되거나 확인된 리스크를 기술합니다.
- 리스크 항목 | 심각도(S/A/B/C) | 발현 가능 시점 | 대응 방안
- 해결된 기존 이슈가 있다면 함께 기록
```

### 8.3 작성 기준

| 항목 | 기준 |
|------|------|
| 작성 시점 | 작업 완료 직후, 다음 Stage 착수 전 |
| 작성 주체 | 작업을 수행한 AI (Codex·Claude) |
| 분량 | 최소 각 섹션 3줄 이상 — 형식적 작성 금지 |
| 이슈 심각도 | 7절의 4축 기준에 따라 분류 |

### 8.4 금지 사항

| 번호 | 금지 사항 |
|------|---------|
| D-01 | 개발 일지 없이 다음 Stage 착수 |
| D-02 | 4개 섹션 중 하나라도 누락 |
| D-03 | "특이사항 없음" 등 형식적 작성 |
| D-04 | 리스크 섹션에 심각도 미분류 |
| D-05 | 기존 개발 일지 파일 소급 수정 (새 파일로 추가) |

---

## 9. 작업 진행 절차 규칙

**모든 작업은 아래 절차를 반드시 순서대로 따릅니다. 절차 생략은 금지입니다.**

### 9.1 작업 시작 전 — 전략 제시 및 필수 질문

작업 지시를 받으면 즉시 구현에 착수하지 않고 다음 순서를 따릅니다.

```
1. 구현 전략 제시
   - 어떤 방식으로 구현할 것인지 개요 서술
   - 채택한 패턴·구조와 그 이유
   - 예상 파일 목록 및 변경 범위

2. 필수 질문 제시 (5개, 최소 3개)
   - 전략을 확정하기 전에 반드시 확인해야 할 사항
   - 모호한 요구사항, 의존성, 제약 조건, 우선순위 등
   - 질문 형식: 번호 목록으로 명확하게 제시

3. 답변 대기
   - 사용자의 답변이 입력되기 전까지 코드 작성·파일 수정 금지
   - 답변이 불충분하면 재질문 허용
```

**필수 질문 작성 기준**:

| 질문 유형 | 예시 |
|---------|------|
| 요구사항 명확화 | "A와 B 중 어떤 방식을 우선하나요?" |
| 의존성 확인 | "이 기능은 X가 완성된 후 구현해야 하는데, X의 현재 상태는?" |
| 제약 조건 | "성능 요구사항이 있나요? (응답 시간, 동시 처리 수 등)" |
| 범위 확정 | "엣지 케이스 Y도 처리 범위에 포함하나요?" |
| 우선순위 | "완성도와 속도 중 이번 Stage에서 더 중요한 것은?" |

### 9.2 작업 중 — 변경 발생 시 재질문

작업 도중 **전략과 다른 구현이 필요한 상황**이 발생하면:

```
❌ 금지: 임의로 전략을 변경하고 계속 진행
✅ 필수: 변경 사유를 설명하고 사용자 승인 후 진행
```

단, 명백한 버그 수정·오타 수정은 즉시 처리 가능.

### 9.3 작업 완료 후 — 개발 일지 작성

작업이 끝나면 해당 파트의 개발 일지를 작성합니다.
작성 위치·형식·필수 항목은 **8절(파트별 개발 일지 작성 규칙)** 을 따릅니다.

### 9.4 전체 절차 요약

```
[작업 지시 수신]
      │
      ▼
[전략 제시 + 필수 질문 5개 (최소 3개)]
      │
      ▼
[사용자 답변 대기] ── 답변 전 작업 착수 금지
      │
      ▼
[구현 진행]
      │ 전략 변경 필요 시 → 사용자 승인 후 재개
      ▼
[작업 완료]
      │
      ▼
[해당 파트 개발 일지 작성] ── 구현 방식 + 리스크 포함
      │
      ▼
[다음 작업 대기]
```

### 9.5 금지 사항

| 번호 | 금지 사항 |
|------|---------|
| P-01 | 전략 제시 없이 즉시 코드 작성 |
| P-02 | 필수 질문 없이 착수 (질문 수 부족 포함) |
| P-03 | 사용자 답변 전 구현 시작 |
| P-04 | 전략 변경을 임의로 진행하고 사후 통보 |

---

---

## 10. 미래지향적 설계 원칙

> 이 프로젝트의 최종 목표는 자가 개선(self-improving) 멀티에이전트 연구 성과를 얻는 것입니다.
> 구현 편의만을 위한 단기적 설계는 추후 데이터 재수집·마이그레이션 비용으로 돌아옵니다.

### 10.1 데이터 설계 원칙

| 원칙 | 나쁜 예 | 좋은 예 |
|------|---------|---------|
| **컨텍스트 보존** | 성공/실패 여부만 저장 | `(question, answer, success, agent_id, project_id, timestamp)` 함께 저장 |
| **지수적 가중 평균** | 최근 결과로 단순 대체 | EMA (α=0.2) 적용 — 누적된 이력에 점진적 반영 |
| **교체 가능한 스토리지** | 구현체를 코드에 직접 결합 | Port 인터페이스 뒤에 숨겨 SQLite → Qdrant → Redis 전환 가능하게 |

### 10.2 적용 기준

새 스키마·어댑터·API를 설계할 때 아래 질문에 답합니다.

```
1. 이 데이터를 미래에 다시 학습 입력으로 쓸 수 있는가?
2. agent_id, project_id, timestamp 없이도 충분한가?  →  없다면 반드시 포함
3. 지금 단순히 구현이 편해서 선택한 것인가, 아니면 연구 목표에도 유리한가?
```

*이 파일의 변경은 전체 파트에 영향을 미치므로, 반드시 개발 일지에 변경 사유를 기록합니다.*

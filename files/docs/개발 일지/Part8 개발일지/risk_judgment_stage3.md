# Part 8 Stage 3-3 — 잔존 리스크 22건 판정 표

> 세션 가이드 §Stage 3 의 "C등급 잔존 리스크 일괄 검토" 산출물.
> 원 리스크 기록은 Part 6/7/8 해당 일지 §4를 참조.

## 판정 기준

| 판정 | 의미 | 후속 조치 |
|---|---|---|
| 유지 | 현재 상태가 운영상 수용 가능 또는 아키텍처 의도에 부합. 코드 수정 없이 종결 | 일지에 근거 기록 |
| 수정 | Stage 3-4 에서 구현 | 커밋 + 테스트 + 회귀 확인 |
| 이월 | v2.0 또는 별도 Phase 로 연기. Stage 3 범위 초과 | 세션 가이드에 이관 명시 |

E2E 실행 결과(`benchmarks/reports/e2e/todo/run-*.json`)와 각 항목의
"E2E 발현 여부" 를 교차 대조하여 판정.

---

## Part 6 이월 (R-04 / R-05 / R-06)

### R-04F — 키워드 lemma 기반 확장 누락
- **설명**: 키워드 사전이 정확 단어만 매칭. 굴절형(decide → decides, decided)은 miss.
- **현재 상태**: `knowledge_graph._KEYWORD_PATTERNS` 는 `re.compile` 캐시 + NFC 정규화 적용. lemma 확장 없음.
- **E2E 발현**: (pending) — Todo 요청에 굴절 키워드 포함 시 라우팅 품질 영향 여부
- **판정**: **유지**
- **근거**: lemma 확장은 형태소 분석기(nltk/spacy/kiwi) 신규 의존성 필요. Part 8 범위 초과. 라우팅 정확도는 E5/MPNET 임베딩 시맨틱 검색이 보완. v2.0 전문화 과제.

### R-04G — 단일 글자/약어 키워드 약화
- **설명**: R-04 word-boundary 정규식 적용 후 `"ci"` 같은 약어 매칭 약화.
- **현재 상태**: 현 사전에서 해당 케이스는 실질 영향 없음(CI 키워드는 `"continuous integration"` 경유 매칭).
- **E2E 발현**: 없음(예상) — 사용자 요청이 `"ci"` 단독 키워드 포함 시에만
- **판정**: **유지**
- **근거**: 원본 일지(4) §4 "매칭은 정상 작동. R-04 의도 자체라 부작용 아님"을 그대로 수락.

### R-04H — 타 모듈 substring 매칭 잠재 존재
- **설명**: 다른 코드에도 `if kw in text` 패턴이 있을 수 있음.
- **현재 상태**: 전체 grep 필요.
- **E2E 발현**: N/A(아키텍처 감사)
- **판정**: **유지**
- **근거**: 현재까지 추가 발견 없음. 코드 리뷰 체크리스트 항목으로만 관리.

### R-04I — Qdrant 저장 데이터 NFC 미정규화
- **설명**: 쿼리 측엔 NFC 있지만 저장 측엔 없음 → 외부 입력 NFD 저장 시 검색 miss.
- **현재 상태**: `knowledge_graph.py` NFC 적용. `qdrant_storage.add_qa` / `add_task_result` 는 NFC 미적용.
- **E2E 발현**: 없음(예상) — 모든 내부 생성 텍스트는 이미 NFC.
- **판정**: **유지**
- **근거**: R-05E 와 동일 문제의 다른 층. 외부 연동(Slack/이메일) 생길 때만 영향. Stage 3-4 에서 1줄 방어 추가는 가능하지만 관찰된 증상 없음 → v2.0 이월.

### R-05E — Qdrant 저장 NFC 정규화
- **설명**: R-04I와 동일 (Q&A/작업결과 저장 경로).
- **판정**: **유지** (R-04I 근거와 같음)

### R-06A — pre-commit 훅 미도입
- **설명**: black/isort/flake8/mypy 를 커밋 전에 자동 강제할 훅 없음.
- **현재 상태**: `.pre-commit-config.yaml` 없음. `.husky` 없음.
- **E2E 발현**: N/A(개발 프로세스 이슈)
- **판정**: **수정**
- **근거**: Stage 3-0 ~ 3-2½ 작업 중 black/isort 수정 반복 발생 → 실질 개발 마찰. pre-commit 설치 + 훅 설정으로 5줄 YAML로 해결. 작업 마찰 감소가 체감 영향 지표(세션 가이드 §핵심 원칙) 상위 기준에 부합.
- **Stage 3-4 마감 (2026-04-27)**: `.pre-commit-config.yaml` 신설(black/isort/flake8/mypy 4종 hook), `requirements-dev.txt` 에 `pre-commit>=3.0` 추가, `Makefile` `pre-commit-install` 타겟 추가, `.github/workflows/ci.yml` lint job 을 `pre-commit run --all-files` 호출로 교체. Q4=(d) 로컬 권고 + CI 강제 동시 적용. mypy hook 은 venv 의존성 충돌 회피 위해 `language: system` + venv 자동 분기. 사전 검증 `pre-commit run --all-files` 모든 hook 통과(N3 부재 확인).

### R-06B — `# noqa` 누적
- **설명**: 예외 주석이 리뷰 없이 늘어나는 리스크.
- **현재 상태**: `grep -c noqa src/` 결과 2건 (stage_gate 1, peer_review 1).
- **E2E 발현**: N/A(linting 위생)
- **판정**: **유지**
- **근거**: 현재 2건 수준으로 매우 낮음. 체크 메커니즘(정기 grep) 은 R-06A pre-commit 에 추후 통합 가능.

### R-06C — `_on_blocking_detected` 시그니처
- **설명**: 원 일지에서 방어적 기본값이 API 사용자 혼란 가능이라 우려.
- **현재 상태**: `stage_gate.py:265` `def _on_blocking_detected(self, event_type: str = "blocking.detected", payload: dict[str, object] | None = None)` — EventHandler 타입과 일치하는 형태.
- **E2E 발현**: 없음 — 현재 서명으로 이미 안정.
- **판정**: **유지**
- **근거**: Part 7 S1 에서 이미 시그니처 정리 완료. 추가 재설계 불필요.

---

## Part 7 이월 (R-07 / R-08 / R-09)

### R-07A — EmergencyMeeting inbox 샤딩 (회의별 가상 inbox)
- **설명**: 동시 다중 회의 실행 시 inbox 메시지 섞임 가능.
- **현재 상태**: `meeting_id = f"meeting_{uuid.uuid4().hex[:16]}"` 생성 (emergency_meeting.py:112) — 회의 ID 는 있으나 inbox 샤딩은 기존 `to=cto` 단일 큐 경유.
- **E2E 발현**: 없음 — Todo/Blog/Guestbook 단일 회의 흐름에선 동시 회의 없음.
- **판정**: **유지**
- **근거**: 관찰된 증상 없음. 동시 다중 프로젝트 지원은 PROJECT_PLAN §13.2 "v2.0 멀티 프로젝트 동시 진행"에서 다뤄질 주제.

### R-07B — prompts/meeting/vote.txt 템플릿 신설
- **설명**: 투표 응답 프롬프트가 인라인 문자열로만 존재.
- **현재 상태**: `src/application/prompts/meeting/` 디렉토리 없음. `src/application/prompts/peer_review/review.txt` 는 Stage 2 에서 신설됨.
- **E2E 발현**: Emergency Meeting 가 발생하면 영향 — Todo/Blog/Guestbook 에서 blocking 이 발생하지 않으면 관찰 불가.
- **판정**: **이월**
- **근거**: 프롬프트 외부화는 Stage 3 내 구현 가능하지만 E2E 3건이 blocking 을 거의 안 일으키는 단순 프로젝트라 "발현 기반 우선순위"에서 낮음. v2.0 프롬프트 엔지니어링 정비에 합쳐서 처리.

### R-07F — EmergencyMeeting 이전 inbox 메시지 오염
- **설명**: 연속 blocking 사이 큐 잔류 메시지 오염.
- **현재 상태**: R-07A 와 동일 인프라 제약.
- **판정**: **유지** (R-07A 와 묶음 처리)

### R-08A — 리뷰 severity 객관 기준
- **설명**: MINOR/MAJOR/CRITICAL 이 LLM 주관.
- **현재 상태**: `peer_review._parse_review` 가 `payload.get("severity", "MINOR")` — 응답 그대로 수용.
- **E2E 발현**: PeerReviewMode 기본 OFF 이므로 미발현.
- **판정**: **유지**
- **근거**: 기본 OFF 라 프로덕션 경로 미포함. 룰 기반 2차 검증은 리뷰 데이터 누적 후 v2.0 에서 통계로 도입이 합리적.

### R-08B — 리뷰 감사용 MessageQueue 알림
- **설명**: 감사 로그가 metric 외 없음.
- **현재 상태**: Coordinator 는 MessageQueue 미사용.
- **판정**: **유지**
- **근거**: MetricCollector 가 이미 review 수치를 수집. 감사 요구는 규정 대상 발생 시 추가.

### R-08D — EventBus exception isolation
- **설명**: 구독자 처리 실패가 메인 흐름에 전파.
- **현재 상태**: `event_bus.py:26-32` 이미 `try/except log.exception` 으로 격리됨 — **해결됨**.
- **판정**: **해결** (유지, 코드 이미 대응)
- **근거**: Stage 2 이전 어떤 시점에 격리 코드가 추가되어 R-08D 는 사실상 해결 상태. Stage 3 추가 작업 없이 일지에 "resolved" 표시.

### R-08F — DNAManager 캐시 asyncio.Lock
- **설명**: `load/update` 동시 호출 시 인메모리 캐시 race.
- **현재 상태**: `dna_manager.py._cache` 에 Lock 없음.
- **E2E 발현**: PeerReviewMode OFF → review 호출 없음 → 동시 `update_review_feedback` 없음. 실질 race 미발현.
- **판정**: **유지**
- **근거**: 실 SQLite 경로는 직렬이라 영향 작음. 캐시는 race 시에도 마지막 write 승 → 최악의 경우 EMA 한 단계 건너뜀. 관측 가능한 품질 영향 미검증.

### R-09A — DNAAwareSelector 초기 편향
- **설명**: 누적 데이터 없는 시작 시 알파벳순 쏠림.
- **현재 상태**: `_decay_k=5` 로 결정적 편향 제한. (reviewer_selector.py:129)
- **E2E 발현**: reviewer_selector_mode 기본 "fixed" 라 미발현.
- **판정**: **유지**
- **근거**: mode 가 fixed 로 기본 OFF 이고, dna_aware 사용 시에도 decay_k 튜닝으로 조정 가능. 당장 수정 필요성 없음.

### R-09C — rework 시 Task.dependencies 빈 리스트로 재구성
- **설명**: 의존성 자체가 변하면 놓침.
- **현재 상태**: `rework_scheduler.py:249` `dependencies=[]`.
- **E2E 발현**: rework 자체가 발현해야 영향 — PeerReviewMode OFF 이므로 미발현.
- **판정**: **유지**
- **근거**: rework 기능은 기본 OFF (rework_enabled=False 기본값) 이고, 활성화 시에도 "의존성 변화는 실무에서 드묾" (원 일지(3) §4 근거) 유지.

### R-09F — `task.completed` payload `rework_count` 리뷰어 선정 미반영
- **설명**: 이미 rework 된 task 가 또 리뷰어에게.
- **현재 상태**: payload 에 `rework_count` 포함 (shared_workspace.py:121). `reviewer_selector` 는 이 값 미참조.
- **E2E 발현**: 동일 (peer review OFF).
- **판정**: **이월**
- **근거**: rework-aware 선정은 Stage 3 추가 구현 가능하지만 peer review 자체가 기본 OFF 라 가치 관측 불가. v2.0 활성화 시점에 같이 처리.

### R-09G — Agent 인스턴스 재사용 상태 오염
- **설명**: `AgentFactory.create_team` 1회 호출 후 같은 인스턴스 재사용.
- **현재 상태**: DNAManager 는 immutable copy 반환으로 완화.
- **E2E 발현**: 영향 없음 — 원 일지 근거가 그대로 유효.
- **판정**: **유지**

---

## Part 8 Stage 2 이월 (R-11)

### R-11A — 부분 핫리로드
- **설명**: HOT_RELOADABLE 분류된 필드 중 일부(peer_review_*, reviewer_selector_*, rework_*, meeting_*)는 실제로는 coordinator `self._config` 가 init 시점에 캡처되어 런타임 변경 미반영.
- **현재 상태**: `peer_review.py:146` `self._config.mode` 등 — PeerReviewConfig 에서 읽음. PATCH 가 SystemConfig 를 바꿔도 coordinator 에 전파 안 됨. (반면 llm_concurrency_* 는 `LLMConcurrencyLimiter.update_limits()` 로 진짜 핫.)
- **E2E 발현**: 사용자가 런타임 중 PATCH → 효과 안 보이면 발현. Todo E2E 단독 실행엔 발현 경로 없음.
- **판정**: **수정** (범위 축소)
- **근거**: UI 배지 "즉시 적용" 이 실제로는 절반 거짓 → 사용자 혼란 직접 유발. Stage 3-4 에서 (a) 분류 재조정(실제로 핫이 아닌 필드는 RESTART_REQUIRED 로 강등) 또는 (b) 코디네이터들이 SystemConfig ref 를 들고 매번 재조회 — (a) 가 작고 안전. 수정 범위: config_mutation.py `HOT_RELOADABLE` 에서 peer_review_* / reviewer_selector_* / rework_* / meeting_* 제거. 5줄 변경.
- **Stage 3-4 마감 (2026-04-27)**: (a) 적용. `config_mutation.py` `HOT_RELOADABLE` 에서 8개 필드 제거(peer_review_mode/peer_review_critical_duration_sec/reviewer_selector_mode/rework_enabled/rework_max_attempts/meeting_response_timeout_sec/meeting_cto_max_retries/meeting_cto_retry_interval_sec). 자동으로 RESTART_REQUIRED 로 분류됨. `tests/unit/test_dashboard_routes.py` 분류 검증 갱신 + RESTART_REQUIRED PATCH 케이스 신규 테스트 추가. 13/13 dashboard routes 테스트 통과, 438/438 unit+integration 통과. Q2=(a) Flutter 시각 검증은 v1.0 release 후 demo 시점으로 이연(분류 enum 자동 반영이라 회귀 가능성 낮음). Q3=(b) BREAKING CHANGE 태그 미적용(메타데이터 분류 변경, 스키마 자체 변경 아님).

### R-11B — 별도 프로세스 대시보드 SharedWorkspace 미공유
- **설명**: `python main.py --dashboard` 와 `python main.py "<request>"` 를 두 터미널에서 동시에 열면 대시보드가 파이프라인 실행 인스턴스를 관찰 못 함.
- **현재 상태**: `_run_dashboard_server` 가 새 SharedWorkspace / DNAManager 인스턴스 생성 — 같은 SQLite DB 를 바라보지만 메모리 객체는 별개. EventBus 이벤트는 프로세스 경계 안 넘음.
- **E2E 발현**: 이번 E2E 는 단일 프로세스 test(TestClient) 라 미발현.
- **판정**: **이월**
- **근거**: 단일-프로세스 통합 또는 이벤트-DB polling 백엔드 추가가 필요 — 두 방식 모두 Stage 3 범위 초과. v2.0 "배포 아키텍처 정비" 로 이월.

### R-11D — WebSocket E2E 테스트 스코프 축소
- **설명**: TestClient 기반 broadcaster 단위 테스트만 있고 실제 uvicorn 서브프로세스 E2E 는 없음.
- **현재 상태**: Stage 3-2 에서 추가한 `tests/e2e/test_dashboard_live.py` 는 TestClient 로 auth/PATCH/WS snapshot+tick 통합 검증 — 스코프 확장됐지만 여전히 in-process.
- **E2E 발현**: 미발현 (현재 테스트 방식에선 애초에 검증 불가능).
- **판정**: **유지**
- **근거**: uvicorn subprocess + websockets 외부 client 로 띄우면 CI 플레이키니스 + 포트 관리 부담 증가. Stage 2 에서 Broadcaster 직접 fanout 테스트 + Stage 3 의 TestClient 통합 조합으로 "production 흐름의 핵심 경로" 커버됨.

---

## 신규 발견 (Stage 3 중)

### N1 — CTO decompose 60초 타임아웃
- **설명**: Todo E2E 1차 실행에서 `decompose_tasks` 가 기본 60s 타임아웃 초과.
- **판정**: **수정** (커밋 `99d3548` 에서 선행 완료)
- **근거**: 16GB M-series + qwen3:8b + gemma4:e4b 동시 로드 시 swap 으로 응답 시간 증가. 기본값 120/240/180 으로 상향 + SystemConfig 노출.

### N2 — 디스크 이전 후 Ollama 모델 미동기화 (Stage 3-4 발견)
- **설명**: 2026-04-26 프로젝트를 휴대 디스크(`/Volumes/ 개발(휴대)/프로젝트/compani_ai`) → 본 외장(`/Volumes/개발/compani_ai`) 회전 백업 이전 시, Ollama 모델은 `~/.ollama/models/` 에 별도 저장되어 함께 옮겨지지 않음. SystemConfig 기본 모델 3종(qwen3:8b/gemma4:e4b/llama3.2:3b) 모두 누락 상태로 E2E 재실행 시도 시 즉시 실패.
- **원인 분석**: `benchmarks/reports/e2e/todo/run-20260424T082508Z.json` 의 RED(`completion_pct=0`, `task_success=0`, `collab_success=100`) 결과는 **모델 누락이 진짜 원인일 가능성 높음**. CTO 전략 수립까지는 작은 응답으로 통과(collab=100), 실제 코드 생성(task_success=0)에서 모델 부재로 모두 실패하는 패턴과 일치. 일회성 swap 이슈가 아니라 환경 구성 이슈.
- **판정**: **운영 절차 이슈** (코드 변경 없음)
- **대응 (Stage 3-4)**:
  1. `~/.ollama/models` 를 `/Volumes/개발/.ollama/models` 로 심볼릭 링크 → 프로젝트와 같은 외장 볼륨에 두어 향후 동일 이슈 재발 방지(이전 시 같이 옮겨짐).
  2. 누락된 3종 모델 `ollama pull` 로 복구 (~17GB).
  3. v1.0 release 후 사용자 직접 E2E 재실행하여 GREEN 확인 — `risk_judgment_stage3.md` 에 결과 부록 갱신 예정.
- **재발 방지 권고 (RUNBOOK 갱신 후보)**: 다른 머신/볼륨으로 프로젝트 이전 시 `~/.ollama/models/` 디렉토리도 함께 이전 또는 재설치 단계 명시.

---

## 판정 요약

| 원 리스크 | 수정 | 유지 | 이월 | 해결(기존) |
|---|:---:|:---:|:---:|:---:|
| R-04F/G/H/I | 0 | 4 | 0 | 0 |
| R-05E | 0 | 1 | 0 | 0 |
| R-06A/B/C | 1 (R-06A) | 2 | 0 | 0 |
| R-07A/B/F | 0 | 2 | 1 (R-07B) | 0 |
| R-08A/B/D/F | 0 | 3 | 0 | 1 (R-08D) |
| R-09A/C/F/G | 0 | 3 | 1 (R-09F) | 0 |
| R-11A/B/D | 1 (R-11A) | 1 (R-11D) | 1 (R-11B) | 0 |
| **합계** | **2** | **16** | **3** | **1** |

**+ 신규 N1 (decompose 타임아웃) 수정 완료** → Stage 3-4 순 작업 = **2건** (R-06A pre-commit 훅 도입, R-11A HOT_RELOADABLE 분류 재조정).

**+ Stage 3-4 신규 N2 (디스크 이전 후 모델 미동기화) 운영 절차 이슈로 분류** — 코드 변경 없이 심볼릭 링크 + 모델 재 pull 로 복구.

## Stage 3-4 마감 상태 (2026-04-27)

| 항목 | 상태 |
|---|---|
| R-06A pre-commit 훅 도입 | ✅ 구현 + CI 적용 |
| R-11A HOT_RELOADABLE 분류 재조정 | ✅ 구현 + 테스트 갱신 |
| `make test` 회귀 | ✅ 438 passed |
| `pre-commit run --all-files` | ✅ black/isort/flake8/mypy 4종 통과 |
| Todo E2E 재실행 GREEN 검증 | ⏳ N2 복구 후 v1.0 release 직후 사용자 재실행 |
| Part 8 종료 선언 | ✅ 본 문서 마감 시점 |

---

*Stage 3-3 draft → Stage 3-4 마감 (2026-04-27). E2E GREEN 재검증은 N2 운영 복구 후 부록 갱신 예정.*

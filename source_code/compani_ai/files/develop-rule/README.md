# develop-rule — AI 코딩 규칙 디렉토리

> Codex·Claude 등 AI가 이 프로젝트를 작업할 때 반드시 준수해야 하는 규칙 모음입니다.
> **작업 시작 전 00_COMMON_RULES.md를 항상 먼저 읽으세요.**

---

## 파일 목록

| 파일 | 대상 파트 | 핵심 내용 |
|------|---------|---------|
| `00_COMMON_RULES.md` | **전체 공통** | 아키텍처 계층, 코드 스타일, 관측성, 테스트, 커밋, 심각도 분류 기준 |
| `01_ORCHESTRATION_RULES.md` | CTO Agent | 전략 수립, 작업 분해, LLM 재시도, 오케스트레이션 흐름 |
| `02_AGENT_EXECUTION_RULES.md` | SLM Agents | 코드 생성, 의존성 대기, Q&A, 응답 파싱 |
| `03_COLLABORATION_RULES.md` | WorkSpace·MessageQueue·EventBus | 상태 전이, 메시지 라우팅, 이벤트 발행/구독 |
| `04_INFRASTRUCTURE_RULES.md` | Adapters·인프라 | Ollama 호출, SQLite, 파일 저장, 환경변수 |
| `05_FRONTEND_RULES.md` | CEO 대시보드·Frontend SLM | Flutter/React 코드 기준, API 연동 |
| `06_MLOPS_RULES.md` | MLOps Agent·CI/CD | Dockerfile, docker-compose, GitHub Actions, 배포 스크립트 |

---

## 규칙 우선순위

```
00_COMMON_RULES   (최우선 — 항상 적용)
        ↓
파트별 규칙       (해당 파트 작업 시 추가 적용)
```

파트별 규칙이 공통 규칙과 충돌하면 **공통 규칙이 우선**합니다.

---

## 작업 전 필수 확인 순서

```
1. 00_COMMON_RULES.md          읽기
2. 해당 파트 규칙 파일           읽기
3. docs/개발 일지/초기 아키텍처 설계/개발 일지(4).md   현재 전략 확인
4. docs/04_SYSTEM_ARCHITECTURE.md  SSOT 확인
5. 작업 시작
```

---

## 규칙 파일 업데이트 기준

- 새로운 공통 패턴이 2회 이상 반복 발생 시 → `00_COMMON_RULES.md` 추가
- 특정 파트에서만 필요한 규칙 → 해당 파트 파일에 추가
- 규칙 변경 시 → 다음 개발 일지에 변경 사유 기록

---

*마지막 업데이트: 2026-02-21 | 다음 리뷰: Part 1 완료 후*

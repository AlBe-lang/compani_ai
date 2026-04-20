# 멀티 에이전트 AI 개발 시스템 — 공식 문서

> 최종 업데이트: 2026-02-21

---

## 문서 목록

| 번호 | 파일 | 내용 | 분량 |
|------|------|------|------|
| 01 | [기획안](./01_PROJECT_PLAN.md) | 프로젝트 개요, 문제 정의, 솔루션, MVP 계획, 로드맵, KPI, 비용 분석 | ~600줄 |
| 02 | [시스템 파이프라인](./02_SYSTEM_PIPELINE.md) | 개발/실행/협업/CI-CD/모니터링/배포 파이프라인 전체 | ~700줄 |
| 03 | [ERD](./03_ERD.md) | 12개 엔티티 상세 정의, 전체 ASCII ERD, DDL 스키마, 인덱스 전략 | ~600줄 |
| 04 | [시스템 아키텍처](./04_SYSTEM_ARCHITECTURE.md) | 4계층 아키텍처, 컴포넌트 설계, 보안/성능/확장성, Phase별 진화 | ~650줄 |

---

## 빠른 참조

### 이 시스템이 무엇인가?
CTO Agent (Llama 3.1 70B) + 역할별 SLM 에이전트 3개(Frontend, Backend, MLOps)가
실시간 협업하여 소프트웨어 프로젝트를 자동 생성하는 완전 로컬 AI 시스템

### 핵심 수치
- 비용: $0 (완전 로컬, 오픈소스)
- 목표 완성도: 60–70% (MVP 기준)
- MVP 기간: 3주
- 전체 개발: 3–4개월 (8단계)
- 하드웨어: Mac Mini M4 16GB

### 기술 스택 요약
```
LLM:   Ollama + Llama 3.1 70B (CTO) + Phi-3.5 (SLM)
언어:  Python 3.10+, asyncio
DB:    SQLite → Redis (Phase3) → Qdrant (Phase4)
파인튜닝: Unsloth LoRA (Phase2)
UI:    Flutter Web CEO 대시보드 (Phase8)
```

### 8단계 로드맵 요약
```
Phase 1 (1–2주)  : 기본 에이전트 인프라
Phase 2 (2–3주)  : SLM 역할별 파인튜닝
Phase 3 (2주)    : Shared Workspace (Redis)
Phase 4 (2주)    : Communication Hub + 지식 그래프
Phase 5 (1–2주)  : Stage Gate 집단 지성 검증
Phase 6 (2주)    : DNA 자가 진화 시스템
Phase 7 (2주)    : 고급 협업 (피어 리뷰, 긴급 회의)
Phase 8 (2–3주)  : 최종 통합 + CEO 대시보드
```

---

*이 문서들은 Claude CLI와 함께 사용하도록 설계되었습니다.*

# Todo REST API

CompaniAI 멀티에이전트 시스템이 자동 생성한 Todo 관리 REST API.

## 구성

- **Backend** (FastAPI + SQLAlchemy + JWT)
- **Frontend** (React + TypeScript + Vite)
- **Deploy** (Docker + GitHub Actions)

## 빠른 시작

```bash
# 백엔드
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# 프론트엔드
cd frontend
npm install
npm run dev

# Docker 통합
docker-compose up
```

## 디렉토리 구조

```
.
├── backend/
│   ├── main.py              # FastAPI app entry
│   ├── models.py            # Pydantic + SQLAlchemy
│   ├── database.py          # SQLite/Postgres setup
│   ├── auth.py              # JWT auth middleware
│   └── routers/
│       └── todos.py         # CRUD endpoints
├── frontend/
│   ├── package.json
│   ├── index.html
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       └── components/
│           └── TodoItem.tsx
└── deploy/
    ├── Dockerfile
    ├── docker-compose.yml
    └── .github/
        └── workflows/
            └── ci.yml
```

## 주요 기능

- ✅ Todo CRUD (생성/조회/수정/삭제)
- ✅ JSON Merge Patch (RFC 7396) 부분 업데이트
- ✅ JWT 기반 인증
- ✅ 사용자별 Todo 분리
- ✅ Docker 컨테이너화
- ✅ GitHub Actions CI

## 에이전트 협업 기록

이 프로젝트는 다음 5개 task로 분해되어 자동 생성되었습니다:

| Task | 담당 | 산출물 |
|------|------|-------|
| T-001 | Backend | FastAPI Todo CRUD endpoints |
| T-002 | Frontend | React Todo list UI |
| T-003 | MLOps | Dockerfile + docker-compose |
| T-004 | Backend | JWT auth middleware |
| T-005 | MLOps | GitHub Actions CI |

피어 리뷰: T-001(backend) → frontend reviewer (PASS, MINOR — 201 status code 권장)

생성: CompaniAI v1.1

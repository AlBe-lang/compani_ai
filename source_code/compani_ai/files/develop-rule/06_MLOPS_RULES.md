# MLOps 규칙 (MLOPS RULES)

> 대상 파트: **MLOps Agent + 개발 인프라 파이프라인**
> 레이어 위치: `adapters/`, `.github/workflows/`, `deploy/`
> 공통 규칙(`00_COMMON_RULES.md`)을 반드시 먼저 읽으세요.

---

## 1. 역할 이중 정의

```
관점 A: MLOps Agent가 외부 프로젝트에 생성하는 인프라 코드 기준
  → Dockerfile, docker-compose, GitHub Actions, 배포 스크립트

관점 B: 본 시스템(멀티 에이전트 시스템) 자체의 CI/CD 및 운영 규칙
  → 이 프로젝트를 빌드·테스트·배포하는 파이프라인
```

---

## 2. MLOps Agent 생성 코드 기준 (관점 A)

### 2.1 Dockerfile 기준

```dockerfile
# ✅ 올바른 Dockerfile
FROM python:3.10-slim AS base

# 의존성만 먼저 복사 (레이어 캐시 최적화)
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# 실행 유저 — root 금지
RUN useradd -m appuser
USER appuser

# 포트 노출 최소화 (실제 사용 포트만)
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**필수 체크리스트**:
- [ ] `root` 유저로 실행 금지 (`USER appuser` 필수)
- [ ] `--no-cache-dir` 옵션으로 이미지 크기 최소화
- [ ] 의존성 레이어와 소스 레이어 분리 (캐시 효율)
- [ ] `EXPOSE`는 실제 사용 포트만
- [ ] `.dockerignore` 파일 함께 생성

### 2.2 .dockerignore 필수 포함 항목

```
.env
.git
.github
__pycache__
*.pyc
*.pyo
.pytest_cache
venv/
*.egg-info/
dist/
build/
outputs/
data/
logs/
```

### 2.3 docker-compose.yml 기준

```yaml
# ✅ 올바른 docker-compose.yml
version: '3.8'

services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL}   # 환경변수 — 하드코딩 금지
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  db_data:
```

**필수 체크리스트**:
- [ ] 민감 정보는 환경변수 참조 (`${VAR}`) — 하드코딩 금지
- [ ] `healthcheck` 설정 필수 (모든 서비스)
- [ ] `depends_on`에 `condition: service_healthy` 사용
- [ ] `restart: unless-stopped` 설정
- [ ] 볼륨은 명명 볼륨(named volume) 사용

### 2.4 GitHub Actions CI 기준

```yaml
# ✅ 올바른 CI 구조
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'           # 캐시 활성화 필수

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Lint
        run: |
          black --check .
          flake8 .
          mypy .

      - name: Test
        run: pytest tests/unit tests/integration -v --cov=. --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
```

**필수 체크리스트**:
- [ ] `actions/checkout`, `actions/setup-python` 최신 버전(v4+) 사용
- [ ] pip 캐시 활성화
- [ ] lint → test 순서 고정
- [ ] 커버리지 업로드

### 2.5 생성 결과물 필수 포함 항목

MLOps Agent TaskResult 필수 구성:

```json
{
  "approach": "Docker multi-stage build + GitHub Actions CI",
  "code": {
    "Dockerfile": "...",
    "docker-compose.yml": "...",
    ".dockerignore": "...",
    ".github/workflows/ci.yml": "...",
    ".env.example": "..."
  },
  "files": [...],
  "dependencies": [],
  "setup_commands": ["docker-compose up --build"],
  "ports_exposed": [8000],
  "env_vars_required": ["DATABASE_URL", "SECRET_KEY"]
}
```

`env_vars_required`는 Backend 에이전트와 공유하여 환경변수 누락을 방지합니다.

---

## 3. 본 시스템 CI/CD 규칙 (관점 B)

### 3.1 GitHub Actions 파이프라인 구조

```
Push / PR
    │
    ▼
[Job 1: lint]          black, flake8, mypy, isort
    │ 성공
    ▼
[Job 2: unit-test]     tests/unit/ — MockLLMProvider 사용
    │ 성공
    ▼
[Job 3: integration]   tests/integration/ — MockLLMProvider 사용
    │ 성공
    ▼
[Job 4: build]         패키지 빌드 및 아티팩트 업로드
```

- E2E 테스트는 CI에서 실행하지 않습니다 (실제 Ollama 필요)
- E2E는 로컬에서 `make test-e2e`로 수동 실행

### 3.2 브랜치 보호 규칙

```
main 브랜치:
  - 직접 push 금지
  - PR 필수
  - CI 전체 통과 후 머지 허용
  - 1인 이상 리뷰 (팀 확장 시)
```

### 3.3 로컬 실행 명령 표준

```makefile
# Makefile — 모든 명령 여기서 관리

.PHONY: setup lint format test test-fast test-e2e deploy

setup:
	bash deploy/setup.sh

lint:
	black --check . && flake8 . && mypy . && isort --check .

format:
	black . && isort .

test:
	pytest tests/unit tests/integration -v

test-fast:
	pytest tests/unit -v

test-e2e:
	pytest tests/e2e -v -m slow

deploy:
	bash deploy/run.sh
```

---

## 4. 환경별 설정 관리

| 환경 | 설정 방법 | Ollama 모델 |
|------|---------|-----------|
| `development` | `.env` + SQLite 인메모리 | 실제 모델 또는 Mock |
| `testing` | `.env.test` + SQLite 임시 파일 | MockLLMProvider |
| `production` | 환경변수 직접 주입 | 실제 모델 (70B) |

```python
# config.py
import os
from enum import Enum

class Env(Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"

ENV = Env(os.getenv("APP_ENV", "development"))
```

---

## 5. 본 시스템 배포 스크립트 규칙

```bash
#!/bin/bash
# deploy/run.sh

set -euo pipefail    # 오류 즉시 종료, 미정의 변수 오류, 파이프 오류 전파

# 1. 환경 확인
if ! command -v ollama &>/dev/null; then
    echo "[ERROR] Ollama가 설치되어 있지 않습니다." >&2
    exit 1
fi

# 2. 필요 모델 확인
REQUIRED_MODELS=("llama3.1:70b" "phi3.5" "llama3.2:3b")
for model in "${REQUIRED_MODELS[@]}"; do
    if ! ollama list | grep -q "$model"; then
        echo "[INFO] 모델 다운로드 중: $model"
        ollama pull "$model"
    fi
done

# 3. DB 초기화 (idempotent)
python -c "import asyncio; from adapters.sqlite_storage import SQLiteStorage; \
           asyncio.run(SQLiteStorage(db_path='data/workspace.db').init())"

# 4. 실행
python main.py
```

**필수 규칙**:
- `set -euo pipefail` 항상 첫 줄
- 모든 echo 메시지에 `[INFO]` / `[ERROR]` 접두어
- 에러는 `stderr`로 출력 (`>&2`)
- 스크립트는 **멱등성(idempotent)** 보장 — 여러 번 실행해도 동일 결과

---

## 6. 보안 규칙

```
포트 최소 노출:
  개발: 8000 (API), 11434 (Ollama — localhost only)
  운영: 8000만 외부 노출, 나머지 내부망

민감 정보:
  - .env 파일 git 커밋 절대 금지
  - 로그에 비밀번호·토큰 출력 금지
  - Docker 이미지에 .env 포함 금지

네트워크:
  - 기본 완전 로컬 (외부 네트워크 불필요)
  - 외부 연동 시 명시적으로 개발 일지에 기록
```

---

## 7. 금지 사항 (MLOps 전용)

| 번호 | 금지 사항 |
|------|---------|
| M-01 | Dockerfile에서 `root` 유저로 실행 |
| M-02 | docker-compose에 민감 정보 하드코딩 |
| M-03 | `healthcheck` 없는 서비스 정의 |
| M-04 | 배포 스크립트에 `set -e` 미적용 |
| M-05 | CI에서 E2E 테스트 실행 (실제 Ollama 필요) |
| M-06 | `.env` 파일 git 추적 |
| M-07 | 멱등성 미보장 배포 스크립트 |
| M-08 | 최신 버전이 아닌 GitHub Actions 사용 (v4 미만) |

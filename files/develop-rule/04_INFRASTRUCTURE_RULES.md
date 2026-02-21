# 인프라·어댑터 규칙 (INFRASTRUCTURE RULES)

> 대상 파트: **Adapters / Infrastructure Layer**
> 레이어 위치: `adapters/ollama_provider.py`, `adapters/sqlite_storage.py`, `adapters/redis_cache.py`
> 공통 규칙(`00_COMMON_RULES.md`)을 반드시 먼저 읽으세요.

---

## 1. 역할 정의

인프라·어댑터 레이어는 **외부 시스템과의 연결을 전담**합니다.

```
담당:
  - Ollama API 호출 (LLM 실행)
  - SQLite CRUD (영속화)
  - Redis 캐시 읽기/쓰기 (Phase 3+)
  - Qdrant 벡터 DB 연동 (Phase 4+)
  - 파일 시스템 입출력 (결과물 저장)

담당하지 않는 것:
  - 비즈니스 로직 판단
  - 에이전트 간 통신 중계
  - 전략 수립 또는 작업 분해
```

모든 어댑터는 `domain/ports.py`에 정의된 **인터페이스를 구현**하는 형태로 작성합니다.

---

## 2. OllamaProvider 규칙

### 2.1 기본 구조

```python
# adapters/ollama_provider.py

class OllamaProvider:
    """LLMProvider Protocol 구현체"""

    BASE_URL: str = "http://localhost:11434"
    TIMEOUT_SEC: int = 300

    def __init__(self, base_url: str, config: OllamaConfig) -> None:
        self._base_url = base_url
        self._config = config
        self._session: aiohttp.ClientSession | None = None

    async def generate(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        async with self._session.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self.TIMEOUT_SEC),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise AdapterError(
                    ErrorCode.E_LLM_UNAVAILABLE,
                    detail=f"status={resp.status}, body={body[:200]}"
                )
            data = await resp.json()
            return data["message"]["content"]
```

### 2.2 연결 관리 규칙

```python
# ✅ 세션은 컨텍스트 매니저로 관리
async with OllamaProvider(base_url=...) as provider:
    result = await provider.generate(...)

# ❌ 금지 — 요청마다 세션 새로 생성
async def generate(self, ...):
    async with aiohttp.ClientSession() as session:  # 매 호출마다 생성 — 비효율
        ...
```

- `ClientSession`은 인스턴스 생명주기 동안 **1개만 유지**
- `__aenter__` / `__aexit__`로 명시적 관리

### 2.3 모델 상태 확인

```python
async def health_check(self) -> bool:
    """Ollama 서버 및 필요 모델 존재 여부 확인"""
    try:
        async with self._session.get(
            f"{self._base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status != 200:
                return False
            data = await resp.json()
            available = [m["name"] for m in data.get("models", [])]
            return self._config.required_models_available(available)
    except Exception:
        return False
```

애플리케이션 시작 시 반드시 `health_check()` 호출 후 False면 즉시 종료합니다.

### 2.4 Ollama 관련 금지 사항

| 번호 | 금지 사항 |
|------|---------|
| I-01 | `stream: true` 응답을 파싱 없이 그대로 반환 |
| I-02 | 타임아웃 300초 이상 설정 (메모리 고갈 위험) |
| I-03 | 모델명을 코드에 하드코딩 (config에서 주입) |
| I-04 | 동시에 2개 이상 70B 모델 호출 (OOM 위험) |

---

## 3. SQLiteStorage 규칙

### 3.1 기본 구조

```python
# adapters/sqlite_storage.py

class SQLiteStorage:
    """StoragePort Protocol 구현체"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """DB 초기화 — 반드시 앱 시작 시 1회 호출"""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._run_migrations()

    async def save(self, item: WorkItem) -> None: ...
    async def load(self, item_id: str) -> WorkItem | None: ...
    async def update(self, item: WorkItem) -> None: ...
    async def query(self, sql: str, params: tuple = ()) -> list[dict]: ...
```

### 3.2 마이그레이션 규칙

```
adapters/migrations/
├── 001_initial_schema.sql
├── 002_add_retry_count.sql
└── 003_add_agent_dna.sql
```

- 마이그레이션 파일은 **번호 순서대로** 실행
- 기존 마이그레이션 파일 수정 금지 — 새 파일로 추가
- 스키마 변경 시 `BREAKING CHANGE` 커밋 태그 필수

### 3.3 트랜잭션 규칙

```python
# ✅ 복수 쓰기는 트랜잭션으로 묶음
async with self._conn.execute("BEGIN"):
    await self._conn.execute("INSERT INTO work_items ...", params1)
    await self._conn.execute("INSERT INTO task_results ...", params2)
    await self._conn.execute("COMMIT")

# ❌ 금지 — 각각 개별 커밋 (일부 성공·실패 상태 발생)
await self._conn.execute("INSERT INTO work_items ...")
await self._conn.execute("INSERT INTO task_results ...")
```

### 3.4 Raw SQL 규칙

```python
# ✅ 파라미터 바인딩 필수 (SQL 인젝션 방지)
await self._conn.execute(
    "SELECT * FROM work_items WHERE id = ?", (item_id,)
)

# ❌ 금지 — f-string으로 SQL 조합
await self._conn.execute(f"SELECT * FROM work_items WHERE id = '{item_id}'")
```

---

## 4. 파일 시스템 규칙

### 4.1 결과물 저장 경로 구조

```
outputs/
└── {project_name}-{run_id}/
    ├── frontend/
    │   ├── {component}.jsx   또는 .dart
    │   └── ...
    ├── backend/
    │   ├── main.py
    │   └── ...
    ├── mlops/
    │   ├── Dockerfile
    │   └── docker-compose.yml
    └── README.md              ← 자동 생성
```

### 4.2 파일 저장 규칙

```python
# ✅ 올바른 파일 저장
async def save_result_files(self, result: TaskResult, base_dir: Path) -> list[Path]:
    saved = []
    for file_info in result.files:
        file_path = base_dir / file_info.path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # 인코딩 명시 필수
        file_path.write_text(file_info.content, encoding="utf-8")
        saved.append(file_path)
    return saved
```

- 인코딩은 항상 `utf-8` 명시
- 경로 구성 시 `pathlib.Path` 사용 (`os.path.join` 지양)
- 기존 파일 덮어쓰기 전 로그 기록

### 4.3 README 자동 생성 필수 항목

```markdown
# {project_name}

## 실행 방법
## 프로젝트 구조
## 기술 스택
## 생성 정보 (run_id, 생성 시각, 소요 시간)
```

---

## 5. Redis 캐시 규칙 (Phase 3+)

### 5.1 캐시 키 네이밍

```
work_item:{item_id}          WorkItem 상태
agent_status:{agent_id}      에이전트 현재 상태
run_metrics:{run_id}         실행 메트릭
```

### 5.2 TTL 설정 필수

```python
# ✅ 모든 캐시 키에 TTL 설정
await redis.setex(f"work_item:{item_id}", 3600, json_data)   # 1시간

# ❌ 금지 — TTL 없는 영구 캐시
await redis.set(f"work_item:{item_id}", json_data)
```

---

## 6. 환경변수 관리 규칙

```
# .env (gitignore에 포함 — 실제 값)
OLLAMA_BASE_URL=http://localhost:11434
CTO_MODEL=llama3.1:70b
FRONTEND_MODEL=phi3.5
BACKEND_MODEL=phi3.5
MLOPS_MODEL=llama3.2:3b
DB_PATH=data/workspace.db
LOG_LEVEL=INFO
REDIS_URL=redis://localhost:6379   # Phase 3+

# .env.example (git 추적 — 키만, 값 없음)
OLLAMA_BASE_URL=
CTO_MODEL=
...
```

- `.env` 파일은 절대 git에 커밋하지 않습니다
- 새 환경변수 추가 시 `.env.example`에도 반드시 추가

---

## 7. 로그 규칙 (인프라 전용 이벤트)

```python
# Ollama
log.info("ollama.call",     model=model, tokens_in=prompt_tokens)
log.info("ollama.response", model=model, tokens_out=output_tokens, duration_sec=d)
log.error("ollama.error",   model=model, error_code=e.code, status=resp.status)

# SQLite
log.debug("db.save",   table="work_items", item_id=item.id)
log.debug("db.load",   table="work_items", item_id=item_id, found=item is not None)
log.error("db.error",  table=table, error_code=e.code, detail=str(e))

# FileSystem
log.info("fs.save",    path=str(file_path), size_bytes=len(content))
```

---

## 8. 금지 사항 (인프라 전용)

| 번호 | 금지 사항 |
|------|---------|
| I-05 | 어댑터 안에 비즈니스 로직 작성 |
| I-06 | SQL 파라미터 f-string 조합 |
| I-07 | 마이그레이션 파일 소급 수정 |
| I-08 | TTL 없는 Redis 키 생성 |
| I-09 | `.env` 파일 git 커밋 |
| I-10 | 동시에 복수의 70B 모델 로드 |
| I-11 | 파일 저장 시 인코딩 미지정 |
| I-12 | health_check() 없이 Ollama 호출 시작 |

# RUNBOOK — ErrorCode 대응 절차

> 런타임에서 발생하는 `ErrorCode` 각각에 대한 1차 대응 절차를 기술합니다.
> 대응 후에도 재발 시 해당 코드를 이슈로 등록하세요.

---

## LLM 관련

### `E-LLM-TIMEOUT`
**증상**: LLM generate 호출이 `timeout_sec`(기본 90초) 내에 응답하지 않아 SLMAgentError 발생.

**원인**: Ollama 프로세스가 모델을 메모리에 올리는 중 또는 과부하.

**대응**:
1. `ollama ps` — 현재 로드된 모델 확인
2. 메모리가 부족하면 `ollama stop <model>` 후 재시도
3. `SLMConfig.timeout_sec` 값을 높여서 (`120~180`) 재실행

### `E-LLM-UNAVAILABLE`
**증상**: Ollama API `/api/chat` 응답 status가 200이 아님.

**대응**:
1. `curl http://localhost:11434/api/tags` 로 서버 상태 확인
2. `ollama serve` 재실행
3. 모델 존재 여부 확인: `ollama list`

### `E-LLM-MODEL-MISSING`
**증상**: `health_check()` 에서 required_models 중 하나가 Ollama에 없음.

**대응**:
```bash
ollama pull llama3.1:8b
ollama pull gemma4:e4b
ollama pull llama3.2:3b
```

---

## 파싱 관련

### `E-PARSE-JSON`
**증상**: LLM 응답이 유효한 JSON이 아님. `json-repair` 후에도 실패.

**대응**: LLM이 마크다운 코드 펜스를 포함하거나 JSON 외 텍스트를 반환한 경우.
- `max_retries` 내 재시도 자동 처리됨
- 반복 실패 시 해당 에이전트의 `system_prompt`를 강화 (JSON only 명시)

### `E-PARSE-SCHEMA`
**증상**: JSON 파싱은 성공했으나 Pydantic 스키마 검증 실패 (`files` 필드 누락 등).

**대응**: LLM 응답의 `files` 배열에 `name/path/content/type` 필드가 누락된 경우.
- 프롬프트에 필수 필드 예시 추가

### `E-PARSE-EMPTY`
**증상**: LLM 응답이 코드 펜스 제거 후 빈 문자열.

**대응**: 모델이 응답 길이 제한에 걸린 경우. `max_tokens` 확인 후 증가.

---

## 의존성 관련

### `E-DEPS-BLOCKED`
**증상**: 의존 태스크가 FAILED 또는 BLOCKED 상태.

**대응**:
- 의존 태스크의 로그를 확인하여 근본 원인 파악
- 실패한 태스크만 재실행 (파이프라인 부분 재개)

### `E-DEPS-TIMEOUT`
**증상**: 의존 태스크가 `dep_timeout_sec`(기본 300초) 내에 완료되지 않음.

**대응**:
1. 의존 에이전트가 실행 중인지 확인
2. 데드락 여부 점검 (A→B, B→A 상호 의존)
3. `dep_timeout_sec` 조정 후 재실행

---

## 저장 관련

### `E-STORAGE-READ` / `E-STORAGE-WRITE`
**증상**: SQLite 쿼리 실패.

**대응**:
1. `data/compani.db` 파일 존재 및 권한 확인
2. DB 잠금 여부 확인: `lsof | grep compani.db`
3. WAL 모드 활성화 확인: `PRAGMA journal_mode;` → 반드시 `wal`

---

## 시스템 관련

### `E-SYSTEM-CONFIG`
**증상**: AgentFactory 또는 SystemConfig 초기화 실패.

**대응**: `SystemConfig` 필드 값 및 환경변수(`.env`) 확인.

### `E-SYSTEM-UNKNOWN`
**증상**: 분류되지 않은 예외가 `BaseSLMAgent.execute_task` 에서 캐치됨.

**대응**: 로그의 `detail` 필드에서 원본 예외 확인 후 적절한 ErrorCode 신규 등록 검토.

---

## 빠른 참조

| ErrorCode | 심각도 | 자동 재시도 | 주요 원인 |
|-----------|--------|------------|---------|
| E-LLM-TIMEOUT | A | ❌ | Ollama 과부하 |
| E-LLM-UNAVAILABLE | S | ❌ | Ollama 미실행 |
| E-PARSE-JSON | B | ✅ (max_retries) | LLM 응답 포맷 불량 |
| E-PARSE-SCHEMA | B | ✅ (max_retries) | 필수 필드 누락 |
| E-DEPS-BLOCKED | A | ❌ | 상위 태스크 실패 |
| E-DEPS-TIMEOUT | A | ❌ | 의존 태스크 지연 |
| E-STORAGE-READ | A | ❌ | DB 접근 불가 |
| E-SYSTEM-UNKNOWN | A | ❌ | 미분류 예외 |

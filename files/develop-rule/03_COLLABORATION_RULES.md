# 협업 레이어 규칙 (COLLABORATION RULES)

> 대상 파트: **Shared Workspace / MessageQueue / EventBus**
> 레이어 위치: `application/workspace.py`, `application/message_queue.py`, `application/event_bus.py`
> 공통 규칙(`00_COMMON_RULES.md`)을 반드시 먼저 읽으세요.

---

## 1. 역할 정의

협업 레이어는 에이전트 간 **간접 통신의 유일한 경로**입니다.

```
에이전트 A → 에이전트 B  직접 호출   ❌ 금지
에이전트 A → MessageQueue → 에이전트 B  ✅ 필수

WorkSpace    : 작업 상태 공유, 의존성 추적, 이벤트 브로드캐스트
MessageQueue : 에이전트 간 Q&A 및 알림 비동기 전달
EventBus     : 상태 변경 이벤트 발행/구독 (관찰자 패턴)
```

---

## 2. WorkSpace 규칙

### 2.1 WorkItem 상태 전이 — 허용 경로만 허용

```
PLANNED → IN_PROGRESS → DONE
                      → FAILED
        → WAITING     → IN_PROGRESS  (의존성 해소 시)
IN_PROGRESS → BLOCKED → IN_PROGRESS  (블로킹 해소 시)
```

허용되지 않은 전이 시 `WorkspaceError` 발생:
```
예: DONE → IN_PROGRESS  ❌
예: FAILED → DONE       ❌
```

### 2.2 WorkSpace 접근 규칙

```python
# ✅ 허용 — 인터페이스(Port)를 통한 접근
class SimpleSLM:
    def __init__(self, workspace: WorkSpacePort, ...): ...

# ❌ 금지 — 구현체 직접 참조
class SimpleSLM:
    def __init__(self, workspace: SharedWorkspace, ...): ...  # 구현체 직접 참조
```

WorkSpace 구현체(`SharedWorkspace`)는 `adapters/` 레이어에서만 직접 사용합니다.
`application/` 레이어는 반드시 `WorkSpacePort` 인터페이스를 사용합니다.

### 2.3 인메모리 캐시 규칙

```python
class SharedWorkspace:
    def __init__(self, storage: StoragePort):
        self._cache: dict[str, WorkItem] = {}  # 인메모리 캐시
        self._storage = storage                 # 영속화 레이어

    async def get(self, item_id: str) -> WorkItem | None:
        # 캐시 우선 조회
        if item_id in self._cache:
            return self._cache[item_id]
        # 캐시 미스 시 DB 조회 후 캐시 갱신
        item = await self._storage.load(item_id)
        if item:
            self._cache[item_id] = item
        return item

    async def update(self, item: WorkItem) -> None:
        item.updated_at = datetime.utcnow()
        self._cache[item.id] = item          # 캐시 갱신
        await self._storage.save(item)        # DB 동기화
        await self._event_bus.publish(        # 이벤트 발행
            WorkItemUpdatedEvent(item=item)
        )
```

**캐시 무효화 조건**: 프로세스 재시작 시 전체 무효화 (DB에서 재로드)

### 2.4 블로킹 감지 규칙

```python
async def detect_blocking(self) -> list[WorkItem]:
    """
    status == BLOCKED 인 항목을 반환.
    감지 즉시 EventBus로 BlockingDetectedEvent 발행.
    자동 회의 소집 등의 처리는 EventBus 구독자가 담당.
    WorkSpace는 감지와 발행만 담당.
    """
```

---

## 3. MessageQueue 규칙

### 3.1 메시지 라우팅 우선순위

```
1순위: KnowledgeGraph 기반 라우팅 (Phase 4+)
       — expertise_level이 가장 높은 에이전트에게 전달

2순위: 키워드 기반 라우팅 (MVP)
       "api", "database", "sql", "endpoint"  → backend
       "ui", "component", "screen", "widget"  → frontend
       "docker", "deploy", "ci", "env"        → mlops

3순위: 기본값
       → backend (가장 범용적 지식)
```

### 3.2 Q&A 타임아웃 처리

```python
async def ask(
    self,
    from_agent: str,
    question: str,
    context: dict,
    timeout: float = 30.0
) -> str:
    to_agent = self._find_responder(question, context)
    msg_id = generate_message_id()

    # 메시지 발송
    await self._send(Message(
        id=msg_id,
        from_agent=from_agent,
        to_agent=to_agent,
        message_type=MessageType.QUESTION,
        content=question,
        context=context,
    ))

    # 응답 대기 (타임아웃 후 빈 문자열 반환 — 에러 미발생)
    try:
        response = await asyncio.wait_for(
            self._queues[from_agent].get(), timeout=timeout
        )
        return response.content
    except asyncio.TimeoutError:
        log.warning("queue.qa.timeout",
            msg_id=msg_id, from_agent=from_agent, to_agent=to_agent)
        await self._storage.update_message_status(msg_id, MessageStatus.TIMEOUT)
        return ""
```

### 3.3 메시지 히스토리 보존 규칙

- 모든 메시지는 DB에 영구 저장 (삭제 금지)
- 응답된 메시지는 `status = ANSWERED`, 타임아웃은 `status = TIMEOUT`으로 기록
- 히스토리는 KnowledgeGraph 구축에 활용됨 (Phase 4+)

---

## 4. EventBus 규칙

### 4.1 이벤트 발행/구독 패턴

```python
# 이벤트 정의 — domain/events.py
@dataclass(frozen=True)
class WorkItemUpdatedEvent:
    item: WorkItem
    previous_status: WorkStatus

@dataclass(frozen=True)
class BlockingDetectedEvent:
    blocked_item: WorkItem
    reason: str

# 구독 등록 — application 레이어에서만
event_bus.subscribe(WorkItemUpdatedEvent, workspace_change_handler)
event_bus.subscribe(BlockingDetectedEvent, emergency_meeting_handler)  # Phase 5+
```

### 4.2 이벤트 핸들러 규칙

```python
# ✅ 올바른 핸들러 — 단일 책임, 빠른 처리
async def workspace_change_handler(event: WorkItemUpdatedEvent) -> None:
    if event.item.status == WorkStatus.DONE:
        await notify_watchers(event.item)

# ❌ 금지 — 핸들러 내부에서 LLM 호출 또는 무거운 작업
async def workspace_change_handler(event: WorkItemUpdatedEvent) -> None:
    await llm.generate(...)   # 핸들러는 경량이어야 함
```

- 핸들러는 **10초 이내** 완료 목표
- 10초 이상 걸리는 작업은 별도 코루틴으로 분리

---

## 5. 인터페이스(Port) 정의 규칙

협업 레이어의 모든 컴포넌트는 `domain/ports.py`에 인터페이스를 선 정의합니다.

```python
# domain/ports.py

from typing import Protocol

class WorkSpacePort(Protocol):
    async def register(self, task: Task, agent_id: str) -> WorkItem: ...
    async def get(self, item_id: str) -> WorkItem | None: ...
    async def set_status(self, item_id: str, status: WorkStatus) -> None: ...
    async def attach_result(self, item_id: str, result: TaskResult) -> None: ...
    async def detect_blocking(self) -> list[WorkItem]: ...

class MessageQueuePort(Protocol):
    async def ask(self, from_agent: str, question: str, context: dict) -> str: ...
    async def send(self, message: Message) -> None: ...
    async def receive(self, agent_id: str) -> Message: ...

class EventBusPort(Protocol):
    def subscribe(self, event_type: type, handler: Callable) -> None: ...
    async def publish(self, event: Any) -> None: ...
```

---

## 6. 로그 규칙 (협업 레이어 전용)

```python
# WorkSpace
log.info("ws.item.registered",  run_id=run_id, item_id=item.id, owner=item.agent_id)
log.info("ws.item.status",      run_id=run_id, item_id=item.id,
         prev=prev_status, curr=new_status)
log.warning("ws.blocking",      run_id=run_id, item_id=item.id, reason=reason)

# MessageQueue
log.info("queue.msg.sent",      run_id=run_id, msg_id=msg.id,
         from_=msg.from_agent, to=msg.to_agent, type=msg.message_type)
log.info("queue.msg.answered",  run_id=run_id, msg_id=msg.id, duration_sec=d)
log.warning("queue.msg.timeout",run_id=run_id, msg_id=msg.id)

# EventBus
log.debug("event.published",    event_type=type(event).__name__)
log.debug("event.handled",      event_type=type(event).__name__, handler=handler.__name__)
```

---

## 7. 금지 사항 (협업 레이어 전용)

| 번호 | 금지 사항 |
|------|---------|
| C-01 | 에이전트 간 직접 메서드 호출 (반드시 Queue/EventBus 경유) |
| C-02 | WorkItem 상태를 허용되지 않은 경로로 전이 |
| C-03 | 메시지 히스토리 삭제 |
| C-04 | 이벤트 핸들러 내부에서 LLM 호출 |
| C-05 | WorkSpace 구현체를 application 레이어에서 직접 참조 |
| C-06 | Q&A 타임아웃 발생 시 에러로 전체 중단 (빈 응답으로 계속) |
| C-07 | 구독 없이 이벤트를 임의로 무시 |

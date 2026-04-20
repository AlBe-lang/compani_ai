# Claude Code 소스코드 분석 - 05. 도구 시스템 (에이전트/작업/MCP)

> 분석 대상: `src/tools/AgentTool/`, `src/tools/Task*Tool/`, `src/tools/MCPTool/`, `src/coordinator/`

---

## 1. AgentTool - 서브에이전트 생성 (17개 파일)

### 1.1 역할

AgentTool은 Claude Code의 **멀티에이전트 오케스트레이션 핵심**입니다. 서브에이전트를 생성하고, 병렬로 실행하며, 결과를 수집합니다.

### 1.2 파일 구조

| 파일 | 크기 | 역할 |
|------|------|------|
| `AgentTool.tsx` | 1,398줄 | 메인 구현, 서브에이전트 생성 |
| `runAgent.ts` | 974줄 | 에이전트 실행 루프 |
| `agentToolUtils.ts` | 687줄 | 비동기 라이프사이클, 도구 필터링 |
| `forkSubagent.ts` | 211줄 | Fork 메커니즘 |
| `agentMemory.ts` | 178줄 | 에이전트 메모리 관리 |
| `agentMemorySnapshot.ts` | 198줄 | 메모리 스냅샷 |
| `resumeAgent.ts` | 266줄 | 중단된 에이전트 재개 |
| `builtInAgents.ts` | 73줄 | 빌트인 에이전트 목록 |
| `loadAgentsDir.ts` | 756줄 | 커스텀 에이전트 로드 |
| `prompt.ts` | 288줄 | 프롬프트 구성 |
| `UI.tsx` | 872줄 | UI 컴포넌트 |
| `agentDisplay.ts` | 105줄 | 에이전트 표시 |
| `agentColorManager.ts` | 67줄 | 에이전트 색상 |
| `constants.ts` | 13줄 | 상수 |
| `built-in/` | - | 빌트인 에이전트 정의 |

### 1.3 입력 스키마

```typescript
{
  prompt: string                   // 에이전트에게 줄 작업 지시
  subagent_type?: string           // 에이전트 유형 (general-purpose, Explore, Plan 등)
  description?: string             // UI 표시용 설명 (3-5 단어)
  model?: string                   // 사용할 모델 (기본: 부모와 동일)
  run_in_background?: boolean      // 비동기 백그라운드 실행 여부
  name?: string                    // 에이전트 이름 (재개용)
  isolation?: 'worktree' | 'none'  // 격리 방식
  cwd?: string                     // 작업 디렉토리
}
```

### 1.4 서브에이전트 생성 7단계

```typescript
async call({ prompt, subagent_type, run_in_background, isolation, ... }) {
  // Step 1: 에이전트 유형 결정
  const isForkPath = subagent_type === undefined && isForkSubagentEnabled()
  const selectedAgent = isForkPath
    ? FORK_AGENT
    : findAgent(subagent_type) ?? GENERAL_PURPOSE_AGENT

  // Step 2: 동기/비동기 결정
  const shouldRunAsync = (
    run_in_background === true ||
    selectedAgent.background === true ||
    isCoordinatorMode() ||         // 코디네이터는 항상 비동기
    isCoordinator
  ) && !isBackgroundTasksDisabled()

  // Step 3: 도구 풀 조립
  const workerTools = resolveAgentTools(
    selectedAgent,
    availableTools,
    shouldRunAsync
  )

  // Step 4: 시스템 프롬프트 구성
  const systemPrompt = isForkPath
    ? toolUseContext.renderedSystemPrompt   // Fork: 부모 프롬프트 상속
    : selectedAgent.getSystemPrompt()       // 일반: 에이전트 전용 프롬프트

  // Step 5: Worktree 격리 (선택적)
  if (isolation === 'worktree') {
    worktreeInfo = await createAgentWorktree(`agent-${agentId.slice(0, 8)}`)
  }

  // Step 6: 비동기 실행
  if (shouldRunAsync) {
    const task = registerAsyncAgent({ agentId, description, prompt })
    void runWithAgentContext(asyncContext, () =>
      runAsyncAgentLifecycle({ taskId: task.agentId, makeStream: ... })
    )
    return { agentId, description, outputFile: getTaskOutputPath(agentId) }
  }

  // Step 7: 동기 실행
  const messages = []
  for await (const message of runAgent({ ... })) {
    messages.push(message)
  }
  return { data: extractFinalText(messages) }
}
```

---

## 2. runAgent.ts - 에이전트 실행 루프

### 2.1 역할

서브에이전트의 실제 LLM 호출과 도구 실행 루프를 담당합니다.

### 2.2 핵심 구조

```typescript
export async function* runAgent({
  agentDefinition,      // 에이전트 정의
  promptMessages,       // 초기 메시지들
  toolUseContext,       // 도구 실행 컨텍스트
  canUseTool,           // 권한 확인 함수
  isAsync,              // 비동기 실행 여부
  model,                // 사용할 모델
  availableTools,       // 사용 가능한 도구 목록
  contentReplacementState,
  worktreePath,
}): AsyncGenerator<Message, void> {

  const agentId = createAgentId()

  // 1. MCP 서버 초기화
  const { clients, tools: mcpTools, cleanup } =
    await initializeAgentMcpServers(agentDefinition, parentClients)

  // 2. 도구 풀 해석
  const resolvedTools = resolveAgentTools(agentDefinition, availableTools, isAsync)

  // 3. 시스템 프롬프트
  const agentSystemPrompt = await getAgentSystemPrompt(agentDefinition, ...)

  // 4. 메시지 스트림 처리
  for await (const message of query({
    messages: promptMessages,
    model,
    tools: resolvedTools.resolvedTools,
    systemPrompt: agentSystemPrompt,
  }, ...)) {
    yield message  // 각 메시지를 부모에게 전달
  }

  // 5. 정리
  await cleanup()
}
```

---

## 3. Fork 서브에이전트 (forkSubagent.ts)

### 3.1 Fork란?

Fork는 **부모의 전체 대화 맥락을 그대로 상속하는** 특수한 서브에이전트입니다. 새로운 에이전트를 처음부터 시작하는 대신, 부모가 지금까지 나눈 대화를 그대로 가져갑니다.

```typescript
export const FORK_AGENT = {
  agentType: FORK_SUBAGENT_TYPE,
  whenToUse: 'Implicit fork — inherits full conversation context.',
  tools: ['*'],          // 모든 도구 허용
  maxTurns: 200,
  model: 'inherit',      // 부모 모델 상속
  permissionMode: 'bubble',  // 권한을 부모로 위임
  source: 'built-in',
}
```

### 3.2 Fork 메시지 구성

```typescript
export function buildForkedMessages(
  directive: string,     // 새 지시사항
  assistantMessage: AssistantMessage  // 부모의 현재 assistant 메시지
): MessageType[] {

  // 1. 부모의 assistant 메시지 복제
  const fullAssistantMessage = { ...assistantMessage }

  // 2. 모든 tool_use에 대해 placeholder tool_result 생성
  // (부모가 이미 실행했으므로 결과를 placeholder로 대체)
  const toolResultBlocks = toolUseBlocks.map(block => ({
    type: 'tool_result',
    tool_use_id: block.id,
    content: [{ type: 'text', text: FORK_PLACEHOLDER_RESULT }],
    // 모든 fork child가 동일한 placeholder 사용 → 캐시 히트!
  }))

  // 3. user 메시지 구성 [tool_results..., 새 지시사항]
  const userMessage = createUserMessage({
    content: [
      ...toolResultBlocks,
      { type: 'text', text: buildChildMessage(directive) }
    ]
  })

  return [fullAssistantMessage, userMessage]
}
```

### 3.3 캐시 최적화 전략

```
부모: [시스템 프롬프트] [대화 히스토리] [assistant 메시지]
                                                    ↓ fork
Fork A: [시스템 프롬프트] [대화 히스토리] [assistant 메시지] [placeholder A] [지시사항 A]
Fork B: [시스템 프롬프트] [대화 히스토리] [assistant 메시지] [placeholder B] [지시사항 B]

→ 시스템 프롬프트 + 대화 히스토리 + assistant 메시지 = 캐시 히트!
→ 지시사항 부분만 달라서 캐시 미스 (최소화)
```

### 3.4 재귀 Fork 방지

```typescript
// Fork child는 다시 fork할 수 없음
export function isInForkChild(messages: MessageType[]): boolean {
  return messages.some(m => {
    if (m.type !== 'user') return false
    return m.message.content.some(
      block => block.type === 'text' &&
               block.text.includes(`<${FORK_BOILERPLATE_TAG}>`)
    )
  })
}

// Fork child 지시사항에 포함되는 규칙
const FORK_CHILD_RULES = `
RULES (non-negotiable):
1. You ARE the fork. Do NOT spawn sub-agents; execute directly.
2. Do NOT converse, ask questions, or suggest next steps
3. Do NOT editorialize or add meta-commentary
4. USE your tools directly: Bash, Read, Write, etc.
`
```

---

## 4. Coordinator Mode (coordinatorMode.ts)

### 4.1 코디네이터 역할

코디네이터는 **멀티에이전트 팀의 오케스트레이터**입니다:
- 작업을 여러 Worker로 분해
- Worker들을 병렬 실행
- 결과 수집 및 합성

### 4.2 코디네이터 활성화

```typescript
export function isCoordinatorMode(): boolean {
  if (feature('COORDINATOR_MODE')) {
    return isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE)
  }
  return false
}
```

**활성화 방법:**
```bash
CLAUDE_CODE_COORDINATOR_MODE=1 claude
```

### 4.3 코디네이터 시스템 프롬프트 요점

```typescript
export function getCoordinatorSystemPrompt(): string {
  return `
You are a coordinator. Your job is to:
- Help the user achieve their goal
- Direct workers to research, implement and verify code changes
- Synthesize results and communicate with the user

Parallelism is your superpower. Workers are async. Launch independent workers
concurrently whenever possible — don't serialize work that can run simultaneously.

To launch workers in parallel, make multiple tool calls in a single message.
  `
}
```

### 4.4 Worker 완료 알림 형식

Worker가 완료되면 이 형식으로 코디네이터에게 통보됩니다:

```xml
<task-notification>
  <task-id>agent-abc123</task-id>
  <status>completed</status>
  <summary>파일 분석 완료</summary>
  <result>분석 결과 텍스트...</result>
  <usage>
    <total_tokens>1234</total_tokens>
    <tool_uses>5</tool_uses>
    <duration_ms>3456</duration_ms>
  </usage>
</task-notification>
```

---

## 5. 에이전트 메모리 (agentMemory.ts)

### 5.1 메모리 스코프

```typescript
export type AgentMemoryScope = 'user' | 'project' | 'local'

// 메모리 저장 위치
function getAgentMemoryDir(agentType: string, scope: AgentMemoryScope): string {
  switch (scope) {
    case 'user':
      // ~/.claude/agent-memory/general-purpose/
      return join(getMemoryBaseDir(), 'agent-memory', agentType) + sep

    case 'project':
      // .claude/agent-memory/general-purpose/
      return join(getCwd(), '.claude', 'agent-memory', agentType) + sep

    case 'local':
      // .claude/agent-memory-local/general-purpose/ (gitignore됨)
      return getLocalAgentMemoryDir(agentType)
  }
}
```

### 5.2 메모리 파일 구조

```
~/.claude/agent-memory/
├── general-purpose/
│   └── MEMORY.md          # 범용 에이전트 메모리
├── Explore/
│   └── MEMORY.md          # 탐색 에이전트 메모리
└── Plan/
    └── MEMORY.md          # 계획 에이전트 메모리

.claude/agent-memory/      # 프로젝트 레벨 메모리
└── general-purpose/
    └── MEMORY.md
```

---

## 6. 에이전트 재개 (resumeAgent.ts)

### 6.1 역할

중단된 에이전트를 저장된 트랜스크립트에서 복원하여 이어서 실행합니다.

### 6.2 재개 프로세스

```typescript
export async function resumeAgentBackground({ agentId, prompt, ... }) {
  // 1. 트랜스크립트 및 메타데이터 로드
  const [transcript, meta] = await Promise.all([
    getAgentTranscript(agentId),
    readAgentMetadata(agentId),
  ])

  // 2. 메시지 정제 (孤립된 thinking, 빈 메시지 제거)
  const cleanMessages = filterOrphanedThinkingOnlyMessages(
    filterUnresolvedToolUses(transcript.messages)
  )

  // 3. 컨텍스트 교체 상태 재구성 (캐시 안정성)
  const resumedState = reconstructForSubagentResume(
    toolUseContext.contentReplacementState,
    cleanMessages,
    transcript.contentReplacements
  )

  // 4. Worktree 경로 검증
  const worktreePath = meta?.worktreePath
    ? await validateWorktreePath(meta.worktreePath)
    : undefined

  // 5. 에이전트 선택 (메타에서 이전 에이전트 유형 복원)
  const selectedAgent = meta?.agentType === FORK_AGENT.agentType
    ? FORK_AGENT
    : findAgent(meta?.agentType) ?? GENERAL_PURPOSE_AGENT

  // 6. 비동기 재개 실행
  void runWithAgentContext(context, () =>
    runAsyncAgentLifecycle({ taskId: agentId, ... })
  )

  return { agentId, description, outputFile: getTaskOutputPath(agentId) }
}
```

---

## 7. 빌트인 에이전트 (builtInAgents.ts)

### 7.1 기본 에이전트 목록

```typescript
export function getBuiltInAgents(): AgentDefinition[] {
  const agents: AgentDefinition[] = [
    GENERAL_PURPOSE_AGENT,    // 범용 (기본)
    STATUSLINE_SETUP_AGENT,   // 상태 라인 설정
  ]

  // 실험적 에이전트 (기능 플래그로 활성화)
  if (areExplorePlanAgentsEnabled()) {
    agents.push(EXPLORE_AGENT, PLAN_AGENT)
  }

  // Claude Code Guide (SDK 모드에서 제외)
  if (isNonSdkEntrypoint) {
    agents.push(CLAUDE_CODE_GUIDE_AGENT)
  }

  // 검증 에이전트 (feature flag + GrowthBook 플래그 동시 필요)
  if (feature('VERIFICATION_AGENT') && getFeatureValue('tengu_hive_evidence')) {
    agents.push(VERIFICATION_AGENT)
  }

  return agents
}
```

### 7.2 에이전트 정의 구조

```typescript
interface AgentDefinition {
  agentType: string                    // 에이전트 식별자
  description: string                  // 사용 설명
  whenToUse: string                    // 언제 사용할지
  tools: string[] | ['*']              // 사용 가능한 도구 목록
  disallowedTools?: string[]           // 금지된 도구 목록
  maxTurns?: number                    // 최대 대화 턴
  model?: string | 'inherit'           // 사용할 모델
  permissionMode?: PermissionMode      // 권한 모드
  background?: boolean                 // 기본 백그라운드 실행 여부
  source: 'built-in' | string          // 에이전트 소스
  getSystemPrompt(options): string     // 시스템 프롬프트 생성
}
```

### 7.3 현재 사용 가능한 에이전트 (이 Claude Code에서)

| 에이전트 | subagent_type | 용도 |
|---------|---------------|------|
| General Purpose | `general-purpose` | 일반 작업 |
| Explore | `Explore` | 코드베이스 탐색 |
| Plan | `Plan` | 구현 계획 |
| Claude Code Guide | `claude-code-guide` | Claude Code 사용법 안내 |
| Statusline Setup | `statusline-setup` | 상태 라인 설정 |

---

## 8. 작업 관리 도구 (Task*Tool)

### 8.1 작업 시스템 개요

작업(Task)은 **비동기 에이전트 실행의 트래킹 단위**입니다. AgentTool이 비동기로 에이전트를 실행할 때 Task가 생성됩니다.

```typescript
interface Task {
  id: string                    // 고유 ID
  type: 'local' | 'remote'      // 로컬 vs 원격 에이전트
  status: 'pending' | 'running' | 'completed' | 'failed' | 'killed'
  description: string           // 작업 설명
  agentId: string               // 연결된 에이전트 ID
  messages?: Message[]          // 에이전트 메시지들
  progress?: ProgressUpdate     // 진행 상황
  result?: string               // 최종 결과
  createdAt: number             // 생성 시각
  completedAt?: number          // 완료 시각
}
```

### 8.2 TaskCreateTool

```typescript
// 입력
{
  description: string     // 작업 설명
  prompt: string          // 에이전트 지시사항
  subagent_type?: string  // 에이전트 유형
}

// 내부 동작
async call({ description, prompt, subagent_type }) {
  // AgentTool을 run_in_background=true로 호출
  return AgentTool.call({
    prompt,
    subagent_type,
    description,
    run_in_background: true,
  }, ...)
}
```

### 8.3 TaskGetTool

```typescript
// 입력
{
  task_id: string    // 조회할 작업 ID
}

// 출력
{
  id, status, description, progress,
  messages: [...],  // 에이전트 메시지 히스토리
  result,           // 완료된 경우 최종 결과
}
```

### 8.4 TaskOutputTool

```typescript
// 입력
{
  task_id: string    // 조회할 작업 ID
}

// 완료된 작업의 최종 출력만 반환 (메시지 히스토리 제외)
async call({ task_id }) {
  const outputPath = getTaskOutputPath(task_id)
  return { data: await fs.readFile(outputPath, 'utf-8') }
}
```

### 8.5 TaskStopTool

```typescript
// 입력
{
  task_id: string    // 중지할 작업 ID
}

// 실행 중인 에이전트에 AbortController로 취소 신호 전송
async call({ task_id }) {
  const task = getTask(task_id)
  task.abortController?.abort()
  return { data: `Task ${task_id} stop signal sent` }
}
```

---

## 9. MCP 관련 도구

### 9.1 MCPTool

**역할:** MCP 서버의 도구 실행

```typescript
// MCP 도구는 동적으로 등록됨
// 각 MCP 서버가 연결되면 해당 서버의 도구들이 자동 등록

// 도구 이름 형식: mcp__<server_name>__<tool_name>
// 예: mcp__filesystem__read_file
//     mcp__git__create_commit
//     mcp__puppeteer__puppeteer_navigate
```

### 9.2 ListMcpResourcesTool

```typescript
// 입력
{
  server_name?: string   // 특정 서버 (없으면 전체)
}

// MCP 서버에서 제공하는 리소스 목록 반환
// 예: 데이터베이스 스키마, 파일 시스템, 문서 등
```

### 9.3 ReadMcpResourceTool

```typescript
// 입력
{
  server_name: string   // MCP 서버 이름
  resource_uri: string  // 리소스 URI (예: "file:///path/to/file")
}

// MCP 서버에서 특정 리소스 내용 읽기
```

### 9.4 ToolSearchTool

**역할:** 지연 로드(deferred)된 도구를 필요할 때 활성화

```typescript
// 입력
{
  query: string         // 검색어 (예: "notebook jupyter")
  max_results?: number  // 최대 결과 수
}

// 동작:
// 1. 비활성화된 도구들의 이름/설명 검색
// 2. 관련된 도구의 전체 스키마 반환
// 3. 해당 도구를 이후 호출 가능 상태로 활성화
```

---

## 10. 스케줄/트리거 도구

### 10.1 ScheduleCronTool

```typescript
// 입력
{
  action: 'create' | 'delete' | 'list'
  schedule?: string    // cron 표현식 (예: "0 9 * * 1-5")
  prompt?: string      // 스케줄 실행 시 실행할 프롬프트
  name?: string        // 스케줄 이름
}

// 예시: 매일 오전 9시에 코드 리뷰 실행
ScheduleCronTool({
  action: 'create',
  schedule: '0 9 * * 1-5',
  prompt: '/review-pr --auto',
  name: 'daily-code-review'
})
```

### 10.2 RemoteTriggerTool

```typescript
// 원격에서 Claude Code 에이전트 트리거
// 예: GitHub Actions, Webhook 등에서 호출

// 입력
{
  trigger_id: string   // 트리거 ID
  payload?: object     // 추가 데이터
}
```

---

## 11. SendMessageTool (에이전트 간 메시징)

### 11.1 역할

실행 중인 에이전트에게 메시지 전송 또는 에이전트 상태 조회

```typescript
// 입력
{
  to: string        // 에이전트 ID 또는 이름
  message: string   // 보낼 메시지
}

// 사용 예:
// 1. 코디네이터가 Worker에게 추가 지시
// 2. Worker가 완료 후 결과 보고
// 3. 에이전트 간 정보 공유
```

---

## 12. 팀 도구 (TeamCreateTool, TeamDeleteTool)

### 12.1 팀 모드

팀 모드는 **여러 에이전트가 실시간으로 협업**하는 고급 멀티에이전트 모드입니다:

```typescript
// 팀 생성
TeamCreateTool({
  team_name: 'analysis-team',
  agents: [
    { name: 'analyzer', subagent_type: 'Explore' },
    { name: 'planner', subagent_type: 'Plan' },
    { name: 'implementer', subagent_type: 'general-purpose' },
  ]
})

// 팀 내 에이전트들은:
// - SendMessageTool로 직접 통신 가능
// - 공유 상태에 접근 가능
// - 병렬로 다른 파일 작업 가능
```

### 12.2 팀 vs 코디네이터 비교

| 특성 | 코디네이터 | 팀 |
|------|-----------|-----|
| 통신 방식 | task-notification | SendMessage |
| 에이전트 간 직접 통신 | 불가 | 가능 |
| 사용 케이스 | 독립적 병렬 작업 | 밀접한 협업 |
| 복잡도 | 낮음 | 높음 |

---

## 13. 도구 필터링 (agentToolUtils.ts)

### 13.1 서브에이전트 도구 제한

비동기 에이전트는 모든 도구를 사용할 수 없습니다:

```typescript
// 비동기 에이전트에서 허용된 도구 (화이트리스트)
const ASYNC_AGENT_ALLOWED_TOOLS = new Set([
  'Bash', 'Read', 'Write', 'Edit',
  'Glob', 'Grep', 'WebFetch', 'WebSearch',
  'TodoWrite', 'Agent', 'SendMessage',
  'TaskCreate', 'TaskGet', 'TaskList', 'TaskOutput',
  // ... (AskUserQuestion은 제외 - UI 상호작용 불가)
])

// 모든 에이전트에서 금지된 도구
const ALL_AGENT_DISALLOWED_TOOLS = new Set([
  'EnterPlanMode',      // 플랜 모드는 메인 세션에서만
  'ExitPlanMode',
  // ...
])
```

### 13.2 Agent(agentType) 형식 파싱

```typescript
// "Agent(worker, researcher)" → allowedAgentTypes = ["worker", "researcher"]
for (const toolSpec of agentTools) {
  const { toolName, ruleContent } = permissionRuleValueFromString(toolSpec)

  if (toolName === AGENT_TOOL_NAME && ruleContent) {
    allowedAgentTypes = ruleContent.split(',').map(s => s.trim())
  }
}
```

# Claude Code 소스코드 분석 - 02. 핵심 엔진

> 분석 대상: `src/main.tsx`, `src/query.ts`, `src/QueryEngine.ts`, `src/context.ts`, `src/history.ts`, `src/cost-tracker.ts`, `src/Tool.ts`

---

## 1. main.tsx - CLI 진입점 (803KB)

### 1.1 역할

`main.tsx`는 Claude Code의 **최상위 진입점**입니다. CLI 인자를 파싱하고, 초기화 순서를 관리하며, React/Ink 렌더러를 부트스트랩합니다.

### 1.2 초기화 순서

```typescript
// 1단계: 병렬 프리페치 시작 (I/O 블로킹 없이 백그라운드에서 실행)
profileCheckpoint('main_tsx_entry')
startMdmRawRead()        // MDM(Mobile Device Management) 설정 읽기
startKeychainPrefetch()  // macOS 키체인에서 API 키 읽기

// 2단계: Commander.js CLI 파서 설정
const program = new CommanderCommand()
  .name('claude')
  .version(version)
  .option('--api-key <key>', 'Anthropic API 키')
  .option('--model <model>', '사용할 모델')
  .option('--bare', '최소 UI 모드')
  .option('--dangerously-skip-permissions', '권한 확인 생략')
  .option('--print', '비대화형 출력 모드')
  // ... 30개 이상의 옵션

// 3단계: 초기화 파이프라인
async function bootstrap() {
  await verifyTrustDialogue()         // 신뢰 대화 확인
  await loadMdmSettings()             // MDM 설정 로드
  await initGrowthBook()              // 기능 플래그 초기화
  await setupOAuth()                  // OAuth 설정
  await discoverMcpServers()          // MCP 서버 발견
  await loadPlugins()                 // 플러그인 로드
  await loadSkills()                  // 스킬 로드

  // 4단계: REPL 또는 비대화형 모드 실행
  if (options.print) {
    await runNonInteractive(options)
  } else {
    await runREPL(options)
  }
}
```

### 1.3 병렬 프리페치 최적화

main.tsx의 핵심 성능 최적화 중 하나는 **병렬 I/O 프리페치**입니다:

```typescript
// 메인 스레드가 무거운 모듈 임포트를 처리하는 동안
// 백그라운드에서 I/O 작업이 동시에 실행됩니다

// 약 135ms 동안 무거운 임포트 실행 중:
// - MDM 설정 읽기 (~30ms 절약)
// - 키체인 읽기 (~35ms 절약)
// 총 약 65ms 평균 시간 절약 (macOS 기준)
```

### 1.4 주요 CLI 옵션

| 옵션 | 설명 |
|------|------|
| `--api-key` | Anthropic API 키 직접 지정 |
| `--model` | 사용할 Claude 모델 지정 |
| `--print` / `-p` | 비대화형 출력 모드 |
| `--bare` | 최소 UI (터미널 UI 없음) |
| `--dangerously-skip-permissions` | 모든 권한 확인 자동 승인 |
| `--resume` | 이전 세션 재개 |
| `--continue` | 마지막 세션 계속 |
| `--mcp-server` | MCP 서버 모드로 실행 |
| `--input-format` | 입력 형식 (text/json/stream-json) |
| `--output-format` | 출력 형식 (text/json/stream-json) |

---

## 2. QueryEngine.ts - LLM 핵심 루프 (~46KB)

### 2.1 역할

`QueryEngine.ts`는 Claude Code의 **두뇌**입니다. Anthropic API와의 모든 통신, 도구 호출 루프, 재시도 로직, 토큰 관리를 담당합니다.

### 2.2 핵심 클래스 구조

```typescript
export class QueryEngine {
  private config: QueryEngineConfig
  private mutableMessages: Message[]        // 대화 히스토리
  private abortController: AbortController // 취소 제어
  private permissionDenials: SDKPermissionDenial[]
  private totalUsage: NonNullableUsage      // 누적 토큰 사용량

  // 생성자
  constructor(config: QueryEngineConfig) {
    this.config = config
    this.mutableMessages = []
    this.abortController = new AbortController()
    this.totalUsage = { input_tokens: 0, output_tokens: 0, ... }
  }

  // 사용자 메시지 제출
  async submitMessage(userMessage: Message): Promise<void>

  // 내부 도구 실행 루프
  private async *executeToolLoop(): AsyncGenerator<Message>

  // Extended Thinking 관리
  private async handleThinkingMode(options: ThinkingOptions): Promise<void>

  // 폴백 재시도
  private async retryWithFallback(error: APIError): Promise<void>

  // 토큰 사용량 추적
  private async trackTokenUsage(usage: BetaUsage): Promise<void>
}
```

### 2.3 도구 실행 루프 (Tool Loop)

QueryEngine의 핵심인 도구 실행 루프는 **반복적(iterative) 패턴**으로 동작합니다:

```
[사용자 메시지]
      ↓
[API 호출 → 스트리밍 응답]
      ↓
 스트림에서 블록 유형 확인:
      │
      ├── text 블록 → 즉시 터미널에 출력
      │
      ├── thinking 블록 → Extended thinking 관리
      │
      └── tool_use 블록 → 도구 실행
               ↓
          [권한 확인]
               ↓
          [도구 실행]
               ↓
          [결과를 tool_result로 추가]
               ↓
          [루프 처음으로 돌아감]
      ↓
[stop_reason: end_turn] → 루프 종료
```

### 2.4 에러 처리 및 재시도

```typescript
// 자동 재시도 전략
private async retryWithFallback(error: APIError): Promise<void> {
  if (error.status === 529) {
    // API 과부하 → 지수 백오프로 재시도
    await exponentialBackoff()
  }

  if (error.message.includes('max_output_tokens')) {
    // 출력 토큰 한계 → 출력 크기 줄여서 재시도
    await retryWithSmallerOutput()
  }

  if (error.message.includes('prompt too long')) {
    // 컨텍스트 초과 → 자동 압축 후 재시도
    await compactAndRetry()
  }

  if (error.status === 429) {
    // 요청 한도 초과 → 폴백 모델로 전환
    await switchToFallbackModel()
  }
}
```

### 2.5 Extended Thinking

```typescript
private async handleThinkingMode(options: ThinkingOptions): Promise<void> {
  // thinking 블록은 UI에 접을 수 있는 형태로 표시
  // budget_tokens: thinking에 할당된 토큰 예산
  // 사용자는 thinking 과정을 펼쳐서 볼 수 있음
}
```

### 2.6 토큰 추적

```typescript
private async trackTokenUsage(usage: BetaUsage): Promise<void> {
  this.totalUsage.input_tokens += usage.input_tokens
  this.totalUsage.output_tokens += usage.output_tokens
  this.totalUsage.cache_read_input_tokens += usage.cache_read_input_tokens ?? 0
  this.totalUsage.cache_creation_input_tokens += usage.cache_creation_input_tokens ?? 0
}
```

---

## 3. query.ts - 쿼리 파이프라인 (~68KB)

### 3.1 역할

`query.ts`는 QueryEngine을 **REPL과 SDK에 노출**하는 파이프라인입니다. 컨텍스트 조립, 메모리 통합, 비용 추적을 처리합니다.

### 3.2 주요 내보내기

```typescript
// 1. 메인 쿼리 함수 (대화형 REPL용)
export async function query(params: QueryParams): Promise<void>

// 2. SDK 모드 (프로그래밍 API용)
export async function ask(params: QueryParams): Promise<void>

// 3. 스트리밍 제너레이터
export async function* queryStream(
  params: QueryParams
): AsyncGenerator<Message, void>
```

### 3.3 쿼리 처리 파이프라인

```typescript
export async function query(params: QueryParams): Promise<void> {
  // 1. 시스템 프롬프트 조립
  const systemPrompt = await buildEffectiveSystemPrompt({
    tools: params.tools,
    systemContext: await getSystemContext(),
    userContext: await getUserContext(),
    memory: await loadMemory(),
    customPrompt: params.systemPrompt,
  })

  // 2. QueryEngine 초기화
  const engine = new QueryEngine({
    model: params.model,
    tools: params.tools,
    systemPrompt,
    permissionMode: params.permissionMode,
  })

  // 3. 메시지 스트리밍 처리
  for await (const message of engine.submitMessage(params.userMessage)) {
    // 메시지 히스토리에 추가
    params.onMessage?.(message)

    // 비용 추적
    if (message.type === 'assistant') {
      addToTotalSessionCost(message.usage)
    }
  }

  // 4. 분석 이벤트 로깅
  await logAnalyticsEvent('query_completed', { ... })
}
```

### 3.4 시스템 프롬프트 구성

```typescript
async function buildEffectiveSystemPrompt(options): Promise<string> {
  const parts = [
    BASE_SYSTEM_PROMPT,           // 기본 Claude Code 프롬프트
    getToolsPrompt(options.tools), // 각 도구의 설명과 사용법
    options.systemContext,         // Git 상태, 현재 디렉토리 등
    options.userContext,           // CLAUDE.md 내용, 메모리
    options.customPrompt,          // 사용자 커스텀 프롬프트
    getCacheBreaker(),             // 프롬프트 캐시 제어
  ]

  return parts.filter(Boolean).join('\n\n')
}
```

---

## 4. context.ts - 컨텍스트 생성

### 4.1 역할

시스템 및 사용자 컨텍스트를 자동 수집하여 시스템 프롬프트에 포함시킵니다.

### 4.2 시스템 컨텍스트

```typescript
export const getSystemContext = memoize(async (): Promise<{
  [k: string]: string
}> => {
  // Git 상태 수집
  const gitStatus = await runGitCommand('status --short')
  const gitBranch = await runGitCommand('branch --show-current')
  const recentCommits = await runGitCommand('log --oneline -5')

  // 프롬프트 캐시 제어 (반복 요청 시 캐시 히트 최대화)
  const cacheBreaker = `[CACHE_BREAKER: ${generateCacheKey()}]`

  return {
    gitStatus,
    gitBranch,
    recentCommits,
    cacheBreaker,
    currentDirectory: process.cwd(),
    platform: process.platform,
  }
})
```

### 4.3 사용자 컨텍스트

```typescript
export const getUserContext = memoize(async (): Promise<{
  [k: string]: string
}> => {
  // CLAUDE.md 파일 자동 발견 (현재 디렉토리부터 상위로 탐색)
  const claudeMdContent = await loadClaudeMd()

  // 메모리 파일 수집 (~/.claude/memory/)
  const memoryContent = await loadMemoryFiles()

  // 현재 날짜 주입
  const currentDate = `Today's date is ${new Date().toISOString().split('T')[0]}.`

  return {
    claudeMd: claudeMdContent,
    memory: memoryContent,
    currentDate,
  }
})
```

---

## 5. history.ts - 히스토리 관리 (~14KB)

### 5.1 역할

프롬프트 히스토리를 파일에 저장하고, 위쪽 화살표 키로 이전 입력을 복원합니다.

### 5.2 저장 형식

히스토리는 JSONL(JSON Lines) 형식으로 저장됩니다:

```typescript
type LogEntry = {
  display: string           // 표시될 텍스트
  pastedContents: Record<number, StoredPastedContent>  // 붙여넣은 내용
  timestamp: number         // Unix timestamp
  project: string           // 프로젝트 식별자 (cwd 해시)
  sessionId?: string        // 세션 ID
}
```

**저장 위치:**
- `~/.claude/history.jsonl` - 전체 히스토리
- 프로젝트별, 세션별로 필터링 가능

### 5.3 주요 함수

```typescript
// 히스토리 순회 (가장 최근부터)
export async function* getHistory(): AsyncGenerator<HistoryEntry> {
  // 현재 세션 항목을 먼저 반환
  // 그 다음 같은 프로젝트의 이전 세션 항목
  // 마지막으로 다른 프로젝트 항목
}

// 히스토리에 추가
export function addToHistory(command: HistoryEntry | string): void

// 마지막 항목 제거 (Ctrl+C로 중단된 입력 복구용)
export function removeLastFromHistory(): void

// 히스토리 검색 (Ctrl+R)
export async function searchHistory(query: string): AsyncGenerator<HistoryEntry>
```

---

## 6. cost-tracker.ts - 비용 추적 (~11KB)

### 6.1 역할

토큰 사용량과 API 비용을 추적하여 `/cost` 커맨드에서 표시합니다.

### 6.2 비용 계산

```typescript
// 모델별 가격 정의 ($/1M tokens)
const MODEL_PRICING: Record<string, ModelPricing> = {
  'claude-opus-4-5': {
    input: 15.0,
    output: 75.0,
    cacheRead: 1.5,
    cacheWrite: 18.75,
  },
  'claude-sonnet-4-6': {
    input: 3.0,
    output: 15.0,
    cacheRead: 0.30,
    cacheWrite: 3.75,
  },
  'claude-haiku-4-5': {
    input: 0.80,
    output: 4.0,
    cacheRead: 0.08,
    cacheWrite: 1.0,
  },
}

export function addToTotalSessionCost(
  cost: number,
  usage: BetaUsage,
  model: string
): number {
  // 모델별 사용량 누적
  // 캐시 읽기/쓰기 토큰 별도 추적
  // 웹 검색 요청 횟수 추적
}
```

### 6.3 비용 표시 형식

```
/cost 출력 예시:

Total session cost: $0.0234
  claude-sonnet-4-6:
    Input tokens:       1,234 ($0.0037)
    Output tokens:        567 ($0.0085)
    Cache read tokens:  2,345 ($0.0007)
    Cache write tokens:   890 ($0.0034)

  Web search requests: 2 ($0.0071)

Total API time: 45.3s
Lines changed: +123 / -45
```

---

## 7. Tool.ts - 도구 타입 정의 (~29KB)

### 7.1 Tool 인터페이스

```typescript
export interface Tool {
  // 기본 정보
  name: string
  description: string
  aliases?: string[]

  // 스키마
  inputSchema: ToolInputJSONSchema    // 입력 파라미터 스키마
  outputSchema: ToolInputJSONSchema   // 출력 형식 스키마

  // 핵심 실행 함수
  call(
    input: unknown,
    context: ToolUseContext,
    canUseTool: CanUseToolFn,
    parentMessage?: AssistantMessage,
    onProgress?: (progress: ToolProgressData) => void
  ): Promise<{
    data: string
    newMessages?: Message[]
  }>

  // 권한 확인
  checkPermissions(
    input: unknown,
    context: ToolUseContext
  ): Promise<PermissionResult>

  // 동시 실행 안전 여부
  isConcurrencySafe(input: unknown): boolean

  // 읽기 전용 여부
  isReadOnly(input: unknown): boolean

  // 시스템 프롬프트용 설명 생성
  prompt(options?: PromptOptions): string | Promise<string>

  // UI 렌더링
  renderToolUseMessage(input: unknown, options: RenderOptions): JSX.Element
  renderToolResultMessage(
    content: string,
    progress: ToolProgressMessage[]
  ): JSX.Element
}
```

### 7.2 ToolUseContext (도구 실행 컨텍스트)

모든 도구 실행 시 전달되는 컨텍스트 객체입니다:

```typescript
export interface ToolUseContext {
  // 앱 상태
  appState: AppState

  // 현재 작업 디렉토리
  getCwd: () => string

  // 파일 캐시
  getFileCache: () => FileStateCache

  // IDE 연결
  handleElicitation?: (url: string) => void

  // 시스템 프롬프트 접근
  getSystemPrompt: () => Promise<SystemPrompt>

  // 렌더링된 시스템 프롬프트 (Fork용)
  renderedSystemPrompt?: SystemPrompt

  // 권한 모드
  permissionMode: PermissionMode

  // 도구 목록
  options: {
    tools: Tool[]
    agentDefinitions: AgentDefinitions
    mainLoopModel: ModelOptions
    // ...
  }

  // 컨텍스트 교체 상태 (긴 텍스트 참조 최적화)
  contentReplacementState: ContentReplacementState

  // 도구 사용 ID (현재 도구 호출 ID)
  toolUseId: string

  // MCP 클라이언트
  mcpClients: MCPClient[]

  // ... 40개 이상의 속성
}
```

### 7.3 buildTool - 도구 생성 헬퍼

```typescript
// 도구 정의를 Tool 인터페이스로 변환하는 빌더
export function buildTool(definition: ToolDef): Tool {
  return {
    name: definition.name,
    description: definition.description,
    inputSchema: definition.inputSchema,

    async call(input, context, canUseTool, parentMessage, onProgress) {
      // 권한 확인
      const permission = await definition.checkPermissions?.(input, context)
      if (!permission?.granted) {
        throw new PermissionDeniedError(permission?.reason)
      }

      // 도구 실행
      return await definition.execute(input, context, { onProgress })
    },

    // ... 나머지 메서드 위임
  }
}
```

---

## 8. 전체 엔진 상호작용 다이어그램

```
main.tsx
   │
   ├── CLI 파싱 (Commander.js)
   ├── 초기화 (MDM, GrowthBook, OAuth, MCP, 플러그인)
   └── screens/REPL.tsx 실행
              │
              │ 사용자 입력
              ▼
         query.ts
              │
              ├── 시스템 프롬프트 조립 (context.ts)
              │     ├── getSystemContext() → Git 상태, 디렉토리
              │     └── getUserContext() → CLAUDE.md, 메모리
              │
              ├── QueryEngine 초기화
              └── QueryEngine.submitMessage()
                         │
                         ▼
                   QueryEngine.ts
                         │
                         ├── Anthropic API 스트리밍 호출
                         ├── text 블록 → 즉시 출력
                         ├── thinking 블록 → Extended thinking
                         └── tool_use 블록 → 도구 실행 루프
                                    │
                                    ├── Tool.checkPermissions()
                                    ├── Tool.call()
                                    └── tool_result → 다시 API로
```

# Claude Code 소스코드 분석 - 08. IDE 브릿지 & UI 컴포넌트

> 분석 대상: `src/bridge/`, `src/components/`, `src/screens/`, `src/hooks/`

---

## 1. IDE 브릿지 시스템 (src/bridge/)

### 1.1 역할

IDE 브릿지는 Claude Code CLI를 **VS Code, JetBrains 같은 IDE와 연결**하는 양방향 통신 레이어입니다.

### 1.2 전체 아키텍처

```
┌─────────────────────────────────────────┐
│         IDE 확장 (VS Code Extension)     │
│                                          │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ 코드 에디터  │  │  Claude 패널 UI   │  │
│  └─────────────┘  └──────────────────┘  │
│         ↓ 파일 변경                ↑ 결과 │
└─────────────────────────────────────────┘
                    │
                    │ JWT 인증 + WebSocket/HTTP
                    │
┌─────────────────────────────────────────┐
│          Bridge 레이어 (src/bridge/)     │
│                                          │
│  bridgeMain.ts      → 메인 루프          │
│  bridgeMessaging.ts → 프로토콜           │
│  bridgePermissionCallbacks.ts → 권한     │
│  replBridge.ts      → REPL 통합          │
│  jwtUtils.ts        → JWT 인증           │
└─────────────────────────────────────────┘
                    │
                    ↓
┌─────────────────────────────────────────┐
│          Claude Code 코어               │
│  QueryEngine + Tools + Commands          │
└─────────────────────────────────────────┘
```

### 1.3 주요 파일

| 파일 | 역할 |
|------|------|
| `bridgeMain.ts` | 메인 루프 & 양방향 채널 시작 |
| `bridgeMessaging.ts` | 프로토콜 직렬화/역직렬화 |
| `bridgePermissionCallbacks.ts` | IDE로 권한 프롬프트 라우팅 |
| `bridgeApi.ts` | IDE에 노출된 API 표면 |
| `replBridge.ts` | REPL 세션을 브릿지와 연결 |
| `jwtUtils.ts` | JWT 기반 인증 |
| `sessionRunner.ts` | 브릿지 세션 실행 관리 |
| `createSession.ts` | 새 브릿지 세션 생성 |
| `inboundMessages.ts` | IDE에서 오는 메시지 처리 |
| `inboundAttachments.ts` | IDE 파일 첨부 처리 |
| `types.ts` | 브릿지 프로토콜 타입 |

### 1.4 브릿지 프로토콜 (bridgeMessaging.ts)

```typescript
// IDE → Claude Code 메시지 유형
type InboundMessage =
  | { type: 'user_message'; content: string; attachments?: Attachment[] }
  | { type: 'interrupt' }
  | { type: 'permission_response'; approved: boolean; rule?: string }
  | { type: 'file_changed'; path: string; content: string }
  | { type: 'diagnostic'; path: string; diagnostics: LSPDiagnostic[] }
  | { type: 'ping' }

// Claude Code → IDE 메시지 유형
type OutboundMessage =
  | { type: 'assistant_message'; content: MessageContent }
  | { type: 'tool_use'; toolName: string; input: unknown }
  | { type: 'tool_result'; toolName: string; output: string }
  | { type: 'permission_request'; action: string; details: string }
  | { type: 'file_edit'; path: string; diff: FileDiff }
  | { type: 'status'; isProcessing: boolean }
  | { type: 'pong' }
```

### 1.5 JWT 인증 (jwtUtils.ts)

```typescript
// IDE 연결 시 JWT 토큰으로 인증
export function generateBridgeToken(sessionId: string): string {
  return jwt.sign(
    { sessionId, iat: Date.now() },
    BRIDGE_SECRET_KEY,
    { expiresIn: '24h' }
  )
}

export function verifyBridgeToken(token: string): BridgeTokenPayload {
  return jwt.verify(token, BRIDGE_SECRET_KEY) as BridgeTokenPayload
}
```

### 1.6 권한 라우팅 (bridgePermissionCallbacks.ts)

```typescript
// CLI에서는 터미널에 권한 프롬프트 표시
// IDE 브릿지에서는 IDE 패널에 권한 프롬프트 전달

export function createBridgePermissionCallbacks(
  sendToIDE: (message: OutboundMessage) => void
): PermissionCallbacks {
  return {
    onPermissionRequest: async (action, details) => {
      // IDE에 권한 요청 전송
      sendToIDE({
        type: 'permission_request',
        action,
        details,
      })

      // IDE의 응답 대기
      const response = await waitForPermissionResponse()
      return response.approved
    },
  }
}
```

### 1.7 파일 감시 (inboundAttachments.ts)

```typescript
// IDE에서 파일 변경 사항을 Claude Code에 실시간 전달
// IDE의 파일 에디터와 Claude Code의 파일 시스템 동기화

interface FileAttachment {
  path: string
  content: string
  mimeType: string
  encoding: 'utf-8' | 'base64'
}
```

### 1.8 활성화 조건

```typescript
// IDE 브릿지는 BRIDGE_MODE 기능 플래그가 활성화된 빌드에서만 작동
// 일반 CLI 빌드에는 포함되지 않음

if (feature('BRIDGE_MODE')) {
  await startBridgeServer()
}
```

---

## 2. UI 컴포넌트 시스템 (src/components/)

### 2.1 기술 스택

| 기술 | 역할 |
|------|------|
| React 19 | 컴포넌트 트리 관리 |
| Ink | 터미널 렌더링 엔진 |
| React Compiler | 자동 메모이제이션 |
| Yoga Layout | Flexbox 레이아웃 (터미널용) |

### 2.2 컴포넌트 구조

```
src/components/
├── design-system/         # 기본 UI 빌딩 블록
│   ├── Text.tsx           # 스타일된 텍스트
│   ├── Box.tsx            # Flexbox 컨테이너
│   ├── Spinner.tsx        # 로딩 스피너
│   ├── Badge.tsx          # 배지/태그
│   └── Divider.tsx        # 구분선
│
├── messages/              # 메시지 렌더링
│   ├── AssistantMessage.tsx  # AI 응답
│   ├── UserMessage.tsx       # 사용자 입력
│   ├── ToolUseMessage.tsx    # 도구 호출 표시
│   ├── ToolResultMessage.tsx # 도구 결과 표시
│   └── ThinkingMessage.tsx   # Extended thinking
│
├── tools/                 # 도구별 특화 UI
│   ├── BashToolUI.tsx
│   ├── FileReadToolUI.tsx
│   ├── FileEditToolUI.tsx
│   ├── AgentToolUI.tsx
│   └── ...
│
├── input/                 # 사용자 입력
│   ├── PromptInput.tsx    # 메인 입력창
│   ├── MultilineInput.tsx # 여러 줄 입력
│   └── HistoryInput.tsx   # 히스토리 탐색
│
├── settings/              # 설정 UI
│   ├── SettingsPanel.tsx
│   ├── PermissionSettings.tsx
│   └── ThemeSettings.tsx
│
├── collaboration/         # 협업 UI
│   ├── AgentCursors.tsx   # 에이전트 커서 표시
│   └── TeamStatus.tsx     # 팀 상태
│
├── file-viewer/           # 파일 뷰어
│   ├── CodeViewer.tsx     # 문법 강조
│   ├── ImageViewer.tsx    # 이미지 표시
│   └── DiffViewer.tsx     # diff 시각화
│
├── notifications/         # 알림
│   ├── NotificationCenter.tsx
│   └── Toast.tsx
│
├── export/                # 내보내기
│   ├── ExportOptions.tsx
│   └── ShareDialog.tsx
│
└── layout/                # 레이아웃
    ├── Header.tsx
    ├── StatusBar.tsx
    └── Sidebar.tsx
```

### 2.3 메시지 렌더링

```tsx
// 대화 메시지 렌더링
function AssistantMessage({ message }: { message: AssistantMessage }) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* 에이전트 구분 색상 */}
      <Box>
        <Text color={getAgentColor(message.agentId)} bold>
          {getAgentName(message.agentId)} ●
        </Text>
      </Box>

      {/* 메시지 내용 블록들 */}
      {message.message.content.map((block, i) => {
        switch (block.type) {
          case 'text':
            return <MarkdownRenderer key={i} text={block.text} />

          case 'thinking':
            return <ThinkingBlock key={i} thinking={block.thinking} />

          case 'tool_use':
            return <ToolUseBlock key={i} toolUse={block} />
        }
      })}
    </Box>
  )
}
```

### 2.4 Markdown 렌더링

```tsx
// 터미널에서 Markdown 렌더링
function MarkdownRenderer({ text }: { text: string }) {
  const tokens = marked.lexer(text)

  return (
    <Box flexDirection="column">
      {tokens.map((token, i) => {
        switch (token.type) {
          case 'heading':
            return (
              <Text key={i} bold color="cyan">
                {'#'.repeat(token.depth)} {token.text}
              </Text>
            )

          case 'code':
            return (
              <Box key={i} marginLeft={2} borderLeft borderColor="gray">
                <Text color="green">
                  {highlightCode(token.text, token.lang)}
                </Text>
              </Box>
            )

          case 'list':
            return token.items.map((item, j) => (
              <Box key={j} marginLeft={2}>
                <Text>• {item.text}</Text>
              </Box>
            ))

          case 'paragraph':
            return <Text key={i}>{token.text}</Text>
        }
      })}
    </Box>
  )
}
```

### 2.5 Diff 시각화

```tsx
// 파일 변경사항 시각화
function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split('\n')

  return (
    <Box flexDirection="column">
      {lines.map((line, i) => {
        const color =
          line.startsWith('+') ? 'green' :
          line.startsWith('-') ? 'red' :
          line.startsWith('@') ? 'cyan' : 'gray'

        return (
          <Text key={i} color={color}>
            {line}
          </Text>
        )
      })}
    </Box>
  )
}
```

### 2.6 도구 실행 UI

```tsx
// BashTool 실행 UI (실시간 출력 표시)
function BashToolUI({ state }: { state: BashToolState }) {
  const { command, status, output, exitCode } = state

  return (
    <Box flexDirection="column" marginLeft={2}>
      {/* 명령어 헤더 */}
      <Box>
        <Text color="yellow" bold>$ </Text>
        <Text>{command}</Text>
        {status === 'running' && (
          <Box marginLeft={1}>
            <Spinner type="dots" />
          </Box>
        )}
      </Box>

      {/* 실시간 출력 */}
      {output && (
        <Box
          flexDirection="column"
          marginLeft={2}
          borderLeft
          borderColor="gray"
        >
          <Text>{output}</Text>
        </Box>
      )}

      {/* 완료 상태 */}
      {status === 'done' && (
        <Text color={exitCode === 0 ? 'green' : 'red'} dimColor>
          Exit: {exitCode}
        </Text>
      )}
    </Box>
  )
}
```

### 2.7 권한 다이얼로그

```tsx
// 도구 실행 권한 요청 UI
function PermissionDialog({
  action,
  details,
  onAllow,
  onAllowAlways,
  onDeny,
}: PermissionDialogProps) {
  const [selected, setSelected] = useState(0)
  const options = ['Allow once', 'Always allow', 'Deny']

  // 키보드 네비게이션
  useInput((input, key) => {
    if (key.leftArrow) setSelected(prev => Math.max(0, prev - 1))
    if (key.rightArrow) setSelected(prev => Math.min(2, prev + 1))
    if (key.return) {
      if (selected === 0) onAllow()
      if (selected === 1) onAllowAlways()
      if (selected === 2) onDeny()
    }
  })

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="yellow"
      padding={1}
    >
      <Text bold color="yellow">⚠️  권한 요청</Text>
      <Text>{action}</Text>
      <Text color="gray">{details}</Text>

      <Box marginTop={1} gap={2}>
        {options.map((option, i) => (
          <Box
            key={option}
            borderStyle={selected === i ? 'bold' : undefined}
            borderColor={selected === i ? 'cyan' : undefined}
            padding={0.5}
          >
            <Text color={selected === i ? 'cyan' : 'white'}>
              {option}
            </Text>
          </Box>
        ))}
      </Box>
    </Box>
  )
}
```

---

## 3. 스크린 (src/screens/)

### 3.1 REPL.tsx - 메인 REPL 화면

```tsx
// 메인 REPL 화면 구조
function REPL({ options }: REPLProps) {
  const [appState, setAppState] = useAppState(options)

  return (
    <Box flexDirection="column" height="100%">
      {/* 상단 헤더 */}
      <Header
        model={appState.settings.model}
        cost={appState.cost}
        isProcessing={appState.isProcessing}
      />

      {/* 메인 콘텐츠 영역 */}
      <Box flexGrow={1} flexDirection="column" overflow="hidden">
        {/* 메시지 목록 */}
        <MessageList messages={appState.messages} />

        {/* 에이전트 진행 상황 */}
        {appState.activeAgents.length > 0 && (
          <AgentProgressPanel agents={appState.activeAgents} />
        )}

        {/* 알림 */}
        <NotificationCenter notifications={appState.notifications} />
      </Box>

      {/* 하단 입력 영역 */}
      <Box flexDirection="column">
        <StatusBar
          mode={appState.permissionMode}
          tokenCount={getCurrentTokenCount(appState)}
        />
        <PromptInput
          value={appState.inputValue}
          onChange={value => setAppState(prev => ({ ...prev, inputValue: value }))}
          onSubmit={handleSubmit}
          commands={getCommands()}
        />
      </Box>
    </Box>
  )
}
```

### 3.2 Doctor.tsx - 진단 화면

```tsx
// /doctor 커맨드 실행 시 표시되는 환경 진단 화면
function DoctorScreen() {
  const [checks, setChecks] = useState<CheckResult[]>([])
  const [running, setRunning] = useState(true)

  useEffect(() => {
    runDiagnostics().then(results => {
      setChecks(results)
      setRunning(false)
    })
  }, [])

  return (
    <Box flexDirection="column" padding={1}>
      <Text bold>🔍 Claude Code 환경 진단</Text>

      {checks.map(check => (
        <Box key={check.name} gap={2}>
          <Text color={
            check.status === 'pass' ? 'green' :
            check.status === 'warn' ? 'yellow' : 'red'
          }>
            {check.status === 'pass' ? '✓' :
             check.status === 'warn' ? '⚠' : '✗'}
          </Text>
          <Text>{check.name}</Text>
          <Text color="gray">{check.message}</Text>
        </Box>
      ))}

      {running && <Spinner text="진단 중..." />}
    </Box>
  )
}
```

---

## 4. React 훅 (src/hooks/)

### 4.1 주요 훅 목록

**도구 권한 훅:**
```
hooks/toolPermission/
├── useToolPermission.ts      # 도구 실행 권한 확인
├── useBashPermission.ts      # Bash 전용 권한
├── useFilePermission.ts      # 파일 수정 권한
└── usePermissionMode.ts      # 권한 모드 관리
```

**상태 훅:**
```
hooks/
├── useAppState.ts            # 글로벌 앱 상태
├── useMessages.ts            # 메시지 목록 관리
├── useCost.ts                # 비용 추적
├── useModel.ts               # 모델 선택
└── useSettings.ts            # 설정 관리
```

**UI 훅:**
```
hooks/
├── useKeyBindings.ts         # 키바인딩 처리
├── useHistory.ts             # 입력 히스토리
├── useScrollToBottom.ts      # 자동 스크롤
├── useTerminalSize.ts        # 터미널 크기 감지
└── useNotifications.ts       # 알림 관리
```

### 4.2 useToolPermission.ts

```typescript
export function useToolPermission() {
  const { appState, setAppState } = useAppState()

  const checkPermission = useCallback(async (
    tool: Tool,
    input: unknown
  ): Promise<PermissionResult> => {
    // 이미 허용된 규칙 확인
    const existingRule = findMatchingRule(
      appState.toolPermissionContext.rules,
      tool.name,
      input
    )

    if (existingRule) {
      return { granted: existingRule.granted }
    }

    // 권한 모드 확인
    if (appState.permissionMode === 'bypassPermissions') {
      return { granted: true }
    }

    // 사용자에게 확인 요청
    return await requestUserPermission(tool, input, setAppState)
  }, [appState, setAppState])

  return { checkPermission }
}
```

### 4.3 useKeyBindings.ts

```typescript
// 글로벌 키바인딩 관리
export function useKeyBindings() {
  const { appState, setAppState } = useAppState()

  useInput((input, key) => {
    // 기본 키바인딩
    if (key.ctrl && input === 'c') {
      handleInterrupt()
    }
    if (key.ctrl && input === 'r') {
      openHistorySearch()
    }
    if (key.escape) {
      closeCurrentPanel()
    }

    // 사용자 정의 키바인딩 (keybindings.json)
    const customBindings = loadCustomKeybindings()
    for (const binding of customBindings) {
      if (matchesKeybinding(key, input, binding.key)) {
        executeAction(binding.action)
      }
    }
  })
}
```

---

## 5. Ink 렌더링 시스템

### 5.1 Ink란?

Ink는 React를 사용하여 터미널 UI를 만들 수 있게 해주는 라이브러리입니다. HTML/CSS 대신 Yoga(Flexbox) 레이아웃을 사용합니다.

```tsx
// 웹에서의 React
<div style={{ display: 'flex', flexDirection: 'column' }}>
  <h1>Hello</h1>
  <p>World</p>
</div>

// 터미널에서의 Ink
<Box flexDirection="column">
  <Text bold>Hello</Text>
  <Text>World</Text>
</Box>
```

### 5.2 사용자 정의 Ink 확장 (src/ink/)

```
src/ink/
├── components/        # Ink 기본 컴포넌트 래퍼
├── hooks/             # Ink 전용 훅
└── utils/             # Ink 유틸리티
```

### 5.3 React Compiler 최적화

```tsx
// React Compiler가 자동으로 메모이제이션 추가
// 개발자가 useMemo, useCallback 수동 추가 불필요

function ExpensiveComponent({ data }) {
  // React Compiler: 자동으로 최적화
  const processed = processData(data)

  return <Box>{processed.map(item => <Item key={item.id} item={item} />)}</Box>
}
```

### 5.4 ANSI 컬러 시스템

```typescript
// 터미널 컬러 팔레트
const COLORS = {
  // 기본 256색
  primary: 'cyan',
  success: 'green',
  warning: 'yellow',
  error: 'red',
  muted: 'gray',

  // 에이전트별 고유 색상 (agentColorManager.ts)
  agentColors: [
    '#FF6B6B', '#4ECDC4', '#45B7D1',
    '#96CEB4', '#FFEAA7', '#DDA0DD',
  ],
}

// 24비트 트루컬러 지원 (지원하는 터미널에서)
if (supportsColor.has16m) {
  // RGB 색상 사용 가능
}
```

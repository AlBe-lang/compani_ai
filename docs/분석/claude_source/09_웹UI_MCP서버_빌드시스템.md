# Claude Code 소스코드 분석 - 09. 웹 UI & MCP 서버 & 빌드 시스템

> 분석 대상: `web/`, `mcp-server/`, `scripts/`, `prompts/`, `docker/`

---

## 1. 웹 UI (web/)

### 1.1 역할

터미널이 아닌 **웹 브라우저에서 Claude Code를 사용**할 수 있게 해주는 Next.js 기반 웹 인터페이스입니다.

### 1.2 기술 스택

| 기술 | 버전 | 역할 |
|------|------|------|
| Next.js | 14+ | 풀스택 React 프레임워크 |
| React | 19 | UI 컴포넌트 |
| TypeScript | 5.x | 타입 안전성 |
| Tailwind CSS | 3.x | 스타일링 |
| shadcn/ui | 최신 | UI 컴포넌트 라이브러리 |
| Yjs | 최신 | 실시간 협업 (CRDT) |
| xterm.js | 5.x | 터미널 에뮬레이션 |

### 1.3 전체 구조

```
web/
├── app/                          # Next.js 앱 라우터
│   ├── layout.tsx                # 루트 레이아웃
│   ├── page.tsx                  # 메인 페이지
│   ├── globals.css               # 전역 스타일
│   └── api/                      # API 라우트
│       ├── chat/                 # 채팅 엔드포인트
│       │   └── route.ts          # POST /api/chat
│       ├── files/                # 파일 API
│       │   ├── read/route.ts     # GET /api/files/read
│       │   └── write/route.ts    # POST /api/files/write
│       ├── share/                # 공유 API
│       │   ├── route.ts          # POST /api/share
│       │   └── [shareId]/        # GET /api/share/:id
│       └── export/               # 내보내기 API
│           └── route.ts          # POST /api/export
│
├── components/                   # React 컴포넌트
│   ├── ui/                       # 기본 UI 컴포넌트 (shadcn)
│   │   ├── button.tsx
│   │   ├── dialog.tsx
│   │   ├── dropdown-menu.tsx
│   │   └── ...
│   ├── chat/                     # 채팅 UI
│   │   ├── ChatWindow.tsx        # 메인 채팅 창
│   │   ├── MessageList.tsx       # 메시지 목록
│   │   ├── MessageItem.tsx       # 개별 메시지
│   │   └── InputBar.tsx          # 입력창
│   ├── tools/                    # 도구 UI
│   │   ├── BashOutput.tsx        # Bash 출력
│   │   ├── FileViewer.tsx        # 파일 뷰어
│   │   └── DiffViewer.tsx        # diff 시각화
│   ├── settings/                 # 설정 UI
│   ├── collaboration/            # 협업 UI
│   ├── file-viewer/              # 파일 뷰어
│   ├── notifications/            # 알림
│   ├── export/                   # 내보내기
│   ├── mobile/                   # 모바일 최적화
│   ├── command-palette/          # 커맨드 팔레트
│   └── layout/                   # 레이아웃 컴포넌트
│
├── hooks/                        # React 훅
│   ├── useChat.ts               # 채팅 상태 관리
│   ├── useWebSocket.ts          # WebSocket 연결
│   ├── useFileSystem.ts         # 파일 시스템 접근
│   └── useCollaboration.ts      # 협업 상태
│
├── lib/                          # 유틸리티
│   ├── api.ts                   # API 클라이언트
│   ├── auth.ts                  # 인증 유틸리티
│   ├── markdown.ts              # Markdown 파싱
│   └── syntax-highlight.ts      # 문법 강조
│
└── public/                       # 정적 자산
    ├── favicon.ico
    └── icons/
```

### 1.4 채팅 API 라우트

```typescript
// app/api/chat/route.ts
export async function POST(request: Request) {
  const { message, sessionId, model } = await request.json()

  // SDK를 통해 Claude Code 쿼리 엔진 호출
  const stream = await queryStream({
    userMessage: message,
    sessionId,
    model,
  })

  // 스트리밍 응답 반환 (Server-Sent Events)
  return new Response(
    new ReadableStream({
      async start(controller) {
        for await (const chunk of stream) {
          controller.enqueue(encode(JSON.stringify(chunk) + '\n'))
        }
        controller.close()
      }
    }),
    {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      }
    }
  )
}
```

### 1.5 실시간 협업 (Yjs)

```typescript
// 여러 사용자가 동시에 같은 세션 참여
// CRDT(Conflict-free Replicated Data Type)로 충돌 없는 병합

// 협업 컴포넌트
function CollaborationProvider({ children }) {
  const ydoc = new Y.Doc()
  const provider = new WebsocketProvider(WS_URL, sessionId, ydoc)

  // 공유 상태
  const sharedMessages = ydoc.getArray('messages')
  const sharedCursors = ydoc.getMap('cursors')

  return (
    <CollaborationContext.Provider value={{ ydoc, sharedMessages, sharedCursors }}>
      {children}
    </CollaborationContext.Provider>
  )
}
```

### 1.6 터미널 에뮬레이션 (xterm.js)

```tsx
// 웹 브라우저에서 완전한 터미널 에뮬레이션
function TerminalView({ sessionId }) {
  const termRef = useRef<HTMLDivElement>(null)
  const term = useRef<Terminal>()

  useEffect(() => {
    term.current = new Terminal({
      theme: { background: '#1e1e1e', foreground: '#d4d4d4' },
      fontSize: 14,
      fontFamily: "'Cascadia Code', 'Fira Code', monospace",
      cursorBlink: true,
    })

    const fitAddon = new FitAddon()
    term.current.loadAddon(fitAddon)
    term.current.open(termRef.current!)
    fitAddon.fit()

    // WebSocket으로 터미널 데이터 전송/수신
    const ws = new WebSocket(`${WS_URL}/terminal/${sessionId}`)
    ws.onmessage = (event) => term.current!.write(event.data)
    term.current.onData(data => ws.send(data))

    return () => {
      term.current?.dispose()
      ws.close()
    }
  }, [sessionId])

  return <div ref={termRef} style={{ height: '100%' }} />
}
```

### 1.7 파일 뷰어

```tsx
// 코드, 이미지, PDF 등 다양한 파일 형식 지원
function FileViewer({ file }: { file: FileData }) {
  if (file.type === 'image') {
    return <img src={file.dataUrl} alt={file.name} className="max-w-full" />
  }

  if (file.type === 'pdf') {
    return <PDFViewer url={file.url} />
  }

  // 코드 파일
  return (
    <SyntaxHighlighter
      language={detectLanguage(file.name)}
      style={vscDarkPlus}
      showLineNumbers
      wrapLines
    >
      {file.content}
    </SyntaxHighlighter>
  )
}
```

---

## 2. MCP 서버 (mcp-server/)

### 2.1 역할

Claude Code를 **MCP(Model Context Protocol) 서버**로 노출합니다. 다른 AI 도구(Claude Desktop, VS Code Copilot 등)에서 Claude Code의 기능을 MCP 도구로 사용할 수 있게 합니다.

### 2.2 서버 메타데이터 (server.json)

```json
{
  "name": "claude-code-explorer-mcp",
  "version": "1.1.0",
  "description": "Claude Code source code explorer via MCP",
  "author": "Anthropic",
  "license": "MIT"
}
```

### 2.3 서버 구현 (src/server.ts, 31KB)

```typescript
// MCP 서버 초기화
const server = new Server(
  {
    name: "claude-code-explorer-mcp",
    version: "1.1.0",
  },
  {
    capabilities: {
      tools: {},
      resources: {},
    }
  }
)

// 도구 목록 핸들러
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "list_tools",
      description: "Claude Code에서 사용 가능한 모든 도구 목록",
      inputSchema: { type: "object", properties: {} }
    },
    {
      name: "list_commands",
      description: "사용 가능한 모든 슬래시 커맨드 목록",
      inputSchema: { type: "object", properties: {} }
    },
    {
      name: "get_tool_source",
      description: "특정 도구의 소스코드 반환",
      inputSchema: {
        type: "object",
        properties: {
          tool_name: { type: "string", description: "도구 이름" }
        },
        required: ["tool_name"]
      }
    },
    {
      name: "get_command_source",
      description: "특정 커맨드의 소스코드 반환",
      inputSchema: {
        type: "object",
        properties: {
          command_name: { type: "string" }
        },
        required: ["command_name"]
      }
    },
    {
      name: "read_source_file",
      description: "소스 파일 직접 읽기",
      inputSchema: {
        type: "object",
        properties: {
          file_path: { type: "string" }
        },
        required: ["file_path"]
      }
    },
    {
      name: "search_source",
      description: "소스코드에서 패턴 검색",
      inputSchema: {
        type: "object",
        properties: {
          pattern: { type: "string" },
          file_glob: { type: "string" }
        },
        required: ["pattern"]
      }
    },
    {
      name: "list_directory",
      description: "디렉토리 내용 나열",
      inputSchema: {
        type: "object",
        properties: {
          path: { type: "string" }
        }
      }
    },
    {
      name: "get_architecture",
      description: "전체 아키텍처 개요 반환",
      inputSchema: { type: "object", properties: {} }
    }
  ]
}))
```

### 2.4 도구 실행 핸들러

```typescript
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params

  switch (name) {
    case "list_tools": {
      const tools = getTools()
      return {
        content: [{
          type: "text",
          text: tools.map(t => `- **${t.name}**: ${t.description}`).join('\n')
        }]
      }
    }

    case "get_tool_source": {
      const { tool_name } = args
      const toolDir = path.join(SRC_DIR, 'tools', `${tool_name}Tool`)
      const files = readdirSync(toolDir)
      const source = files
        .filter(f => f.endsWith('.ts') || f.endsWith('.tsx'))
        .map(f => readFileSync(path.join(toolDir, f), 'utf-8'))
        .join('\n\n---\n\n')

      return { content: [{ type: "text", text: source }] }
    }

    case "search_source": {
      const { pattern, file_glob = '**/*.ts' } = args
      const results = execSync(
        `rg "${pattern}" --glob "${file_glob}" -n`,
        { cwd: SRC_DIR }
      ).toString()

      return { content: [{ type: "text", text: results }] }
    }

    // ... 다른 도구들
  }
})
```

### 2.5 전송 방식

```typescript
// HTTP 전송 (src/http.ts)
export function createHTTPServer(port: number = 3000): void {
  const app = express()

  // MCP 엔드포인트
  app.post('/mcp', express.json(), async (req, res) => {
    const response = await server.handleRequest(req.body)
    res.json(response)
  })

  // SSE 스트리밍
  app.get('/mcp/stream', (req, res) => {
    res.setHeader('Content-Type', 'text/event-stream')
    // SSE 스트림 처리
  })

  app.listen(port, () => {
    console.log(`MCP 서버 실행 중: http://localhost:${port}`)
  })
}
```

### 2.6 배포

```bash
# npm 패키지로 설치
npm install -g claude-code-explorer-mcp

# Claude Code에 MCP 서버로 등록
claude mcp add claude-code-explorer -- npx -y claude-code-explorer-mcp

# Vercel에 배포
# vercel.json 설정 참조
```

### 2.7 Vercel 배포 설정 (vercel.json)

```json
{
  "functions": {
    "mcp-server/api/index.ts": {
      "runtime": "@vercel/node"
    }
  },
  "routes": [
    {
      "src": "/mcp/(.*)",
      "dest": "/mcp-server/api/index.ts"
    }
  ]
}
```

---

## 3. 빌드 시스템

### 3.1 빌드 파이프라인 개요

```
TypeScript 소스
      ↓
[Bun 번들러]
  - JSX 변환
  - bun:bundle 기능 플래그 (데드 코드 제거)
  - 의존성 번들링
      ↓
[esbuild 최적화]
  - 코드 축소화 (minification)
  - 트리 쉐이킹
  - 소스맵 생성/제거
      ↓
단일 실행 파일 (claude)
```

### 3.2 build-bundle.ts

```typescript
// 메인 빌드 스크립트
async function buildBundle(options: BuildOptions = {}) {
  const { production = false, watch = false } = options

  const result = await Bun.build({
    entrypoints: ['src/entrypoints/cli.tsx'],
    outdir: 'dist',
    target: 'bun',
    format: 'esm',

    // 기능 플래그 (데드 코드 제거)
    define: {
      'feature("BRIDGE_MODE")': JSON.stringify(false),
      'feature("VOICE_MODE")': JSON.stringify(false),
      'feature("PROACTIVE")': JSON.stringify(false),
      'feature("KAIROS")': JSON.stringify(false),
      // ... 배포 환경에 따라 다르게 설정
    },

    minify: production,
    sourcemap: production ? 'none' : 'external',

    external: [
      // 번들에 포함하지 않는 패키지들
      'node-pty',    // 네이티브 바인딩
      'fsevents',    // macOS 파일 감시
    ],
  })

  if (!result.success) {
    console.error('빌드 실패:', result.logs)
    process.exit(1)
  }

  // 실행 권한 설정
  chmodSync('dist/cli.js', '755')

  console.log(`빌드 완료: ${result.outputs[0].path}`)
}
```

### 3.3 기능 플래그별 빌드

```typescript
// 다양한 배포 대상별 기능 플래그
const BUILD_CONFIGURATIONS = {
  // 공개 npm 패키지
  'npm-public': {
    BRIDGE_MODE: false,
    VOICE_MODE: false,
    PROACTIVE: false,
    KAIROS: false,
    COORDINATOR_MODE: false,
  },

  // IDE 확장용 빌드
  'ide-extension': {
    BRIDGE_MODE: true,    // IDE 브릿지 활성화
    VOICE_MODE: false,
    PROACTIVE: false,
    KAIROS: false,
  },

  // 내부 직원용 빌드
  'internal-ant': {
    BRIDGE_MODE: true,
    VOICE_MODE: true,
    PROACTIVE: true,
    KAIROS: true,
    COORDINATOR_MODE: true,
  },
}
```

### 3.4 빌드 스크립트 목록 (scripts/)

| 스크립트 | 역할 |
|---------|------|
| `build-bundle.ts` | 메인 CLI 번들링 |
| `build-web.ts` | Next.js 웹 UI 빌드 |
| `build.sh` | 전체 빌드 (CLI + 웹) |
| `dev.ts` | 개발 서버 (hot-reload) |
| `test-mcp.ts` | MCP 서버 테스트 |
| `test-services.ts` | 서비스 테스트 |
| `generate-types.ts` | 타입 자동 생성 |
| `migrate-settings.ts` | 설정 마이그레이션 |

### 3.5 개발 서버 (dev.ts)

```typescript
// 개발 모드: 파일 변경 시 자동 재빌드
async function startDevServer() {
  // 1. 초기 빌드
  await buildBundle({ production: false })

  // 2. 파일 감시자 설정
  const watcher = fs.watch('src/', { recursive: true }, async (event, filename) => {
    if (!filename?.endsWith('.ts') && !filename?.endsWith('.tsx')) return

    console.log(`변경 감지: ${filename}`)
    await buildBundle({ production: false })
    console.log('재빌드 완료')
  })

  // 3. Claude Code 프로세스 실행
  const claude = spawn('node', ['dist/cli.js'], { stdio: 'inherit' })

  // 종료 시 정리
  process.on('SIGINT', () => {
    watcher.close()
    claude.kill()
    process.exit(0)
  })
}
```

---

## 4. 빌드 가이드 프롬프트 (prompts/)

프롬프트 폴더에는 **이 소스코드를 직접 빌드하는 방법**을 Claude에게 단계별로 가르치는 16개의 마크다운 파일이 있습니다:

### 4.1 프롬프트 목록

| 번호 | 파일명 | 내용 |
|------|--------|------|
| 00 | `00-overview.md` | 전체 빌드 과정 개요 |
| 01 | `01-install-bun-and-deps.md` | Bun 설치 및 의존성 설치 |
| 02 | `02-runtime-shims.md` | Bun shim 파일 생성 |
| 03 | `03-build-config.md` | esbuild 빌드 설정 |
| 04 | `04-fix-mcp-server.md` | MCP 서버 빌드 수정 |
| 05 | `05-env-and-auth.md` | .env 설정 및 OAuth 구성 |
| 06 | `06-ink-react-terminal-ui.md` | Ink/React 렌더링 검증 |
| 07 | `07-tool-system.md` | 도구 시스템 검증 |
| 08 | `08-command-system.md` | 커맨드 시스템 검증 |
| 09 | `09-query-engine.md` | QueryEngine 기능화 |
| 10 | `10-context-and-prompts.md` | 시스템 프롬프트 구성 |
| 11 | `11-mcp-integration.md` | MCP 클라이언트/서버 통합 |
| 12 | `12-services-layer.md` | 서비스 레이어 (분석, 설정) |
| 13 | `13-bridge-ide.md` | IDE 브릿지 설정 |
| 14 | `14-dev-runner.md` | 개발 서버 실행 |
| 15 | `15-production-bundle.md` | 프로덕션 번들 생성 |
| 16 | `16-testing.md` | 테스트 인프라 구성 |

### 4.2 주요 빌드 이슈와 해결책

```markdown
<!-- prompts/02-runtime-shims.md 발췌 -->
# Bun Runtime Shims

Claude Code uses `bun:bundle` for feature flags. When building outside of Bun,
you need to create shim files:

## Problem
`import { feature } from 'bun:bundle'` fails in Node.js

## Solution
Create `src/shims/bun-bundle.ts`:
```typescript
export function feature(flagName: string): boolean {
  // In production Bun builds, this is replaced at build time
  // In development, read from environment variables
  return process.env[`FEATURE_${flagName.toUpperCase()}`] === 'true'
}
```

Then add path alias in tsconfig.json:
```json
{
  "paths": {
    "bun:bundle": ["./src/shims/bun-bundle.ts"]
  }
}
```
```

---

## 5. Docker 설정 (docker/)

### 5.1 Dockerfile

```dockerfile
# 다단계 빌드
FROM oven/bun:1 AS builder
WORKDIR /app

# 의존성 설치
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# 소스 복사 및 빌드
COPY . .
RUN bun run build

# 실행 이미지
FROM debian:bookworm-slim
WORKDIR /app

# Bun 런타임 설치
RUN curl -fsSL https://bun.sh/install | bash

# 빌드 결과물 복사
COPY --from=builder /app/dist/cli.js ./claude
RUN chmod +x ./claude

ENTRYPOINT ["./claude"]
```

### 5.2 docker-compose.yml

```yaml
version: '3.8'
services:
  claude-code:
    build: .
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - ./workspace:/workspace
    working_dir: /workspace
    stdin_open: true
    tty: true

  mcp-server:
    build:
      context: .
      dockerfile: mcp-server/Dockerfile
    ports:
      - "3000:3000"
    environment:
      - SOURCE_DIR=/app/src
```

### 5.3 entrypoint.sh

```bash
#!/bin/bash
set -e

# 환경 변수 검증
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "오류: ANTHROPIC_API_KEY가 설정되지 않았습니다."
  exit 1
fi

# Claude Code 실행
exec ./claude "$@"
```

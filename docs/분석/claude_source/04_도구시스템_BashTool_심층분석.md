# Claude Code 소스코드 분석 - 04. BashTool 심층 분석

> 분석 대상: `src/tools/BashTool/` (16개 파일, ~370KB)
> BashTool은 Claude Code에서 가장 크고 복잡한 도구입니다.

---

## 1. BashTool 개요

### 1.1 역할

BashTool은 **셸 명령어를 실행**하는 도구입니다. 단순해 보이지만, 보안, 권한, 경로 검증, 실시간 출력 등 수많은 복잡한 로직을 포함합니다.

### 1.2 파일 구조

| 파일 | 크기 | 역할 |
|------|------|------|
| `BashTool.tsx` | 160KB | 메인 구현, 실행 로직 |
| `bashSecurity.ts` | 102KB | 보안 검증 (AST 분석) |
| `bashPermissions.ts` | 98KB | 권한 확인 로직 |
| `readOnlyValidation.ts` | 68KB | 읽기 전용 검증 |
| `pathValidation.ts` | 43KB | 경로 검증 |
| `sedValidation.ts` | 21KB | Sed 편집 파서 |
| `prompt.ts` | 21KB | 시스템 프롬프트 |
| `UI.tsx` | 25KB | UI 컴포넌트 |
| `BashToolResultMessage.tsx` | - | 결과 메시지 렌더러 |
| `bashCommandHelpers.ts` | 8.6KB | 헬퍼 함수 |
| `commandSemantics.ts` | 3.6KB | 명령어 의미론 |
| `modeValidation.ts` | - | 모드 검증 |
| `sedEditParser.ts` | - | Sed 편집 파서 |
| `shouldUseSandbox.ts` | - | 샌드박스 결정 로직 |
| `toolName.ts` | - | 도구 이름 상수 |

---

## 2. 입력 스키마

```typescript
{
  command: string          // 실행할 Bash 명령어
  timeout?: number         // 타임아웃 (밀리초, 기본: 120000 = 2분)
  description?: string     // 명령어 설명 (UI 표시용)
}
```

---

## 3. 실행 흐름

```
사용자/LLM이 BashTool 호출
         ↓
[1. 보안 검증] bashSecurity.ts
   - AST 파싱 (Bash 문법 분석)
   - 위험한 명령어 감지
   - 인젝션 공격 방지
         ↓
[2. 권한 확인] bashPermissions.ts
   - 설정된 규칙과 매칭
   - 사용자 승인 요청 (필요시)
         ↓
[3. 읽기 전용 검증] readOnlyValidation.ts
   - read-only 모드에서 쓰기 명령어 차단
         ↓
[4. 경로 검증] pathValidation.ts
   - 경로 순회 공격 방지
   - 허용된 디렉토리 확인
         ↓
[5. 실행 결정]
   - 단기 명령어(< 2초): 동기 실행
   - 장기 명령어(≥ 2초): 백그라운드 실행
         ↓
[6. 명령어 실행]
   node-pty 또는 child_process.exec
         ↓
[7. 출력 처리]
   - ANSI 컬러 지원
   - 줄 수 세기
   - 이미지 감지
   - 크기 제한 처리
         ↓
[8. 결과 반환]
```

---

## 4. 보안 검증 (bashSecurity.ts, 102KB)

### 4.1 AST 기반 분석

BashTool은 단순 문자열 매칭이 아닌 **AST(Abstract Syntax Tree) 파싱**을 통해 명령어를 분석합니다:

```typescript
// bash/ast.js를 사용한 AST 파싱
import { parse } from './bash/ast.js'

function analyzeCommand(command: string): SecurityAnalysis {
  const ast = parse(command)

  return {
    hasRiskyOperations: detectRiskyOperations(ast),
    hasInjectionRisk: detectInjectionRisk(ast),
    involvedPaths: extractPaths(ast),
    commandTypes: extractCommandTypes(ast),
  }
}
```

### 4.2 위험 명령어 감지

```typescript
// 위험 명령어 패턴 목록 (예시)
const DANGEROUS_PATTERNS = [
  // 파일 시스템 파괴
  { pattern: /rm\s+-rf\s+\//, level: 'critical', message: '루트 디렉토리 삭제 시도' },
  { pattern: /rm\s+-rf\s+~/, level: 'critical', message: '홈 디렉토리 삭제 시도' },

  // Git 파괴적 작업
  { pattern: /git\s+reset\s+--hard/, level: 'high', message: 'git reset --hard' },
  { pattern: /git\s+push\s+.*--force/, level: 'high', message: 'git push --force' },
  { pattern: /git\s+branch\s+-D/, level: 'medium', message: '브랜치 강제 삭제' },

  // 시스템 명령어
  { pattern: /sudo\s+/, level: 'high', message: 'sudo 사용' },
  { pattern: /chmod\s+777/, level: 'medium', message: '전체 권한 부여' },

  // 네트워크
  { pattern: /curl.*\|.*bash/, level: 'critical', message: '원격 스크립트 실행' },
  { pattern: /wget.*-O-.*\|.*sh/, level: 'critical', message: '원격 스크립트 실행' },

  // 환경 변수 조작
  { pattern: /export\s+API_KEY/, level: 'medium', message: 'API 키 환경변수 설정' },
]
```

### 4.3 주입 공격 방지

```typescript
function detectInjectionRisk(ast: BashAST): boolean {
  // 사용자 입력이 명령어에 직접 삽입되는 패턴 감지
  // 예: command = `ls ${userInput}` (인젝션 위험)

  // 서브쉘 내 변수 확장 검사
  // 파이프라인에서의 위험한 조합 검사
  // Heredoc 내 인젝션 검사
}
```

---

## 5. 권한 확인 (bashPermissions.ts, 98KB)

### 5.1 권한 규칙 매칭

```typescript
type BashPermissionRule = {
  pattern: string    // 예: "git *", "npm test", "ls *"
  granted: boolean
}

function matchesBashRule(command: string, rule: BashPermissionRule): boolean {
  // 1. 정확한 매칭
  if (command === rule.pattern) return true

  // 2. 와일드카드 매칭
  // "git *" → git으로 시작하는 모든 명령어
  if (rule.pattern.endsWith(' *')) {
    const prefix = rule.pattern.slice(0, -2)
    return command.startsWith(prefix + ' ') || command === prefix
  }

  // 3. 전체 와일드카드
  if (rule.pattern === '*') return true

  return false
}
```

### 5.2 Git 명령어 특별 처리

```typescript
// Git 명령어는 별도 세분화 처리
function analyzeGitCommand(command: string): GitCommandAnalysis {
  const parts = command.split(' ')
  const subcommand = parts[1]  // git <subcommand>

  return {
    isDestructive: ['reset', 'clean', 'push'].includes(subcommand),
    requiresRemoteAccess: ['push', 'pull', 'fetch', 'clone'].includes(subcommand),
    modifiesHistory: ['rebase', 'commit', 'merge', 'cherry-pick'].includes(subcommand),
  }
}
```

### 5.3 권한 부여 방식

**설정 파일에서 규칙 추가:**
```json
// .claude/settings.json
{
  "permissions": {
    "allow": [
      "Bash(git *)",
      "Bash(npm test)",
      "Bash(npm run *)",
      "Bash(python *)"
    ],
    "deny": [
      "Bash(rm -rf *)"
    ]
  }
}
```

**대화 중 허용:**
```
Claude가 실행하려는 명령어: rm -rf node_modules

[ Allow once ] [ Always allow: rm -rf node_modules ] [ Deny ] [ Always deny ]
```

---

## 6. 읽기 전용 검증 (readOnlyValidation.ts, 68KB)

### 6.1 읽기 전용 명령어 판별

```typescript
const READ_ONLY_COMMANDS = new Set([
  'cat', 'ls', 'find', 'grep', 'head', 'tail', 'wc',
  'file', 'stat', 'echo', 'pwd', 'which', 'whereis',
  'git log', 'git status', 'git diff', 'git show',
  'npm list', 'pip list', 'cargo tree',
])

function isReadOnlyCommand(command: string): boolean {
  // AST 분석으로 파일 시스템 수정 여부 판별
  const ast = parse(command)
  return !hasWriteOperations(ast)
}
```

### 6.2 파이프라인 분석

```typescript
// 파이프라인에서 각 단계를 개별 분석
// cat file.txt | grep "pattern" | wc -l
// → [cat: 읽기] | [grep: 읽기] | [wc: 읽기] → 전체 읽기 전용

// cat file.txt | tee output.txt
// → [cat: 읽기] | [tee: 쓰기] → 전체 쓰기 포함!
```

---

## 7. 경로 검증 (pathValidation.ts, 43KB)

### 7.1 경로 순회 공격 방지

```typescript
function validatePath(targetPath: string, allowedBase: string): boolean {
  // 정규화된 절대 경로로 변환
  const resolved = path.resolve(targetPath)

  // 허용된 기본 경로 내에 있는지 확인
  if (!resolved.startsWith(allowedBase + path.sep) &&
      resolved !== allowedBase) {
    throw new SecurityError(
      `경로 순회 공격 감지: ${targetPath} → ${resolved}`
    )
  }

  return true
}
```

### 7.2 심볼릭 링크 처리

```typescript
// 심볼릭 링크가 허용 범위를 벗어나는지 확인
async function validateSymlink(linkPath: string, allowedBase: string): Promise<boolean> {
  const realPath = await fs.realpath(linkPath)
  return validatePath(realPath, allowedBase)
}
```

---

## 8. Sed 검증 (sedValidation.ts, 21KB)

### 8.1 Sed 명령어 파서

`sed`는 파일 내용을 수정하는 강력한 도구입니다. BashTool은 `sed` 명령어를 특별히 파싱하여 무엇을 변경하는지 분석합니다:

```typescript
interface SedEdit {
  type: 'substitute' | 'delete' | 'insert' | 'append'
  address?: string      // 적용할 줄 번호/패턴
  pattern?: string      // 검색 패턴 (s 명령)
  replacement?: string  // 교체 문자열 (s 명령)
  flags?: string        // 플래그 (g, i, p 등)
}

function parseSedCommand(command: string): SedEdit[] {
  // sed 's/old/new/g' file.txt 파싱
  // sed -n '1,5p' file.txt 파싱
  // sed '/pattern/d' file.txt 파싱
}
```

---

## 9. 실행 메커니즘

### 9.1 동기 실행 vs 백그라운드 실행

```typescript
async call({ command, timeout = 120000 }) {
  const startTime = Date.now()

  // 백그라운드 실행 기준:
  // - timeout > 2초이고 실제로 2초 이상 걸리는 경우
  const BACKGROUND_THRESHOLD = 2000

  // node-pty로 의사 터미널 생성
  const pty = spawn('/bin/bash', ['-c', command], {
    name: 'xterm-256color',  // ANSI 컬러 지원
    cols: 220,
    rows: 50,
    env: process.env,
  })

  let output = ''
  let isBackground = false

  pty.on('data', (data) => {
    output += data

    // 2초 경과 후 백그라운드로 전환
    if (!isBackground && Date.now() - startTime > BACKGROUND_THRESHOLD) {
      isBackground = true
      showBackgroundNotification()
    }
  })

  await waitForExit(pty, timeout)

  return { data: output, exitCode: pty.exitCode }
}
```

### 9.2 출력 처리

```typescript
function processOutput(rawOutput: string): ProcessedOutput {
  // 1. ANSI 이스케이프 처리 (컬러, 커서 이동 등)
  const ansiStripped = stripAnsi(rawOutput)

  // 2. 줄 수 계산
  const lineCount = rawOutput.split('\n').length

  // 3. 이미지 감지 (kitty 프로토콜, iTerm2 인라인 이미지)
  const hasInlineImage = detectInlineImage(rawOutput)

  // 4. 크기 제한 처리
  if (rawOutput.length > MAX_OUTPUT_SIZE) {
    return {
      data: `[출력이 너무 큽니다. 처음 ${MAX_OUTPUT_SIZE}자만 표시]\n\n` +
            rawOutput.slice(0, MAX_OUTPUT_SIZE),
      truncated: true,
    }
  }

  return { data: rawOutput, lineCount, hasInlineImage }
}
```

---

## 10. UI 컴포넌트 (UI.tsx, 25KB)

### 10.1 명령어 표시

```tsx
// 실행 중인 명령어 표시
function BashToolUI({ command, status, output, progress }) {
  return (
    <Box flexDirection="column">
      {/* 명령어 헤더 */}
      <Box>
        <Text color="yellow">$ </Text>
        <Text>{command}</Text>
        {status === 'running' && <Spinner />}
      </Box>

      {/* 실시간 출력 */}
      {output && (
        <Box marginLeft={2} flexDirection="column">
          <Text>{output}</Text>
        </Box>
      )}

      {/* 백그라운드 실행 표시 */}
      {status === 'background' && (
        <Text color="gray">[ 백그라운드 실행 중... ]</Text>
      )}

      {/* 종료 코드 */}
      {status === 'done' && (
        <Text color={exitCode === 0 ? 'green' : 'red'}>
          종료 코드: {exitCode}
        </Text>
      )}
    </Box>
  )
}
```

### 10.2 권한 다이얼로그

```tsx
// 권한 확인 다이얼로그
function BashPermissionDialog({ command, onAllow, onDeny }) {
  return (
    <Box borderStyle="round" borderColor="yellow" flexDirection="column">
      <Text bold>다음 명령어를 실행하려고 합니다:</Text>
      <Text color="cyan">{command}</Text>
      <Box marginTop={1}>
        <Text>[ </Text>
        <Text color="green" onClick={onAllow}>허용</Text>
        <Text> ] [ </Text>
        <Text color="green" onClick={() => onAllow({ always: true })}>
          항상 허용
        </Text>
        <Text> ] [ </Text>
        <Text color="red" onClick={onDeny}>거부</Text>
        <Text> ]</Text>
      </Box>
    </Box>
  )
}
```

---

## 11. 시스템 프롬프트 (prompt.ts, 21KB)

BashTool의 시스템 프롬프트는 Claude에게 Bash 명령어 사용 방법을 가르칩니다:

```typescript
export function getBashToolPrompt(): string {
  return `
## Bash Tool

You have access to a bash shell. Here are key guidelines:

### When to use Bash vs other tools:
- Use GrepTool instead of grep commands
- Use GlobTool instead of find commands
- Use FileReadTool instead of cat/head/tail
- Use FileEditTool instead of sed for file modifications
- Reserve Bash for: running tests, git operations, npm commands, etc.

### Safety rules:
- Never run destructive commands without explicit user request
- Always prefer reversible operations
- Use --dry-run flags when available
- Ask before deleting files

### Long-running commands:
- Commands taking > 2 seconds run in background
- You'll be notified when they complete

### Output handling:
- Large outputs are automatically truncated
- Use head/tail to limit output when needed
  `
}
```

---

## 12. 샌드박스 (shouldUseSandbox.ts)

```typescript
// 샌드박스 모드 결정 로직
export function shouldUseSandbox(context: BashContext): boolean {
  // 환경 변수로 강제 활성화/비활성화
  if (process.env.CLAUDE_SANDBOX === 'true') return true
  if (process.env.CLAUDE_SANDBOX === 'false') return false

  // 플랫폼별 기본값
  if (process.platform === 'linux') {
    // Linux: seccomp 또는 namespaces 사용 가능
    return true
  }

  if (process.platform === 'darwin') {
    // macOS: sandbox-exec 사용 가능
    return true
  }

  return false
}
```

---

## 13. 보안 설계 원칙

BashTool의 보안은 **다층 방어(Defense in Depth)** 원칙을 따릅니다:

```
Layer 1: AST 파싱 (구문 수준 분석)
   ↓ 통과하면
Layer 2: 패턴 매칭 (알려진 위험 패턴)
   ↓ 통과하면
Layer 3: 권한 규칙 (사용자 정의 규칙)
   ↓ 통과하면
Layer 4: 사용자 확인 (실시간 승인)
   ↓ 통과하면
Layer 5: 샌드박스 실행 (런타임 격리)
   ↓
실제 실행
```

### 13.1 실패 안전(Fail-Safe) 원칙

```typescript
// 검증 실패 시 기본값은 거부
async function validateBashCommand(command: string): Promise<ValidationResult> {
  try {
    return await performValidation(command)
  } catch (error) {
    // 검증 중 오류 발생 → 안전하게 거부
    return {
      allowed: false,
      reason: `검증 실패: ${error.message}`,
    }
  }
}
```

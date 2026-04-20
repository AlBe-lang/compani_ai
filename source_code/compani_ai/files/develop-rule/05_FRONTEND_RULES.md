# 프론트엔드 규칙 (FRONTEND RULES)

> 대상 파트: **CEO 대시보드 (Flutter Web) + Frontend SLM이 생성하는 코드 기준**
> 레이어 위치: `ui/ceo_dashboard/` (Phase 8)
> 공통 규칙(`00_COMMON_RULES.md`)을 반드시 먼저 읽으세요.

---

## 1. 역할 이중 정의

이 파트는 두 가지 관점이 있습니다.

```
관점 A: CEO 대시보드 개발 규칙
  → 시스템 운영 상황을 실시간으로 모니터링하는 Flutter Web UI
  → Phase 8에서 구현, 현재는 설계 기준 문서

관점 B: Frontend SLM이 생성하는 결과물 품질 기준
  → Frontend Agent가 외부 프로젝트의 UI 코드를 생성할 때 따르는 기준
  → 현재 MVP 단계부터 적용
```

---

## 2. CEO 대시보드 규칙 (관점 A)

### 2.1 기술 스택

| 항목 | 결정 |
|------|------|
| 프레임워크 | Flutter Web 3.x |
| 상태 관리 | Riverpod |
| 실시간 통신 | WebSocket (FastAPI 백엔드) |
| 차트 | fl_chart |
| 아이콘 | Material Icons |
| 배포 | 로컬 웹 서버 (Phase 8 로컬 우선) |

### 2.2 디렉토리 구조

```
ui/ceo_dashboard/
├── lib/
│   ├── core/
│   │   ├── constants.dart        # 상수 (색상, 크기 등)
│   │   ├── router.dart           # 라우팅
│   │   └── theme.dart            # 테마
│   ├── data/
│   │   ├── models/               # API 응답 모델 (freezed)
│   │   └── repositories/        # 데이터 소스 추상화
│   ├── presentation/
│   │   ├── pages/                # 화면 단위
│   │   └── widgets/              # 재사용 위젯
│   └── providers/                # Riverpod 프로바이더
└── test/
    ├── widget/
    └── unit/
```

### 2.3 실시간 연결 규칙

```dart
// ✅ WebSocket 연결 — 자동 재연결 포함
class AgentStatusNotifier extends AsyncNotifier<AgentStatus> {
  late WebSocketChannel _channel;

  @override
  Future<AgentStatus> build() async {
    _connect();
    ref.onDispose(() => _channel.sink.close());
    return AgentStatus.initial();
  }

  void _connect() {
    _channel = WebSocketChannel.connect(Uri.parse(AppConstants.wsUrl));
    _channel.stream.listen(
      _onData,
      onError: _onError,
      onDone: () async {
        await Future.delayed(const Duration(seconds: 3));
        _connect(); // 자동 재연결
      },
    );
  }
}
```

### 2.4 화면 구성 (필수 페이지)

```
/ (홈)         : 현재 실행 중인 프로젝트 요약
/agents        : 에이전트별 상태 (상태, DNA 수치)
/projects      : 프로젝트 목록 및 완성도
/logs          : 실시간 로그 스트림
/metrics       : 성공률, 평균 시간, LLM 토큰 수
```

---

## 3. Frontend SLM 생성 코드 기준 (관점 B)

### 3.1 생성 가능한 프레임워크

```
React (JavaScript/TypeScript)
Flutter (Dart)

선택 기준: Task의 tech_stack.frontend 값을 따름.
미지정 시: React (TypeScript) 기본.
```

### 3.2 React 코드 생성 기준

```tsx
// ✅ 필수 적용 사항
- TypeScript 사용 (JS 금지)
- 함수형 컴포넌트 + Hooks
- Props 타입 명시 (interface PropTypes)
- 파일 1개 = 컴포넌트 1개
- CSS-in-JS (styled-components) 또는 Tailwind CSS
- 에러 바운더리 적용 (최상위 컴포넌트)
- 로딩/에러 상태 처리 필수

// ❌ 금지
- 클래스형 컴포넌트
- any 타입
- inline style 남용
- 직접적인 DOM 조작 (useRef 최소화)
```

**생성 파일 구조 예시 (Todo 앱)**:
```
frontend/
├── src/
│   ├── components/
│   │   ├── TodoList.tsx
│   │   ├── TodoItem.tsx
│   │   └── AddTodoForm.tsx
│   ├── hooks/
│   │   └── useTodos.ts
│   ├── types/
│   │   └── todo.ts
│   ├── api/
│   │   └── todoApi.ts        ← Backend API 연동
│   └── App.tsx
├── package.json
└── tsconfig.json
```

### 3.3 Flutter 코드 생성 기준

```dart
// ✅ 필수 적용 사항
- StatelessWidget 우선, 상태 필요 시 StatefulWidget 또는 Riverpod
- 파일 1개 = 위젯 1개 (단, 밀접한 소형 위젯은 같은 파일 허용)
- const 생성자 최대한 활용
- 플랫폼별 분기 최소화

// ❌ 금지
- BuildContext를 async 함수 외부에서 사용
- StatefulWidget에서 setState 남용
- 위젯 트리에 비즈니스 로직 삽입
```

### 3.4 API 연동 코드 기준

```typescript
// ✅ Backend API 연동 — 에러 처리 필수
const fetchTodos = async (): Promise<Todo[]> => {
  try {
    const response = await fetch('/api/todos');
    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }
    return response.json();
  } catch (error) {
    console.error('fetchTodos failed:', error);
    throw error;
  }
};

// ❌ 금지 — 에러 처리 없는 API 호출
const fetchTodos = async () => {
  const res = await fetch('/api/todos');
  return res.json();
};
```

### 3.5 생성 결과물 필수 포함 항목

Frontend SLM이 반환하는 TaskResult에는 반드시 포함:

```json
{
  "approach": "React TypeScript + Hooks + Tailwind CSS",
  "code": { "파일명": "코드 내용" },
  "files": [{ "name": "...", "path": "frontend/src/...", "type": "tsx" }],
  "dependencies": ["react", "react-dom", "typescript", "tailwindcss"],
  "setup_commands": ["npm install", "npm run dev"],
  "api_endpoints_used": ["GET /api/todos", "POST /api/todos"]
}
```

`api_endpoints_used` 필드는 Backend와의 연동 검증에 사용됩니다.

---

## 4. 공통 UI 품질 기준

### 4.1 반응형 (Responsive)

생성된 UI는 최소 **768px 이상** 화면에서 깨지지 않아야 합니다.
모바일 대응은 별도 요구사항이 없는 한 선택 사항.

### 4.2 접근성 (Accessibility) 기본 적용

```tsx
// ✅ 기본 접근성
<button
  aria-label="할 일 추가"
  onClick={handleAdd}
>
  추가
</button>

// ❌ 접근성 미적용
<div onClick={handleAdd}>추가</div>
```

### 4.3 로딩·에러 상태 필수 처리

```tsx
// 모든 비동기 데이터 표시 컴포넌트에 적용
if (isLoading) return <Spinner />;
if (error) return <ErrorMessage message={error.message} />;
return <DataDisplay data={data} />;
```

---

## 5. 금지 사항 (프론트엔드 전용)

| 번호 | 금지 사항 |
|------|---------|
| FE-01 | JavaScript(비 TS) React 코드 생성 |
| FE-02 | 에러 처리 없는 API 호출 |
| FE-03 | 로딩·에러 상태 없는 비동기 컴포넌트 |
| FE-04 | 하드코딩된 API URL (환경변수 또는 config 사용) |
| FE-05 | 클래스형 React 컴포넌트 생성 |
| FE-06 | CEO 대시보드에서 WebSocket 자동 재연결 미구현 |
| FE-07 | 파일 1개에 복수 주요 컴포넌트 혼합 (소형 보조 위젯 제외) |

/**
 * CompaniAI Live Demo — single-page SPA.
 *
 * 사용자가 아이디어를 입력하면 백엔드(/api/run)로 파이프라인을 시작하고,
 * SSE 스트림(/api/run/stream)으로 stderr 구조화 로그를 받아 실시간으로
 * (1) 시스템 메트릭 (2) 파이프라인 단계 timeline (3) 에이전트 다이어그램
 * (4) 에이전트 메시지 로그 (5) 결과/에러 — 5영역을 갱신한다.
 *
 * OLaLA DemoPage.tsx 의 NDJSON 스트리밍 패턴을 차용하되 멀티에이전트
 * 시각화에 맞게 이벤트 분류 로직을 확장. 백엔드는 메인 dashboard_api 의
 * /api/run + /api/cancel + /api/run/stream 엔드포인트(v1.1 demo entry).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import "./DemoPage.css";

// ──────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────

type StageStatus = "pending" | "running" | "done" | "failed" | "waiting";

interface Stage {
  id: string;
  label: string;
  status: StageStatus;
  startTs?: number;
  endTs?: number;
  meta?: string;
  errorCode?: string;
}

interface AgentNode {
  id: "cto" | "backend" | "frontend" | "mlops";
  label: string;
  role: string;
  status: StageStatus;
  taskId?: string;
  errorCode?: string;
}

interface AgentMessage {
  ts: string;
  kind: "qa" | "meeting" | "review";
  text: string;
}

interface LogEvent {
  timestamp: string;
  level: string;
  event: string;
  component?: string;
  task_id?: string;
  agent_id?: string;
  role?: string;
  model?: string;
  error_code?: string;
  detail?: string;
  to?: string;
  from_agent?: string;
  to_agent?: string;
  question?: string;
  answer?: string;
  raw: string; // original line
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [k: string]: any;
}

interface MetricsSnapshot {
  total_tasks: number;
  success_count: number;
  fail_count: number;
  avg_duration_sec: number;
  memory_peak_gb: number;
  available?: boolean;
}

interface EnvSnapshot {
  total_memory_gb?: number;
  available_memory_gb?: number;
  cpu_count?: number;
  current_embedding_preset?: string;
  can_use_e5_large?: boolean;
}

// ──────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────

const RECOMMENDED = [
  "간단한 Todo REST API 만들어줘",
  "블로그 플랫폼을 만들어줘 (글, 댓글, 사용자)",
  "방명록 시스템 만들어줘",
  "회사 소개 정적 홈페이지 만들어줘",
];

const INITIAL_AGENTS: AgentNode[] = [
  { id: "cto", label: "CTO", role: "전략 수립", status: "pending" },
  { id: "backend", label: "Backend", role: "FastAPI", status: "pending" },
  { id: "frontend", label: "Frontend", role: "React/Flutter", status: "pending" },
  { id: "mlops", label: "MLOps", role: "Docker/CI", status: "pending" },
];

const INITIAL_STAGES: Stage[] = [
  { id: "strategy", label: "CTO 전략 수립", status: "pending" },
  { id: "decompose", label: "CTO 작업 분해", status: "pending" },
  { id: "agents", label: "에이전트 병렬 실행", status: "pending" },
  { id: "gate", label: "Stage Gate 평가", status: "pending" },
  { id: "files", label: "파일 저장", status: "pending" },
];

// ──────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────

function getInitialToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem("compani_token", fromUrl);
    return fromUrl;
  }
  return localStorage.getItem("compani_token") || "";
}

function fmtBytes(n?: number): string {
  if (n === undefined || n === null) return "--";
  if (n < 1) return `${(n * 1024).toFixed(0)} MB`;
  return `${n.toFixed(2)} GB`;
}

function fmtTime(ts?: string): string {
  if (!ts) return "--:--:--";
  return ts.slice(11, 19);
}

async function apiPost<T>(path: string, body: unknown, token: string): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `${path} failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = `${msg} — ${j.detail}`;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

async function apiGet<T>(path: string, token: string): Promise<T> {
  const res = await fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

// ──────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────

function DemoPage() {
  const [token, setToken] = useState<string>(getInitialToken());
  const [tokenInput, setTokenInput] = useState<string>("");
  const [healthy, setHealthy] = useState<boolean>(false);
  const [request, setRequest] = useState<string>("");
  const [planFileName, setPlanFileName] = useState<string>("");
  const [planContent, setPlanContent] = useState<string>("");
  const [running, setRunning] = useState<boolean>(false);
  const [runId, setRunId] = useState<string>("");
  const [exitCode, setExitCode] = useState<number | null>(null);
  const [stages, setStages] = useState<Stage[]>(INITIAL_STAGES);
  const [agents, setAgents] = useState<AgentNode[]>(INITIAL_AGENTS);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [showDevMode, setShowDevMode] = useState<boolean>(false);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [envInfo, setEnvInfo] = useState<EnvSnapshot | null>(null);
  const [errorBanner, setErrorBanner] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);

  // ── Health + metrics polling
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    async function loop() {
      try {
        await apiGet<{ status: string }>("/healthz", token);
        if (!cancelled) setHealthy(true);
      } catch {
        if (!cancelled) setHealthy(false);
      }
      try {
        const m = await apiGet<MetricsSnapshot>("/api/metrics", token);
        if (!cancelled) setMetrics(m);
      } catch {
        /* noop */
      }
      try {
        const e = await apiGet<EnvSnapshot>("/api/environment", token);
        if (!cancelled) setEnvInfo(e);
      } catch {
        /* noop */
      }
    }
    loop();
    const t = setInterval(loop, 3000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [token]);

  const canSubmit = useMemo(
    () => !running && healthy && request.trim().length > 0 && token.length > 0,
    [running, healthy, request, token],
  );

  // ── reset before a new run
  function resetRunState() {
    setStages(INITIAL_STAGES.map((s) => ({ ...s })));
    setAgents(INITIAL_AGENTS.map((a) => ({ ...a })));
    setMessages([]);
    setEvents([]);
    setExitCode(null);
    setErrorBanner("");
    setRunId("");
  }

  // ── plan file handling (text only)
  async function handlePlanFile(f: File | null) {
    if (!f) {
      setPlanFileName("");
      setPlanContent("");
      return;
    }
    if (!/\.(txt|md|markdown)$/i.test(f.name)) {
      setErrorBanner("기획안은 .txt 또는 .md 파일만 지원합니다 (PDF/이미지는 v2.0).");
      return;
    }
    const txt = await f.text();
    setPlanFileName(f.name);
    setPlanContent(txt);
  }

  // ── submit
  async function submit() {
    if (!canSubmit) return;
    resetRunState();
    setRunning(true);
    const composedRequest = planContent
      ? `${request.trim()}\n\n--- 첨부 기획안 (${planFileName}) ---\n${planContent}`
      : request.trim();
    try {
      const startResp = await apiPost<{ run_id: string; pid: number }>(
        "/api/run",
        { request: composedRequest },
        token,
      );
      setRunId(startResp.run_id);
      // open SSE
      abortRef.current = new AbortController();
      await streamEvents(token, abortRef.current.signal);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setErrorBanner(msg);
      setRunning(false);
    }
  }

  async function cancel() {
    try {
      await apiPost("/api/cancel", {}, token);
    } catch {
      /* ignore */
    }
    abortRef.current?.abort();
    setRunning(false);
  }

  // ── SSE stream
  async function streamEvents(tk: string, signal: AbortSignal) {
    const res = await fetch(`/api/run/stream?token=${encodeURIComponent(tk)}`, { signal });
    if (!res.ok || !res.body) {
      throw new Error(`stream open failed: ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const lines = frame.split("\n");
        let eventName = "data";
        const dataLines: string[] = [];
        for (const line of lines) {
          if (line.startsWith("event: ")) eventName = line.slice(7).trim();
          else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
        }
        const dataStr = dataLines.join("\n");
        if (!dataStr) continue;
        let parsed: Record<string, unknown> | null = null;
        try {
          parsed = JSON.parse(dataStr);
        } catch {
          continue;
        }
        if (!parsed) continue;
        if (eventName === "run.done") {
          setExitCode(typeof parsed.exit_code === "number" ? parsed.exit_code : -1);
          setRunning(false);
          markRemainingStages();
          return;
        }
        if (eventName === "data") {
          const ev: LogEvent = { ...(parsed as LogEvent), raw: dataStr };
          handleLogEvent(ev);
        }
      }
    }
  }

  function markRemainingStages() {
    setStages((prev) =>
      prev.map((s) =>
        s.status === "running" || s.status === "pending"
          ? { ...s, status: s.status === "running" ? "failed" : "pending" }
          : s,
      ),
    );
    setAgents((prev) =>
      prev.map((a) => (a.status === "running" || a.status === "waiting" ? { ...a, status: "failed" } : a)),
    );
  }

  function handleLogEvent(ev: LogEvent) {
    setEvents((prev) => [...prev.slice(-499), ev]);

    const name = ev.event || "";

    // Pipeline stages
    if (name === "orchestrator.strategy.start") {
      patchStage("strategy", { status: "running", startTs: Date.now() });
    } else if (name === "cto.strategy.done" || name === "orchestrator.strategy.done") {
      patchStage("strategy", { status: "done", endTs: Date.now(), meta: `project=${ev.project_name ?? "?"}` });
      patchStage("decompose", { status: "running", startTs: Date.now() });
      patchAgent("cto", { status: "done" });
    } else if (name === "cto.decompose.done" || name === "orchestrator.decompose.done") {
      patchStage("decompose", {
        status: "done",
        endTs: Date.now(),
        meta: `task_count=${ev.task_count ?? "?"}`,
      });
      patchStage("agents", { status: "running", startTs: Date.now() });
    } else if (name === "slm.task.start") {
      const role = (ev.role || ev.agent_id || "") as string;
      patchAgent(role as AgentNode["id"], { status: "running", taskId: ev.task_id });
    } else if (name === "slm.task.done") {
      const role = (ev.role || ev.agent_id || "") as string;
      patchAgent(role as AgentNode["id"], { status: "done" });
    } else if (name === "slm.task.failed") {
      const role = (ev.role || ev.agent_id || "") as string;
      patchAgent(role as AgentNode["id"], { status: "failed", errorCode: ev.error_code });
    } else if (name === "slm.deps.waiting") {
      const role = (ev.role || ev.agent_id || "") as string;
      patchAgent(role as AgentNode["id"], { status: "waiting" });
    } else if (name === "orchestrator.gate") {
      patchStage("gate", {
        status: ev.verdict === "abort" ? "failed" : "done",
        endTs: Date.now(),
        meta: `verdict=${ev.verdict ?? "?"}`,
      });
    } else if (name === "orchestrator.done") {
      patchStage("agents", { status: "done", endTs: Date.now() });
      patchStage("files", { status: "done", endTs: Date.now(), meta: `files=${ev.files ?? 0}` });
    }

    // Agent messages — Q&A / meeting / review
    if (name === "queue.qa.sent" || name === "queue.qa.received") {
      const text = `${ev.from_agent ?? "?"} → ${ev.to_agent ?? "?"}: ${ev.question ?? ev.detail ?? ""}`;
      pushMessage("qa", text, ev.timestamp);
    } else if (name.startsWith("meeting.")) {
      pushMessage("meeting", `${name} ${ev.detail ?? ""}`, ev.timestamp);
    } else if (name.startsWith("peer_review.")) {
      pushMessage("review", `${name} ${ev.detail ?? ""}`, ev.timestamp);
    }
  }

  function patchStage(id: string, patch: Partial<Stage>) {
    setStages((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }

  function patchAgent(id: AgentNode["id"], patch: Partial<AgentNode>) {
    setAgents((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  }

  function pushMessage(kind: AgentMessage["kind"], text: string, ts?: string) {
    setMessages((prev) => [...prev.slice(-99), { ts: fmtTime(ts), kind, text }]);
  }

  // ── UI
  if (!token) {
    return (
      <div className="demo-page">
        <h1>
          <span className="accent">Compani</span>AI Demo
        </h1>
        <div className="card">
          <h2>인증 토큰 입력</h2>
          <p>
            대시보드 백엔드(<code>python main.py --dashboard</code>) 시작 시 출력되는 URL의{" "}
            <code>?token=</code> 값을 붙여넣으세요. URL 자체에서 자동 추출도 가능합니다 (
            <code>http://localhost:5173/?token=...</code>).
          </p>
          <input
            type="text"
            className="token-input"
            placeholder="dashboard token (hex 32자)"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
          />
          <button
            className="btn primary"
            style={{ marginLeft: 8 }}
            onClick={() => {
              localStorage.setItem("compani_token", tokenInput.trim());
              setToken(tokenInput.trim());
            }}
          >
            저장
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="demo-page">
      <header className="header">
        <h1>
          <span className="accent">Compani</span>AI Live Demo
          {runId && <span style={{ fontSize: 13, color: "var(--text-dim)", marginLeft: 12 }}>run={runId}</span>}
        </h1>
        <span className={`status-pill ${healthy ? "online" : "offline"}`}>
          {healthy ? "● Dashboard online" : "● offline"}
        </span>
      </header>

      {errorBanner && (
        <div className="banner" role="alert">
          ⚠ {errorBanner}
        </div>
      )}

      {/* (1) 시스템 메트릭 */}
      <div className="metric-row">
        <div className="metric-card">
          <div className="label">RAM (사용 가능)</div>
          <div className="value">{fmtBytes(envInfo?.available_memory_gb)}</div>
          <div className="sub">/ 전체 {fmtBytes(envInfo?.total_memory_gb)}</div>
        </div>
        <div className="metric-card">
          <div className="label">총 Task</div>
          <div className="value">{metrics?.total_tasks ?? 0}</div>
          <div className="sub">
            ✅ {metrics?.success_count ?? 0} / ❌ {metrics?.fail_count ?? 0}
          </div>
        </div>
        <div className="metric-card">
          <div className="label">평균 Task 시간</div>
          <div className="value">
            {metrics?.avg_duration_sec ? `${metrics.avg_duration_sec.toFixed(1)}s` : "--"}
          </div>
          <div className="sub">memory peak {fmtBytes(metrics?.memory_peak_gb)}</div>
        </div>
        <div className="metric-card">
          <div className="label">임베딩</div>
          <div className="value" style={{ fontSize: 14 }}>
            {envInfo?.current_embedding_preset?.split("/").pop() ?? "--"}
          </div>
          <div className="sub">E5 가용: {envInfo?.can_use_e5_large ? "예" : "아니오"}</div>
        </div>
      </div>

      {/* (2) 입력 */}
      <div className="card input-area">
        <h2>
          <span className="icon">💡</span>아이디어
        </h2>
        <textarea
          placeholder="만들고 싶은 프로젝트를 자유롭게 설명해주세요. 예: '글을 작성하고 댓글을 달 수 있는 블로그 플랫폼'"
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          disabled={running}
        />
        <div className="file-input">
          📎 기획안 (선택, .txt/.md):
          <input
            type="file"
            accept=".txt,.md,.markdown"
            onChange={(e) => handlePlanFile(e.target.files?.[0] ?? null)}
            disabled={running}
          />
          {planFileName && <span style={{ marginLeft: 8 }}>📄 {planFileName}</span>}
        </div>
        <div className="recommend-row">
          {RECOMMENDED.map((r) => (
            <button
              key={r}
              className="recommend-pill"
              onClick={() => setRequest(r)}
              disabled={running}
              type="button"
            >
              {r}
            </button>
          ))}
        </div>
        <div className="action-row">
          <button className="btn primary" onClick={submit} disabled={!canSubmit}>
            🚀 제출하기
          </button>
          <button className="btn danger" onClick={cancel} disabled={!running}>
            ⛔ 중단
          </button>
          <button
            className="btn ghost"
            onClick={() => setShowDevMode((v) => !v)}
            type="button"
            style={{ marginLeft: "auto" }}
          >
            {showDevMode ? "사용자 모드" : "개발자 모드"}
          </button>
        </div>
      </div>

      {/* (3) 파이프라인 단계 */}
      <div className="split">
        <div className="card">
          <h2>
            <span className="icon">🔄</span>파이프라인 진행
          </h2>
          <div className="timeline">
            {stages.map((s) => (
              <div key={s.id} className={`timeline-item ${s.status}`}>
                <span className="icon">
                  {s.status === "done" && "✅"}
                  {s.status === "running" && "🔄"}
                  {s.status === "failed" && "❌"}
                  {s.status === "waiting" && "⏳"}
                  {s.status === "pending" && "○"}
                </span>
                <div className="body">
                  <div className="stage-name">{s.label}</div>
                  <div className="stage-meta">
                    {s.meta || (s.status === "pending" ? "대기" : s.status)}
                    {s.startTs && s.endTs && ` · ${((s.endTs - s.startTs) / 1000).toFixed(1)}s`}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* (4) 에이전트 다이어그램 */}
        <div className="card">
          <h2>
            <span className="icon">🎭</span>에이전트 상태
          </h2>
          <div className="diagram">
            <div className="row">
              <div className={`agent-node ${agents[0].status}`}>
                <div className="indicator">{statusEmoji(agents[0].status)}</div>
                <div>{agents[0].label}</div>
                <div className="role">{agents[0].role}</div>
              </div>
            </div>
            <div style={{ color: "var(--text-dim)", fontSize: 18 }}>↓</div>
            <div className="row">
              {agents.slice(1).map((a) => (
                <div key={a.id} className={`agent-node ${a.status}`} title={a.errorCode || ""}>
                  <div className="indicator">{statusEmoji(a.status)}</div>
                  <div>{a.label}</div>
                  <div className="role">{a.role}</div>
                  {a.errorCode && (
                    <div style={{ fontSize: 10, color: "var(--err)", marginTop: 2 }}>{a.errorCode}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* (5) 메시지 + 결과/에러 + 개발자 모드 */}
      <div className="card">
        <h2>
          <span className="icon">💬</span>에이전트 통신 (Q&A · 회의 · 피어리뷰)
        </h2>
        <div className="message-log">
          {messages.length === 0 ? (
            <div style={{ color: "var(--text-dim)", padding: 8 }}>
              아직 에이전트 간 메시지가 없습니다. 협업이 시작되면 여기에 표시됩니다.
            </div>
          ) : (
            messages.slice(-50).map((m, i) => (
              <div key={i} className="row">
                <span className="ts">{m.ts}</span>
                <span className={`kind ${m.kind}`}>{m.kind.toUpperCase()}</span>
                <span>{m.text}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {exitCode !== null && (
        <div className="card">
          <h2>
            <span className="icon">{exitCode === 0 ? "✅" : "⚠️"}</span>
            결과 (exit_code = {exitCode})
          </h2>
          {agents.filter((a) => a.status === "failed").length > 0 && (
            <div className="error-box">
              <div className="code">
                실패한 에이전트:{" "}
                {agents
                  .filter((a) => a.status === "failed")
                  .map((a) => `${a.label}(${a.errorCode ?? "?"})`)
                  .join(", ")}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
                상세 원인은 아래 개발자 모드의 이벤트 로그를 참고하세요.
              </div>
            </div>
          )}
        </div>
      )}

      {showDevMode && (
        <div className="card">
          <h2>
            <span className="icon">🔧</span>개발자 모드 — 원본 이벤트 로그
          </h2>
          <div className="event-stream">
            {events
              .slice(-200)
              .reverse()
              .map((ev, i) => (
                <div key={i} className={`row ${ev.level || "info"}`}>
                  <span className="ts">{fmtTime(ev.timestamp)}</span>
                  <span className={`lvl ${ev.level || "info"}`}>[{(ev.level || "info").toUpperCase()}]</span>
                  <span className="name">{ev.event}</span>
                  <span className="extra">
                    {ev.task_id && `task=${ev.task_id}`} {ev.agent_id && `agent=${ev.agent_id}`}{" "}
                    {ev.error_code && `err=${ev.error_code}`}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function statusEmoji(s: StageStatus): string {
  switch (s) {
    case "done":
      return "✅";
    case "running":
      return "🔄";
    case "failed":
      return "❌";
    case "waiting":
      return "⏳";
    default:
      return "○";
  }
}

export default DemoPage;

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
  // 클릭 시 관련 상세 컨텍스트로 점프할 ID
  refId?: string;
  refKind?: "qa" | "meeting" | "review";
  // 정렬용 원본 timestamp
  rawTs?: number;
}

interface QASession {
  qaId: string;
  fromAgent: string;
  toAgent: string;
  taskId?: string;
  taskContext?: string;
  reason?: string;
  question?: string;
  answer?: string;
  reasoning?: string;
  askedAt?: number;
  answeredAt?: number;
}

interface MeetingMessage {
  speaker: string;
  text: string;
  ts: number;
}

interface Meeting {
  meetingId: string;
  title?: string;
  reason?: string;
  attendees?: string[];
  trigger?: string;
  messages: MeetingMessage[];
  decision?: string;
  outcome?: string;
  durationSec?: number;
  openedAt?: number;
  closedAt?: number;
}

interface ReviewComment {
  file?: string;
  line?: number | null;
  severity?: string;
  comment: string;
  ts: number;
}

interface Review {
  reviewId: string;
  taskId?: string;
  author?: string;
  reviewer?: string;
  reason?: string;
  filesUnderReview?: number;
  comments: ReviewComment[];
  verdict?: string;
  highestSeverity?: string;
  decision?: string;
  openedAt?: number;
  closedAt?: number;
}

interface TaskRow {
  taskId: string;
  role: string;
  agentId: string;
  status: StageStatus;
  startTs?: number;
  endTs?: number;
  filesCount?: number;
  errorCode?: string;
  errorDetail?: string;
  retries?: number;
  description?: string;
  // 마지막 raw 이벤트 (모달용)
  lastRawEvent?: string;
}

interface ErrorModalState {
  title: string;
  errorCode?: string;
  detail?: string;
  // 관련 raw 이벤트들
  rawEvents: LogEvent[];
}

interface OutputTreeNode {
  name: string;
  path: string;
  type: "dir" | "file";
  size?: number;
  children?: OutputTreeNode[];
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
  memory_used_pct?: number;
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

const STAGE_ICONS: Record<string, string> = {
  strategy: "🧠",
  decompose: "✂️",
  agents: "🤝",
  gate: "🚦",
  files: "📦",
};

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

// 이벤트 이름 → 어느 stage 카드의 sub-status 인지 추론
function inferStageFromEvent(name: string): string | null {
  if (name.startsWith("orchestrator.strategy") || name.startsWith("cto.strategy") || name === "cto.thinking") {
    return "strategy";
  }
  if (name.startsWith("cto.decompose") || name.startsWith("orchestrator.decompose")) {
    return "decompose";
  }
  if (name.startsWith("slm.task") || name.startsWith("queue.qa") || name.startsWith("meeting.") || name.startsWith("peer_review.")) {
    return "agents";
  }
  if (name.startsWith("stage_gate") || name === "orchestrator.gate") {
    return "gate";
  }
  if (name.startsWith("file_storage")) {
    return "files";
  }
  return null;
}

// 메시지 카드 ticker 용 짧은 텍스트
function shortText(s: unknown, max = 60): string {
  if (typeof s !== "string" || !s) return "";
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

// 회의 발언자 이모지 (시각적 구분용)
function speakerEmoji(speaker: string): string {
  const map: Record<string, string> = {
    cto: "🧠",
    backend: "⚙️",
    frontend: "🎨",
    mlops: "🐳",
  };
  return map[speaker.toLowerCase()] || "👤";
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
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [qaSessions, setQaSessions] = useState<Record<string, QASession>>({});
  const [meetings, setMeetings] = useState<Record<string, Meeting>>({});
  const [reviews, setReviews] = useState<Record<string, Review>>({});
  const [stageSubStatus, setStageSubStatus] = useState<Record<string, string>>({});
  const [errorModal, setErrorModal] = useState<ErrorModalState | null>(null);
  // 통신 상세 모달 (QA / 회의 / 리뷰 중 하나)
  const [commModal, setCommModal] = useState<
    | { kind: "qa"; session: QASession }
    | { kind: "meeting"; meeting: Meeting }
    | { kind: "review"; review: Review }
    | null
  >(null);
  // 산출물 정보 (파이프라인 완료 시 백엔드에서 받음)
  const [outputInfo, setOutputInfo] = useState<{
    slug: string;
    fileCount: number;
    autoDownloaded: boolean;
  } | null>(null);
  const [outputTree, setOutputTree] = useState<OutputTreeNode | null>(null);
  const [selectedOutputFile, setSelectedOutputFile] = useState<string>("");
  const [outputFileContent, setOutputFileContent] = useState<string>("");
  const [showDevMode, setShowDevMode] = useState<boolean>(false);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [envInfo, setEnvInfo] = useState<EnvSnapshot | null>(null);
  const [errorBanner, setErrorBanner] = useState<string>("");
  // 시연 안전 토글: 기본 ON (mock). 실제 LLM 모드는 confirm 후에만 사용.
  const [mockMode, setMockMode] = useState<boolean>(true);
  const [pendingRealConfirm, setPendingRealConfirm] = useState<boolean>(false);
  // 5초마다 1Hz tick으로 stage/task의 진행중 경과시간이 갱신되도록 강제 리렌더
  const [, setTick] = useState<number>(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
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
    setTasks([]);
    setQaSessions({});
    setMeetings({});
    setReviews({});
    setStageSubStatus({});
    setErrorModal(null);
    setCommModal(null);
    setOutputInfo(null);
    setOutputTree(null);
    setSelectedOutputFile("");
    setOutputFileContent("");
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
    // 안전장치: 실제 LLM 모드면 confirm 모달을 먼저 띄움. 사용자가
    // 명시적으로 "그래도 실행" 누르면 ``runRealAfterConfirm()`` 으로 진입.
    if (!mockMode) {
      setPendingRealConfirm(true);
      return;
    }
    await runPipeline(true);
  }

  async function runRealAfterConfirm() {
    setPendingRealConfirm(false);
    await runPipeline(false);
  }

  async function runPipeline(mock: boolean) {
    resetRunState();
    setRunning(true);
    const composedRequest = planContent
      ? `${request.trim()}\n\n--- 첨부 기획안 (${planFileName}) ---\n${planContent}`
      : request.trim();
    try {
      const startResp = await apiPost<{ run_id: string; pid: number; mock: boolean }>(
        "/api/run",
        { request: composedRequest, mock },
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

    // ─ sub_status: stage 진행 중 라이브 메시지 ─
    if (typeof ev.sub_status === "string" && ev.sub_status) {
      const stageId = inferStageFromEvent(name);
      if (stageId) {
        setStageSubStatus((prev) => ({ ...prev, [stageId]: ev.sub_status as string }));
      }
    }

    // ─ Pipeline stages ─
    if (name === "orchestrator.strategy.start" || name === "cto.thinking") {
      patchStage("strategy", {
        status: "running",
        startTs: stageStartOnce("strategy"),
      });
      patchAgent("cto", { status: "running" });
    } else if (name === "cto.strategy.done" || name === "orchestrator.strategy.done") {
      patchStage("strategy", {
        status: "done",
        endTs: Date.now(),
        meta: `project=${ev.project_name ?? "?"}`,
      });
      patchStage("decompose", { status: "running", startTs: Date.now() });
      patchAgent("cto", { status: "done" });
    } else if (name === "cto.decompose.start") {
      patchStage("decompose", {
        status: "running",
        startTs: stageStartOnce("decompose"),
      });
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
      upsertTask(ev.task_id, {
        role,
        agentId: (ev.agent_id as string) || role,
        status: "running",
        startTs: Date.now(),
        description: (ev.description as string) || (ev.task_name as string) || undefined,
        lastRawEvent: ev.raw,
      });
    } else if (name === "slm.task.done") {
      const role = (ev.role || ev.agent_id || "") as string;
      patchAgent(role as AgentNode["id"], { status: "done" });
      upsertTask(ev.task_id, {
        status: "done",
        endTs: Date.now(),
        filesCount: typeof ev.files === "number" ? ev.files : (ev.file_count as number | undefined),
        retries: ev.retries as number | undefined,
        lastRawEvent: ev.raw,
      });
    } else if (name === "slm.task.failed") {
      const role = (ev.role || ev.agent_id || "") as string;
      patchAgent(role as AgentNode["id"], { status: "failed", errorCode: ev.error_code });
      upsertTask(ev.task_id, {
        status: "failed",
        endTs: Date.now(),
        errorCode: ev.error_code,
        errorDetail: ev.detail,
        retries: ev.retries as number | undefined,
        lastRawEvent: ev.raw,
      });
    } else if (name === "slm.deps.waiting") {
      const role = (ev.role || ev.agent_id || "") as string;
      patchAgent(role as AgentNode["id"], { status: "waiting" });
      upsertTask(ev.task_id, {
        role,
        agentId: (ev.agent_id as string) || role,
        status: "waiting",
        lastRawEvent: ev.raw,
      });
    } else if (name === "slm.task.retry") {
      upsertTask(ev.task_id, { retries: ev.retries as number | undefined, lastRawEvent: ev.raw });
    } else if (name === "stage_gate.evaluate.start") {
      patchStage("gate", { status: "running", startTs: stageStartOnce("gate") });
    } else if (name === "orchestrator.gate") {
      patchStage("gate", {
        status: ev.verdict === "abort" ? "failed" : "done",
        endTs: Date.now(),
        meta: `verdict=${ev.verdict ?? "?"}`,
      });
    } else if (name === "file_storage.write.start") {
      patchStage("files", { status: "running", startTs: stageStartOnce("files") });
    } else if (name === "file_storage.write.done") {
      patchStage("files", {
        status: "done",
        endTs: Date.now(),
        meta: `files=${ev.files ?? 0}`,
      });
    } else if (name === "orchestrator.done") {
      patchStage("agents", { status: "done", endTs: Date.now() });
      patchStage("files", { status: "done", endTs: Date.now(), meta: `files=${ev.files ?? 0}` });
      // 산출물 자동 다운로드 트리거
      const slug = (ev.output_slug as string | undefined) || (ev.project_slug as string | undefined);
      const fileCount = (ev.files as number | undefined) ?? 0;
      if (slug) {
        setOutputInfo({ slug, fileCount, autoDownloaded: false });
        triggerOutputDownload(slug, fileCount).catch((e) => {
          // 다운로드 실패해도 시연은 계속 — 에러 배너만 띄움
          setErrorBanner(`산출물 자동 다운로드 실패: ${e instanceof Error ? e.message : String(e)}`);
        });
      }
    }

    // ─ QA 세션 (질문/응답을 한 세션으로 묶음) ─
    if (name === "queue.qa.sent") {
      const qaId = (ev.qa_id as string) || `qa-${Date.now()}`;
      setQaSessions((prev) => ({
        ...prev,
        [qaId]: {
          ...(prev[qaId] || { qaId, fromAgent: "", toAgent: "", messages: [] }),
          qaId,
          fromAgent: ev.from_agent ?? "?",
          toAgent: ev.to_agent ?? "?",
          taskId: ev.task_id,
          taskContext: ev.task_context as string | undefined,
          reason: ev.reason as string | undefined,
          question: ev.question,
          askedAt: Date.now(),
        },
      }));
      const tickerText = `${ev.from_agent ?? "?"} → ${ev.to_agent ?? "?"}: ${shortText(ev.question)}`;
      pushMessage("qa", tickerText, ev.timestamp, qaId, "qa");
    } else if (name === "queue.qa.received") {
      const qaId = (ev.qa_id as string) || "";
      if (qaId) {
        setQaSessions((prev) => ({
          ...prev,
          [qaId]: {
            ...(prev[qaId] || { qaId, fromAgent: "", toAgent: "", messages: [] }),
            qaId,
            answer: ev.answer as string | undefined,
            reasoning: ev.reasoning as string | undefined,
            answeredAt: Date.now(),
          },
        }));
      }
    }

    // ─ 회의 (Emergency Meeting) ─
    if (name === "meeting.opened") {
      const mid = (ev.meeting_id as string) || `m-${Date.now()}`;
      setMeetings((prev) => ({
        ...prev,
        [mid]: {
          meetingId: mid,
          title: ev.title as string | undefined,
          reason: ev.reason as string | undefined,
          attendees: (ev.attendees as string[] | undefined) || [],
          trigger: ev.trigger as string | undefined,
          messages: [],
          openedAt: Date.now(),
        },
      }));
      pushMessage(
        "meeting",
        `🔥 회의 열림 — ${ev.title ?? "Emergency"}`,
        ev.timestamp,
        mid,
        "meeting",
      );
    } else if (name === "meeting.message") {
      const mid = ev.meeting_id as string;
      if (mid) {
        setMeetings((prev) => {
          const cur = prev[mid];
          if (!cur) return prev;
          return {
            ...prev,
            [mid]: {
              ...cur,
              messages: [
                ...cur.messages,
                {
                  speaker: ev.speaker ?? "?",
                  text: ev.text ?? "",
                  ts: Date.now(),
                },
              ],
            },
          };
        });
      }
    } else if (name === "meeting.closed") {
      const mid = ev.meeting_id as string;
      if (mid) {
        setMeetings((prev) => {
          const cur = prev[mid];
          if (!cur) return prev;
          return {
            ...prev,
            [mid]: {
              ...cur,
              decision: ev.decision as string | undefined,
              outcome: ev.outcome as string | undefined,
              durationSec: ev.duration_sec as number | undefined,
              closedAt: Date.now(),
            },
          };
        });
      }
      pushMessage(
        "meeting",
        `✅ 회의 종료 — 결정: ${shortText(ev.decision)}`,
        ev.timestamp,
        mid,
        "meeting",
      );
    }

    // ─ 피어 리뷰 ─
    if (name === "peer_review.opened") {
      const rid = (ev.review_id as string) || `pr-${Date.now()}`;
      setReviews((prev) => ({
        ...prev,
        [rid]: {
          reviewId: rid,
          taskId: ev.task_id,
          author: ev.author as string | undefined,
          reviewer: ev.reviewer as string | undefined,
          reason: ev.reason as string | undefined,
          filesUnderReview: ev.files_under_review as number | undefined,
          comments: [],
          openedAt: Date.now(),
        },
      }));
      pushMessage(
        "review",
        `🔎 피어 리뷰 시작 — ${ev.task_id} (reviewer: ${ev.reviewer})`,
        ev.timestamp,
        rid,
        "review",
      );
    } else if (name === "peer_review.comment") {
      const rid = ev.review_id as string;
      if (rid) {
        setReviews((prev) => {
          const cur = prev[rid];
          if (!cur) return prev;
          return {
            ...prev,
            [rid]: {
              ...cur,
              comments: [
                ...cur.comments,
                {
                  file: ev.file as string | undefined,
                  line: ev.line as number | null | undefined,
                  severity: ev.severity as string | undefined,
                  comment: ev.comment ?? "",
                  ts: Date.now(),
                },
              ],
            },
          };
        });
      }
    } else if (name === "peer_review.closed" || name === "peer_review.passed") {
      const rid = (ev.review_id as string) || (ev.task_id as string) || "";
      if (rid) {
        setReviews((prev) => {
          const cur = prev[rid];
          if (!cur) {
            // peer_review.passed 가 단독으로 올 경우 (open 없이) 새로 만들어 둠
            return {
              ...prev,
              [rid]: {
                reviewId: rid,
                taskId: ev.task_id,
                reviewer: ev.reviewer as string | undefined,
                author: ev.author as string | undefined,
                comments: [],
                verdict: ev.verdict as string | undefined,
                highestSeverity: ev.severity as string | undefined,
                decision: ev.decision as string | undefined,
                closedAt: Date.now(),
              },
            };
          }
          return {
            ...prev,
            [rid]: {
              ...cur,
              verdict: (ev.verdict as string | undefined) ?? "PASSED",
              highestSeverity: (ev.highest_severity as string | undefined) ?? cur.highestSeverity,
              decision: ev.decision as string | undefined,
              closedAt: Date.now(),
            },
          };
        });
      }
      pushMessage(
        "review",
        `${ev.verdict === "FAILED" ? "❌" : "✅"} 리뷰 종료 — verdict: ${ev.verdict ?? "PASSED"}`,
        ev.timestamp,
        rid,
        "review",
      );
    }
  }

  // 한 stage 가 처음 running 으로 들어가는 시점에만 startTs 잡기 위한 helper
  function stageStartOnce(stageId: string): number {
    const existing = stages.find((s) => s.id === stageId);
    return existing?.startTs ?? Date.now();
  }

  // 산출물 ZIP 자동 다운로드
  async function triggerOutputDownload(slug: string, fileCount: number) {
    const url = `/api/output/download?slug=${encodeURIComponent(slug)}&token=${encodeURIComponent(token)}`;
    // <a download> 트릭으로 브라우저 다운로드 트리거
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slug}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setOutputInfo({ slug, fileCount, autoDownloaded: true });
  }

  async function loadOutputTree(slug: string) {
    try {
      const tree = await apiGet<OutputTreeNode>(
        `/api/output/tree?slug=${encodeURIComponent(slug)}`,
        token,
      );
      setOutputTree(tree);
    } catch (e) {
      setErrorBanner(`산출물 트리 로드 실패: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function loadOutputFile(slug: string, path: string) {
    try {
      const res = await fetch(
        `/api/output/file?slug=${encodeURIComponent(slug)}&path=${encodeURIComponent(path)}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!res.ok) throw new Error(`status ${res.status}`);
      const text = await res.text();
      setSelectedOutputFile(path);
      setOutputFileContent(text);
    } catch (e) {
      setErrorBanner(`파일 로드 실패: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  function upsertTask(taskId: string | undefined, patch: Partial<TaskRow>) {
    if (!taskId) return;
    setTasks((prev) => {
      const idx = prev.findIndex((t) => t.taskId === taskId);
      if (idx === -1) {
        return [
          ...prev,
          {
            taskId,
            role: patch.role ?? "",
            agentId: patch.agentId ?? "",
            status: patch.status ?? "running",
            ...patch,
          } as TaskRow,
        ];
      }
      const next = [...prev];
      next[idx] = { ...next[idx], ...patch };
      return next;
    });
  }

  function openStageError(stage: Stage) {
    const related = events.filter(
      (e) =>
        e.event?.startsWith("orchestrator.") ||
        (stage.id === "strategy" && e.event?.startsWith("cto.strategy")) ||
        (stage.id === "decompose" && e.event?.startsWith("cto.decompose")) ||
        (stage.id === "agents" && e.event?.startsWith("slm.")) ||
        (stage.id === "gate" && e.event?.startsWith("stage_gate")) ||
        (stage.id === "files" && e.event?.includes("file")),
    );
    setErrorModal({
      title: `단계: ${stage.label}`,
      errorCode: stage.errorCode,
      detail:
        stage.status === "failed"
          ? "이 단계가 실패했습니다. 아래 관련 이벤트를 확인하세요."
          : `상태: ${stage.status}${stage.meta ? ` (${stage.meta})` : ""}`,
      rawEvents: related.slice(-30),
    });
  }

  function openAgentError(agent: AgentNode) {
    const related = events.filter(
      (e) => e.role === agent.id || e.agent_id === agent.id || (agent.taskId && e.task_id === agent.taskId),
    );
    setErrorModal({
      title: `에이전트: ${agent.label} (${agent.id})`,
      errorCode: agent.errorCode,
      detail:
        agent.status === "failed"
          ? `${agent.role} 작업이 실패했습니다.`
          : `상태: ${agent.status}${agent.taskId ? ` · task=${agent.taskId}` : ""}`,
      rawEvents: related.slice(-30),
    });
  }

  function openTaskDetail(task: TaskRow) {
    const related = events.filter((e) => e.task_id === task.taskId);
    setErrorModal({
      title: `Task: ${task.taskId} (${task.role})`,
      errorCode: task.errorCode,
      detail:
        task.errorDetail ||
        (task.status === "failed"
          ? "이 task가 실패했습니다."
          : `상태: ${task.status}${task.description ? ` · ${task.description}` : ""}`),
      rawEvents: related.slice(-30),
    });
  }

  function patchStage(id: string, patch: Partial<Stage>) {
    setStages((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }

  function patchAgent(id: AgentNode["id"], patch: Partial<AgentNode>) {
    setAgents((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  }

  function pushMessage(
    kind: AgentMessage["kind"],
    text: string,
    ts?: string,
    refId?: string,
    refKind?: AgentMessage["refKind"],
  ) {
    setMessages((prev) => [
      ...prev.slice(-99),
      { ts: fmtTime(ts), kind, text, refId, refKind, rawTs: Date.now() },
    ]);
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
        <div className="header-controls">
          <label
            className={`mode-toggle ${mockMode ? "mock" : "real"}`}
            title={
              mockMode
                ? "시연 안전 모드. Ollama 미사용, ~38초 소요."
                : "실제 LLM 호출. 5-10분 소요, 16GB Mac 환경에서 hang 위험 있음."
            }
          >
            <input
              type="checkbox"
              checked={mockMode}
              onChange={(e) => setMockMode(e.target.checked)}
              disabled={running}
            />
            <span className="track">
              <span className="thumb" />
            </span>
            <span className="mode-label">
              {mockMode ? (
                <>
                  <span className="mode-badge mock">MOCK</span>
                  <span className="mode-text">시연 모드 (38초)</span>
                </>
              ) : (
                <>
                  <span className="mode-badge real">REAL</span>
                  <span className="mode-text">실제 LLM (5-10분)</span>
                </>
              )}
            </span>
          </label>
          <span className={`status-pill ${healthy ? "online" : "offline"}`}>
            {healthy ? "● Dashboard online" : "● offline"}
          </span>
        </div>
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
          <div className="sub">
            / 전체 {fmtBytes(envInfo?.total_memory_gb)}
            {typeof envInfo?.memory_used_pct === "number" && ` · ${envInfo.memory_used_pct.toFixed(0)}% 사용`}
          </div>
        </div>
        <div className="metric-card">
          <div className="label">진행 중 Task</div>
          <div className="value">{tasks.filter((t) => t.status === "running").length}</div>
          <div className="sub">
            완료 {tasks.filter((t) => t.status === "done").length} / 실패{" "}
            {tasks.filter((t) => t.status === "failed").length} / 전체 {tasks.length}
          </div>
        </div>
        <div className="metric-card">
          <div className="label">평균 Task 시간</div>
          <div className="value">
            {(() => {
              const completed = tasks.filter((t) => t.startTs && t.endTs);
              if (completed.length === 0) {
                return metrics?.avg_duration_sec ? `${metrics.avg_duration_sec.toFixed(1)}s` : "--";
              }
              const avg =
                completed.reduce((acc, t) => acc + ((t.endTs ?? 0) - (t.startTs ?? 0)) / 1000, 0) /
                completed.length;
              return `${avg.toFixed(1)}s`;
            })()}
          </div>
          <div className="sub">backend peak {fmtBytes(metrics?.memory_peak_gb)}</div>
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

      {/* (3) 파이프라인 단계 — 큰 카드 흐름도 */}
      <div className="split">
        <div className="card">
          <h2>
            <span className="icon">🔄</span>파이프라인 진행
            <span className="hint">단계 클릭 시 관련 이벤트</span>
          </h2>
          <div className="pipeline-flow">
            {stages.map((s, idx) => {
              const elapsed = s.startTs
                ? (((s.endTs ?? Date.now()) - s.startTs) / 1000).toFixed(1)
                : null;
              const stageIcon = STAGE_ICONS[s.id] || "•";
              const sub = stageSubStatus[s.id];
              return (
                <div key={s.id} className="pipeline-step-wrap">
                  <div
                    className={`pipeline-step ${s.status} clickable`}
                    onClick={() => openStageError(s)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="step-head">
                      <div className="step-num">{idx + 1}</div>
                      <div className="step-icon">{stageIcon}</div>
                      <div className="step-status-emoji">
                        {s.status === "done" && "✅"}
                        {s.status === "running" && <span className="spinner" />}
                        {s.status === "failed" && "❌"}
                        {s.status === "waiting" && "⏳"}
                        {s.status === "pending" && "○"}
                      </div>
                    </div>
                    <div className="step-name">{s.label}</div>
                    <div className="step-sub">
                      {s.status === "running" && sub
                        ? sub
                        : s.meta || (s.status === "pending" ? "대기 중" : s.status)}
                    </div>
                    {elapsed && (
                      <div className="step-elapsed">
                        ⏱ {elapsed}s{!s.endTs && "…"}
                      </div>
                    )}
                  </div>
                  {idx < stages.length - 1 && (
                    <div className={`step-arrow ${s.status === "done" ? "done" : ""}`}>↓</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* (4) 에이전트 다이어그램 */}
        <div className="card">
          <h2>
            <span className="icon">🎭</span>에이전트 상태
            <span className="hint">클릭 시 상세</span>
          </h2>
          <div className="diagram">
            <div className="row">
              <div
                className={`agent-node ${agents[0].status} clickable`}
                onClick={() => openAgentError(agents[0])}
                role="button"
                tabIndex={0}
              >
                <div className="indicator">{statusEmoji(agents[0].status)}</div>
                <div>{agents[0].label}</div>
                <div className="role">{agents[0].role}</div>
              </div>
            </div>
            <div style={{ color: "var(--text-dim)", fontSize: 18 }}>↓</div>
            <div className="row">
              {agents.slice(1).map((a) => (
                <div
                  key={a.id}
                  className={`agent-node ${a.status} clickable`}
                  title={a.errorCode || ""}
                  onClick={() => openAgentError(a)}
                  role="button"
                  tabIndex={0}
                >
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

      {/* (3-b) Task 진행 상세 표 */}
      <div className="card">
        <h2>
          <span className="icon">📋</span>Task 진행 상세
          <span className="hint">행 클릭 시 상세</span>
        </h2>
        {tasks.length === 0 ? (
          <div style={{ color: "var(--text-dim)", padding: 8 }}>
            아직 Task가 시작되지 않았습니다. 파이프라인이 작업을 분해하면 여기 실시간으로 표시됩니다.
          </div>
        ) : (
          <div className="task-table-wrap">
            <table className="task-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Task ID</th>
                  <th>역할</th>
                  <th>상태</th>
                  <th>경과</th>
                  <th>재시도</th>
                  <th>산출물</th>
                  <th>설명</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t, i) => {
                  const elapsed = t.startTs ? ((t.endTs ?? Date.now()) - t.startTs) / 1000 : null;
                  return (
                    <tr
                      key={t.taskId}
                      className={`task-row ${t.status} clickable`}
                      onClick={() => openTaskDetail(t)}
                    >
                      <td>{i + 1}</td>
                      <td>
                        <code>{t.taskId.length > 12 ? `${t.taskId.slice(0, 8)}…` : t.taskId}</code>
                      </td>
                      <td>{t.role || t.agentId || "-"}</td>
                      <td>
                        <span className={`status-badge ${t.status}`}>
                          {statusEmoji(t.status)} {t.status}
                        </span>
                      </td>
                      <td>{elapsed !== null ? `${elapsed.toFixed(1)}s${!t.endTs ? "…" : ""}` : "-"}</td>
                      <td>{t.retries ?? 0}</td>
                      <td>
                        {t.status === "failed" ? (
                          <span style={{ color: "var(--err)" }}>{t.errorCode ?? "ERR"}</span>
                        ) : t.filesCount !== undefined ? (
                          `${t.filesCount} files`
                        ) : (
                          "-"
                        )}
                      </td>
                      <td title={t.description || ""}>
                        {t.description
                          ? t.description.length > 40
                            ? `${t.description.slice(0, 40)}…`
                            : t.description
                          : "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* (5) 메시지 + 결과/에러 + 개발자 모드 */}
      <div className="card">
        <h2>
          <span className="icon">💬</span>에이전트 통신 (Q&A · 회의 · 피어리뷰)
          <span className="hint">메시지 클릭 시 전체 대화 보기</span>
        </h2>
        <div className="comm-legend">
          <span className="legend-item">
            <span className="kind qa">QA</span> 에이전트 간 질의응답
          </span>
          <span className="legend-item">
            <span className="kind meeting">MEETING</span> 충돌/blocking 발생 시 합의 회의
          </span>
          <span className="legend-item">
            <span className="kind review">REVIEW</span> 코드 산출물 피어 리뷰
          </span>
        </div>
        <div className="message-log">
          {messages.length === 0 ? (
            <div style={{ color: "var(--text-dim)", padding: 8 }}>
              아직 에이전트 간 메시지가 없습니다. 협업이 시작되면 여기에 표시됩니다.
            </div>
          ) : (
            messages.slice(-50).map((m, i) => {
              const clickable =
                (m.refKind === "qa" && m.refId && qaSessions[m.refId]) ||
                (m.refKind === "meeting" && m.refId && meetings[m.refId]) ||
                (m.refKind === "review" && m.refId && reviews[m.refId]);
              const onClick = clickable
                ? () => {
                    if (m.refKind === "qa" && m.refId) {
                      setCommModal({ kind: "qa", session: qaSessions[m.refId] });
                    } else if (m.refKind === "meeting" && m.refId) {
                      setCommModal({ kind: "meeting", meeting: meetings[m.refId] });
                    } else if (m.refKind === "review" && m.refId) {
                      setCommModal({ kind: "review", review: reviews[m.refId] });
                    }
                  }
                : undefined;
              return (
                <div
                  key={i}
                  className={`row ${clickable ? "clickable" : ""}`}
                  onClick={onClick}
                  role={clickable ? "button" : undefined}
                  tabIndex={clickable ? 0 : undefined}
                >
                  <span className="ts">{m.ts}</span>
                  <span className={`kind ${m.kind}`}>{m.kind.toUpperCase()}</span>
                  <span style={{ flex: 1 }}>{m.text}</span>
                  {clickable && <span className="comm-chevron">→</span>}
                </div>
              );
            })
          )}
        </div>
      </div>

      {exitCode !== null && (
        <div className="card result-card">
          <h2>
            <span className="icon">{exitCode === 0 ? "✅" : "⚠️"}</span>
            결과 (exit_code = {exitCode})
          </h2>
          {outputInfo && (
            <div className="output-summary">
              <div className="output-row">
                <span className="output-label">📦 프로젝트:</span>
                <code>{outputInfo.slug}</code>
              </div>
              <div className="output-row">
                <span className="output-label">📄 생성 파일:</span>
                <strong>{outputInfo.fileCount} files</strong>
              </div>
              <div className="output-row">
                <span className="output-label">⬇️ 자동 다운로드:</span>
                {outputInfo.autoDownloaded ? (
                  <span className="output-ok">완료 — 다운로드 폴더 확인하세요</span>
                ) : (
                  <span className="output-pending">진행 중…</span>
                )}
              </div>
              <div className="output-actions">
                <a
                  className="btn primary"
                  href={`/api/output/download?slug=${encodeURIComponent(outputInfo.slug)}&token=${encodeURIComponent(token)}`}
                  download={`${outputInfo.slug}.zip`}
                >
                  ⬇️ 다시 다운로드 (ZIP)
                </a>
                <button
                  className="btn ghost"
                  onClick={() => loadOutputTree(outputInfo.slug)}
                >
                  📂 산출물 미리보기
                </button>
              </div>
              {outputTree && (
                <OutputTreePanel
                  tree={outputTree}
                  selected={selectedOutputFile}
                  onSelect={(p) => loadOutputFile(outputInfo.slug, p)}
                  fileContent={outputFileContent}
                />
              )}
            </div>
          )}
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

      {/* (6a) 실제 LLM 모드 confirm 모달 */}
      {pendingRealConfirm && (
        <div className="modal-backdrop" onClick={() => setPendingRealConfirm(false)}>
          <div className="modal real-confirm" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>⚠️ 실제 LLM 호출 모드</h3>
              <button className="btn ghost" onClick={() => setPendingRealConfirm(false)}>
                ✕
              </button>
            </div>
            <div className="modal-detail">
              <p>현재 설정: <span className="mode-badge real">REAL</span> (실제 LLM)</p>
              <ul>
                <li>예상 5–10분 소요</li>
                <li>16GB Mac 환경에서 swap 발생 시 hang 위험 (R1-Critical 미해결)</li>
                <li>Ollama + 3개 모델 (qwen3:8b, gemma4:e4b, llama3.2:3b) 자동 로드</li>
                <li><strong>발표/시연 중이면 Mock 모드를 권장합니다.</strong></li>
              </ul>
            </div>
            <div className="action-row" style={{ justifyContent: "flex-end" }}>
              <button className="btn ghost" onClick={() => setPendingRealConfirm(false)}>
                취소 (Mock 모드 유지)
              </button>
              <button className="btn danger" onClick={runRealAfterConfirm}>
                그래도 실행
              </button>
            </div>
          </div>
        </div>
      )}

      {/* (6c) 통신 상세 모달 (QA / 회의 / 리뷰) */}
      {commModal && (
        <div className="modal-backdrop" onClick={() => setCommModal(null)}>
          <div className="modal comm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {commModal.kind === "qa" && "💬 에이전트 Q&A"}
                {commModal.kind === "meeting" && "🔥 Emergency Meeting"}
                {commModal.kind === "review" && "🔎 피어 리뷰"}
              </h3>
              <button className="btn ghost" onClick={() => setCommModal(null)}>
                ✕
              </button>
            </div>
            {commModal.kind === "qa" && (() => {
              const s = commModal.session;
              return (
                <div className="comm-body">
                  <div className="comm-meta">
                    <div><strong>참여자:</strong> <code>{s.fromAgent}</code> → <code>{s.toAgent}</code></div>
                    {s.taskId && <div><strong>발생 task:</strong> <code>{s.taskId}</code></div>}
                    {s.taskContext && <div><strong>당시 상황:</strong> {s.taskContext}</div>}
                    {s.reason && <div><strong>질문 이유:</strong> {s.reason}</div>}
                  </div>
                  <div className="qa-bubble qa-question">
                    <div className="bubble-head">❓ 질문 — <code>{s.fromAgent}</code></div>
                    <div className="bubble-body">{s.question || "(질문 내용 없음)"}</div>
                  </div>
                  {s.answer ? (
                    <>
                      <div className="qa-bubble qa-answer">
                        <div className="bubble-head">💡 답변 — <code>{s.toAgent}</code></div>
                        <div className="bubble-body">{s.answer}</div>
                      </div>
                      {s.reasoning && (
                        <div className="qa-reasoning">
                          <strong>답변 근거:</strong> {s.reasoning}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="qa-pending">⏳ 답변 대기 중…</div>
                  )}
                </div>
              );
            })()}
            {commModal.kind === "meeting" && (() => {
              const m = commModal.meeting;
              return (
                <div className="comm-body">
                  <div className="comm-meta">
                    <div><strong>제목:</strong> {m.title || "(제목 없음)"}</div>
                    <div><strong>왜 열렸나:</strong> {m.reason || "-"}</div>
                    <div>
                      <strong>참석:</strong>{" "}
                      {(m.attendees || []).map((a) => (
                        <code key={a} className="attendee">{a}</code>
                      ))}
                    </div>
                    {m.trigger && <div><strong>트리거:</strong> <code>{m.trigger}</code></div>}
                  </div>
                  <div className="meeting-thread">
                    {m.messages.length === 0 ? (
                      <div className="comm-empty">아직 발언 없음…</div>
                    ) : (
                      m.messages.map((msg, i) => (
                        <div key={i} className={`meeting-msg speaker-${msg.speaker}`}>
                          <div className="msg-speaker">{speakerEmoji(msg.speaker)} <code>{msg.speaker}</code></div>
                          <div className="msg-text">{msg.text}</div>
                        </div>
                      ))
                    )}
                  </div>
                  {m.decision && (
                    <div className="meeting-decision">
                      <div className="decision-label">📌 결정</div>
                      <div className="decision-text">{m.decision}</div>
                      {typeof m.durationSec === "number" && (
                        <div className="decision-meta">소요: {m.durationSec.toFixed(1)}s · 결과: {m.outcome || "resolved"}</div>
                      )}
                    </div>
                  )}
                </div>
              );
            })()}
            {commModal.kind === "review" && (() => {
              const r = commModal.review;
              return (
                <div className="comm-body">
                  <div className="comm-meta">
                    <div><strong>대상 task:</strong> <code>{r.taskId || "?"}</code></div>
                    <div>
                      <strong>역할:</strong> 작성자 <code>{r.author || "?"}</code> · 리뷰어 <code>{r.reviewer || "?"}</code>
                    </div>
                    {r.reason && <div><strong>리뷰 이유:</strong> {r.reason}</div>}
                    {typeof r.filesUnderReview === "number" && (
                      <div><strong>리뷰 대상:</strong> {r.filesUnderReview} files</div>
                    )}
                  </div>
                  <div className="review-comments">
                    <h4>코멘트 ({r.comments.length})</h4>
                    {r.comments.length === 0 ? (
                      <div className="comm-empty">아직 코멘트 없음…</div>
                    ) : (
                      r.comments.map((c, i) => (
                        <div key={i} className={`review-comment severity-${(c.severity || "info").toLowerCase()}`}>
                          <div className="comment-head">
                            <span className={`severity-pill ${(c.severity || "INFO").toLowerCase()}`}>
                              {c.severity || "INFO"}
                            </span>
                            {c.file && (
                              <code>
                                {c.file}
                                {typeof c.line === "number" && c.line ? `:${c.line}` : ""}
                              </code>
                            )}
                          </div>
                          <div className="comment-body">{c.comment}</div>
                        </div>
                      ))
                    )}
                  </div>
                  {r.verdict && (
                    <div className={`review-verdict verdict-${r.verdict.toLowerCase()}`}>
                      <div className="verdict-label">
                        {r.verdict === "PASSED" ? "✅" : "❌"} VERDICT — {r.verdict}
                      </div>
                      {r.decision && <div className="verdict-text">{r.decision}</div>}
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* (6b) 에러/상세 모달 */}
      {errorModal && (
        <div className="modal-backdrop" onClick={() => setErrorModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{errorModal.title}</h3>
              <button className="btn ghost" onClick={() => setErrorModal(null)}>
                ✕
              </button>
            </div>
            {errorModal.errorCode && (
              <div className="modal-error-code">
                ❌ <code>{errorModal.errorCode}</code>
              </div>
            )}
            {errorModal.detail && <div className="modal-detail">{errorModal.detail}</div>}
            <h4>관련 이벤트 ({errorModal.rawEvents.length})</h4>
            {errorModal.rawEvents.length === 0 ? (
              <div style={{ color: "var(--text-dim)" }}>관련 이벤트가 아직 없습니다.</div>
            ) : (
              <div className="modal-events">
                {errorModal.rawEvents.map((ev, i) => (
                  <div key={i} className={`row ${ev.level || "info"}`}>
                    <span className="ts">{fmtTime(ev.timestamp)}</span>
                    <span className={`lvl ${ev.level || "info"}`}>
                      [{(ev.level || "info").toUpperCase()}]
                    </span>
                    <span className="name">{ev.event}</span>
                    {ev.error_code && <span className="err">err={ev.error_code}</span>}
                    {ev.detail && <span className="detail">{ev.detail}</span>}
                  </div>
                ))}
              </div>
            )}
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

// ──────────────────────────────────────────────────────────────────
// 산출물 트리 패널
// ──────────────────────────────────────────────────────────────────

interface OutputTreePanelProps {
  tree: OutputTreeNode;
  selected: string;
  onSelect: (path: string) => void;
  fileContent: string;
}

function OutputTreePanel({ tree, selected, onSelect, fileContent }: OutputTreePanelProps) {
  return (
    <div className="output-tree-panel">
      <div className="output-tree">
        <TreeNode node={tree} selected={selected} onSelect={onSelect} depth={0} />
      </div>
      <div className="output-preview">
        {selected ? (
          <>
            <div className="preview-header">
              <code>{selected}</code>
              <span className="preview-size">{fileContent.length.toLocaleString()} bytes</span>
            </div>
            <pre className="preview-body">{fileContent}</pre>
          </>
        ) : (
          <div className="preview-empty">
            왼쪽에서 파일을 클릭하면 여기 미리보기가 표시됩니다.
          </div>
        )}
      </div>
    </div>
  );
}

interface TreeNodeProps {
  node: OutputTreeNode;
  selected: string;
  onSelect: (path: string) => void;
  depth: number;
}

function TreeNode({ node, selected, onSelect, depth }: TreeNodeProps) {
  if (node.type === "file") {
    return (
      <div
        className={`tree-file ${selected === node.path ? "selected" : ""}`}
        style={{ paddingLeft: 12 + depth * 14 }}
        onClick={() => onSelect(node.path)}
      >
        📄 {node.name}
        {node.size !== undefined && <span className="tree-size">{node.size}b</span>}
      </div>
    );
  }
  return (
    <div className="tree-dir-wrap">
      <div className="tree-dir" style={{ paddingLeft: 12 + depth * 14 }}>
        📁 {node.name || "/"}
      </div>
      {(node.children || []).map((c) => (
        <TreeNode key={c.path} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />
      ))}
    </div>
  );
}

export default DemoPage;

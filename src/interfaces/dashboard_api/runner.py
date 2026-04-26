"""Pipeline run orchestration via subprocess — v1.1 demo entry (dev prototype).

Exposes a :class:`RunManager` that launches ``main.py "<request>"`` as a child
process, captures stderr line-by-line into an in-memory ring, and serves an
SSE stream of those lines to dashboard clients.

Why subprocess (not in-process)?
    The current dashboard runs in its own process (R-11B). Hosting the
    pipeline in-process would require resolving R-11B (single-process
    SharedWorkspace + EventBus sharing) which is a v2.0 architecture task.
    For v1.1 demo we accept the subprocess boundary — the demo only needs
    to surface stderr structured logs, which already carry every event the
    UI cares about (cto.*, slm.*, ws.item.status, ollama.*, etc.).

Concurrency posture (v1.1 dev): one run at a time. ``start()`` rejects with
``RuntimeError`` if a previous run is still alive. v2.0 will lift this when
multi-project orchestration lands.

The structured-log line format on stderr is JSON-per-line (structlog), so
SSE clients receive ready-to-parse payloads without re-encoding.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from observability.logger import get_logger

log = get_logger(__name__)

_DEFAULT_BUFFER_LIMIT = 5000  # 충분히 큼 — 한 회 실행은 보통 수백~수천 이벤트.
_CANCEL_GRACE_SEC = 5.0  # SIGTERM 후 SIGKILL 까지 대기.
_STREAM_POLL_SEC = 0.2  # 스트림 루프가 새 라인 확인하는 주기.


@dataclass
class RunState:
    """In-memory state of a single pipeline run.

    ``events`` accumulates raw stderr lines (each is JSON from structlog).
    ``finished`` is set when the child process exits — readers wait on it
    to know when to send the SSE 'done' frame.
    """

    run_id: str
    request: str
    started_at: float = 0.0
    pid: int | None = None
    proc: asyncio.subprocess.Process | None = None
    events: list[str] = field(default_factory=list)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    exit_code: int | None = None


class RunManager:
    """Single-flight subprocess lifecycle manager.

    The manager owns at most one live run; concurrent ``start`` calls raise
    until the previous run has finished. Cancellation sends SIGTERM and falls
    back to SIGKILL after :data:`_CANCEL_GRACE_SEC` seconds.
    """

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        buffer_limit: int = _DEFAULT_BUFFER_LIMIT,
    ) -> None:
        self._project_root = project_root or Path.cwd()
        self._buffer_limit = buffer_limit
        self._current: RunState | None = None
        self._start_lock = asyncio.Lock()

    @property
    def current(self) -> RunState | None:
        return self._current

    def is_running(self) -> bool:
        state = self._current
        return state is not None and not state.finished.is_set()

    async def start(self, request: str) -> RunState:
        """Launch ``main.py "<request>"`` as a child and begin event capture."""
        if not request.strip():
            raise ValueError("request must not be empty")
        async with self._start_lock:
            if self.is_running():
                raise RuntimeError("another run is in progress")
            run_id = uuid.uuid4().hex[:8]
            state = RunState(
                run_id=run_id,
                request=request,
                started_at=asyncio.get_event_loop().time(),
            )

            python = self._project_root / ".venv" / "bin" / "python"
            if not python.exists():
                python = Path(sys.executable)

            proc = await asyncio.create_subprocess_exec(
                str(python),
                "main.py",
                request,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            state.proc = proc
            state.pid = proc.pid
            self._current = state

        log.info(
            "demo.run.start",
            run_id=run_id,
            pid=proc.pid,
            request_chars=len(request),
        )
        asyncio.create_task(self._consume_stderr(state))
        asyncio.create_task(self._drain_stdout(state))
        return state

    async def cancel(self) -> bool:
        """Send SIGTERM (then SIGKILL after grace period). Returns True on success."""
        state = self._current
        if state is None or state.finished.is_set() or state.proc is None:
            return False
        try:
            state.proc.terminate()
        except ProcessLookupError:
            return False
        try:
            await asyncio.wait_for(state.finished.wait(), timeout=_CANCEL_GRACE_SEC)
        except asyncio.TimeoutError:
            try:
                state.proc.kill()
            except ProcessLookupError:
                pass
            await state.finished.wait()
        log.info("demo.run.cancelled", run_id=state.run_id, exit_code=state.exit_code)
        return True

    async def stream(self) -> AsyncIterator[str]:
        """SSE event stream. Replays buffered events then tails new ones.

        Each yielded item is a complete SSE frame (``data: ...\\n\\n`` or
        ``event: <name>\\ndata: ...\\n\\n``). The stream closes after the
        ``run.done`` frame when the child process exits.
        """
        state = self._current
        if state is None:
            yield _frame("run.empty", {"detail": "no active run"})
            return

        yield _frame(
            "run.start",
            {"run_id": state.run_id, "pid": state.pid, "request": state.request},
        )
        last_idx = 0
        while True:
            while last_idx < len(state.events):
                line = state.events[last_idx]
                # Each stderr line is already a JSON event from structlog.
                # SSE 'data:' values must not contain raw newlines other than
                # the trailing blank line — strip just in case.
                yield f"data: {line}\n\n"
                last_idx += 1
            if state.finished.is_set():
                yield _frame("run.done", {"exit_code": state.exit_code})
                return
            await asyncio.sleep(_STREAM_POLL_SEC)

    async def _consume_stderr(self, state: RunState) -> None:
        if state.proc is None or state.proc.stderr is None:
            return
        try:
            async for raw in state.proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if not line:
                    continue
                state.events.append(line)
                # Cap memory — drop oldest beyond limit.
                if len(state.events) > self._buffer_limit:
                    drop = len(state.events) - self._buffer_limit
                    del state.events[:drop]
        except Exception as exc:  # noqa: BLE001 — surface as run-level error
            log.error("demo.run.stderr_error", run_id=state.run_id, detail=str(exc))
        finally:
            try:
                if state.proc is not None:
                    await state.proc.wait()
                    state.exit_code = state.proc.returncode
            finally:
                state.finished.set()
                log.info(
                    "demo.run.done",
                    run_id=state.run_id,
                    exit_code=state.exit_code,
                    event_count=len(state.events),
                )

    async def _drain_stdout(self, state: RunState) -> None:
        """Stdout from main.py is the final summary print — drain and discard."""
        if state.proc is None or state.proc.stdout is None:
            return
        try:
            async for _ in state.proc.stdout:
                pass
        except Exception:  # noqa: BLE001 — non-critical
            pass


def _frame(event: str, payload: dict[str, Any]) -> str:
    """Format a typed SSE frame: ``event: <name>\\ndata: <json>\\n\\n``."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

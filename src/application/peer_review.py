"""PeerReviewCoordinator — Part 7 Stage 2.

Subscribes to ``task.completed`` (emitted by SharedWorkspace.attach_result
when a WorkItem reaches DONE). Runs one LLM-backed peer review per qualifying
Task, persists the result, and updates both participants' DNA.

Scope boundaries (Stage 2):
  * Decision model: APPROVE / REQUEST_CHANGES (severity MINOR|MAJOR|CRITICAL) / REJECT
  * State transitions: only REJECT → WorkItem FAILED is applied here.
    MAJOR/CRITICAL set ``pending_rework=True`` on the review record;
    actual re-execution is Stage 3 responsibility.
  * Reviewer selection: via pluggable ``ReviewerSelector`` (default
    ``FixedWithKGFallbackSelector``). DNA-weighted / load-balanced selection
    is Stage 3.
  * Trigger mode: SystemConfig.peer_review_mode = OFF | ALL | CRITICAL.
    CRITICAL = Task has dependencies OR execution duration exceeded
    critical_duration_sec threshold.

Rule 10 §1 (context preservation): the review record stores the full
TaskResult snapshot at review time so the record is self-contained.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from application.reviewer_selector import FixedWithKGFallbackSelector, ReviewerSelector
from domain.contracts import (
    PeerReviewDecision,
    PeerReviewRequest,
    PeerReviewResult,
    PeerReviewSeverity,
    WorkStatus,
)
from domain.ports import LLMProvider, StoragePort, WorkSpacePort
from observability.logger import get_logger
from observability.parsers import ParseResponseError, parse_json_response

if TYPE_CHECKING:
    from adapters.qdrant_storage import QdrantStorage
    from application.dna_manager import DNAManager
    from domain.ports import EventBusPort, KnowledgeGraphPort
    from observability.metrics import MetricsCollector

log = get_logger(__name__)

_REVIEW_KEY_PREFIX = "peer_review:"
_CTO_CALL_TIMEOUT_SEC = 30.0
_REVIEW_TEMPERATURE = 0.3
_REVIEW_MAX_TOKENS = 1024
_REVIEW_MAX_RETRIES = 3
_REVIEW_RETRY_INTERVAL_SEC = 2.0

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "peer_review" / "review.txt"


class PeerReviewMode(str, Enum):
    """Operator-selectable trigger policy (exposed via SystemConfig).

    Time-overhead guidance (VRAM is NOT the constraint; reviews reuse already-
    loaded models, only adding sequential inference passes):

      OFF       — 피어 리뷰 비활성. 리뷰 없이 Task 완료 시 즉시 종결.
      CRITICAL  — 의존성을 가지거나 실행 시간이 임계값(기본 60초)을 초과한
                   Task만 선별 리뷰. 대부분 환경에서 실용적 기본값.
      ALL       — 완료된 모든 Task에 자동 리뷰. 품질 검증 극대화.
                   전체 실행 시간 약 2배. 야간 배치 또는 고성능 데스크탑 권장.
    """

    OFF = "off"
    ALL = "all"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PeerReviewConfig:
    mode: PeerReviewMode = PeerReviewMode.OFF
    critical_duration_sec: float = 60.0
    # Model used for the reviewer LLM call. In practice this is the reviewer
    # role's configured model; the coordinator is initialized with a mapping
    # (role → model) so we avoid hard-coding here.
    call_timeout_sec: float = _CTO_CALL_TIMEOUT_SEC
    max_retries: int = _REVIEW_MAX_RETRIES
    retry_interval_sec: float = _REVIEW_RETRY_INTERVAL_SEC


class PeerReviewCoordinator:
    """EventBus handler that owns the peer review lifecycle."""

    def __init__(
        self,
        *,
        workspace: WorkSpacePort,
        storage: StoragePort,
        event_bus: "EventBusPort",
        llm: LLMProvider,
        reviewer_model_by_role: dict[str, str],
        run_id: str,
        config: PeerReviewConfig | None = None,
        selector: ReviewerSelector | None = None,
        knowledge_graph: "KnowledgeGraphPort | None" = None,
        dna_manager: "DNAManager | None" = None,
        qdrant: "QdrantStorage | None" = None,
        metrics: "MetricsCollector | None" = None,
    ) -> None:
        self._workspace = workspace
        self._storage = storage
        self._event_bus = event_bus
        self._llm = llm
        self._reviewer_model_by_role = dict(reviewer_model_by_role)
        self._run_id = run_id
        self._config = config or PeerReviewConfig()
        self._selector: ReviewerSelector = selector or FixedWithKGFallbackSelector(
            knowledge_graph=knowledge_graph
        )
        self._dna_manager = dna_manager
        self._qdrant = qdrant
        self._metrics = metrics
        self._logger = get_logger(component="peer_review", run_id=run_id)
        self._prompt_template = self._load_prompt()

        if self._config.mode is not PeerReviewMode.OFF:
            event_bus.subscribe("task.completed", self._on_task_completed)

    # ------------------------------------------------------------------
    # 퍼블릭 API
    # ------------------------------------------------------------------

    async def review_task(self, payload: dict[str, object]) -> PeerReviewResult | None:
        """Run one review. Returns None if the task doesn't qualify or reviewer
        cannot be selected. Called directly or via EventBus handler."""
        if not self._should_review(payload):
            self._logger.debug(
                "review.skipped.mode",
                mode=self._config.mode.value,
                task_id=payload.get("task_id"),
            )
            return None

        author_role = self._role_from_agent_id(str(payload.get("agent_id", "")))
        result_snapshot = self._extract_result_snapshot(payload)
        reviewer_role = await self._selector.select(
            author_role=author_role,
            context={
                "approach": result_snapshot.get("approach", ""),
                "description": result_snapshot.get("approach", ""),
            },
        )
        if reviewer_role is None:
            self._logger.warning(
                "review.no_reviewer",
                author_role=author_role,
                task_id=payload.get("task_id"),
            )
            return None

        request = PeerReviewRequest(
            review_id=f"review_{uuid.uuid4().hex[:16]}",
            work_item_id=str(payload.get("item_id", "")),
            task_id=str(payload.get("task_id", "")),
            author_agent_id=str(payload.get("agent_id", "")),
            reviewer_agent_id=reviewer_role,
            task_result_snapshot=result_snapshot,
        )
        self._logger.info(
            "review.start",
            review_id=request.review_id,
            author=request.author_agent_id,
            reviewer=reviewer_role,
        )

        result = await self._perform_review(request, reviewer_role)
        if result is None:
            # Reviewer LLM unavailable after retries — metrics fallback log.
            if self._metrics is not None:
                self._metrics.record_fallback(
                    run_id=self._run_id,
                    component="peer_review",
                    reason="reviewer_llm_unavailable",
                )
            return None

        await self._persist(request, result)
        await self._apply_state_transition(request, result)
        await self._feedback_dna(request, result)

        self._logger.info(
            "review.done",
            review_id=result.review_id,
            decision=result.decision.value,
            severity=result.severity.value,
            pending_rework=result.pending_rework,
        )
        return result

    # ------------------------------------------------------------------
    # EventBus 핸들러
    # ------------------------------------------------------------------

    def _on_task_completed(self, event_type: str, payload: dict[str, object]) -> None:
        """Mirrors StageGate._on_blocking_detected — schedule async work."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.review_task(payload))
        except RuntimeError:
            self._logger.warning("review.no_loop", task_id=payload.get("task_id"))

    # ------------------------------------------------------------------
    # 내부 로직
    # ------------------------------------------------------------------

    def _should_review(self, payload: dict[str, object]) -> bool:
        if self._config.mode is PeerReviewMode.OFF:
            return False
        if self._config.mode is PeerReviewMode.ALL:
            return True
        # CRITICAL mode — trigger if Task had dependencies OR duration ≥ threshold.
        result = self._extract_result_snapshot(payload)
        deps = result.get("dependencies", [])
        has_deps = isinstance(deps, list) and len(deps) > 0
        raw_duration = payload.get("duration_sec", 0.0)
        duration_sec = float(raw_duration) if isinstance(raw_duration, (int, float)) else 0.0
        return has_deps or duration_sec >= self._config.critical_duration_sec

    async def _perform_review(
        self, request: PeerReviewRequest, reviewer_role: str
    ) -> PeerReviewResult | None:
        model = self._reviewer_model_by_role.get(reviewer_role)
        if model is None:
            self._logger.warning("review.unknown_model", role=reviewer_role)
            return None
        prompt = self._build_prompt(request)
        for attempt in range(1, self._config.max_retries + 1):
            try:
                raw = await asyncio.wait_for(
                    self._llm.generate(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=_REVIEW_TEMPERATURE,
                        max_tokens=_REVIEW_MAX_TOKENS,
                    ),
                    timeout=self._config.call_timeout_sec,
                )
            except asyncio.TimeoutError:
                self._logger.warning("review.timeout", attempt=attempt)
                raw = None
            except Exception as exc:  # pragma: no cover — defensive
                self._logger.warning("review.llm_error", attempt=attempt, detail=str(exc))
                raw = None

            if raw is not None:
                parsed = self._parse_review_response(raw, request, reviewer_role)
                if parsed is not None:
                    return parsed

            if attempt < self._config.max_retries:
                await asyncio.sleep(self._config.retry_interval_sec)
        return None

    def _parse_review_response(
        self,
        raw: str,
        request: PeerReviewRequest,
        reviewer_role: str,
    ) -> PeerReviewResult | None:
        try:
            payload = parse_json_response(raw)
        except ParseResponseError:
            return None
        decision_str = str(payload.get("decision", "")).upper()
        severity_str = str(payload.get("severity", "MINOR")).upper() or "MINOR"
        try:
            decision = PeerReviewDecision(decision_str)
        except ValueError:
            return None
        try:
            severity = PeerReviewSeverity(severity_str)
        except ValueError:
            severity = PeerReviewSeverity.MINOR
        comments_raw = payload.get("comments", [])
        suggested_raw = payload.get("suggested_changes", [])
        comments = [str(c) for c in comments_raw] if isinstance(comments_raw, list) else []
        suggested = [str(s) for s in suggested_raw] if isinstance(suggested_raw, list) else []
        pending_rework = decision is PeerReviewDecision.REQUEST_CHANGES and severity in (
            PeerReviewSeverity.MAJOR,
            PeerReviewSeverity.CRITICAL,
        )
        return PeerReviewResult(
            review_id=request.review_id,
            work_item_id=request.work_item_id,
            task_id=request.task_id,
            author_agent_id=request.author_agent_id,
            reviewer_agent_id=reviewer_role,
            decision=decision,
            severity=severity,
            comments=comments,
            suggested_changes=suggested,
            pending_rework=pending_rework,
        )

    async def _apply_state_transition(
        self,
        request: PeerReviewRequest,
        result: PeerReviewResult,
    ) -> None:
        """Stage 2 scope: only REJECT → FAILED. MAJOR/CRITICAL rework is
        signaled via pending_rework only; actual status cycling is Stage 3."""
        if result.decision is PeerReviewDecision.REJECT:
            try:
                await self._workspace.set_status(request.work_item_id, WorkStatus.FAILED)
                self._logger.info("review.state.rejected", work_item_id=request.work_item_id)
            except Exception as exc:
                # Non-fatal: state transition may be invalid if already transitioned.
                self._logger.warning(
                    "review.state.reject_failed",
                    work_item_id=request.work_item_id,
                    detail=str(exc),
                )

    async def _persist(self, request: PeerReviewRequest, result: PeerReviewResult) -> None:
        """SQLite — required. Qdrant — best-effort for future semantic retrieval."""
        payload: dict[str, object] = {
            "review_id": result.review_id,
            "work_item_id": result.work_item_id,
            "task_id": result.task_id,
            "author_agent_id": result.author_agent_id,
            "reviewer_agent_id": result.reviewer_agent_id,
            "decision": result.decision.value,
            "severity": result.severity.value,
            "comments": result.comments,
            "suggested_changes": result.suggested_changes,
            "pending_rework": result.pending_rework,
            "reviewed_at": result.reviewed_at.isoformat(),
            "run_id": self._run_id,
            "task_result_snapshot": request.task_result_snapshot,
        }
        await self._storage.save(_REVIEW_KEY_PREFIX + result.review_id, payload)

        if self._qdrant is not None:
            approach = str(request.task_result_snapshot.get("approach", ""))
            text = (
                f"[peer_review] {result.decision.value}/{result.severity.value} "
                f"on task {result.task_id}: {approach[:200]}"
            ).strip()
            qdrant_payload: dict[str, Any] = {
                "task_id": result.review_id,
                "agent_id": "peer_review",
                "approach": text,
                "success": result.decision is PeerReviewDecision.APPROVE,
                "run_id": self._run_id,
                "files": [],
            }
            try:
                await self._qdrant.add_task_result(qdrant_payload)
            except Exception as exc:
                self._logger.warning("review.qdrant_persist_error", detail=str(exc))

    async def _feedback_dna(self, request: PeerReviewRequest, result: PeerReviewResult) -> None:
        if self._dna_manager is None:
            return
        try:
            await self._dna_manager.update_review_feedback(
                reviewer_agent_id=result.reviewer_agent_id,
                reviewer_role=self._role_from_agent_id(result.reviewer_agent_id),
                author_agent_id=result.author_agent_id,
                author_role=self._role_from_agent_id(result.author_agent_id),
                decision=result.decision,
                severity=result.severity,
            )
        except Exception as exc:
            self._logger.warning("review.dna_feedback_error", detail=str(exc))

    # ------------------------------------------------------------------
    # 프롬프트 / 헬퍼
    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        try:
            return _PROMPT_PATH.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover — deployment misconfig
            self._logger.warning("review.prompt.not_found", path=str(_PROMPT_PATH))
            return (
                "Review target — task_id={task_id}, author={author_agent_id}\n"
                "Approach: {approach}\n"
                "Files: {files_summary}\n"
                "Respond JSON: "
                '{{"decision":"APPROVE|REQUEST_CHANGES|REJECT","severity":"MINOR|MAJOR|CRITICAL","comments":[],"suggested_changes":[]}}'  # noqa: E501
            )

    def _build_prompt(self, request: PeerReviewRequest) -> str:
        snapshot = request.task_result_snapshot
        approach = str(snapshot.get("approach", "") or "(no approach provided)")
        files = snapshot.get("files", [])
        if isinstance(files, list) and files:
            files_summary = "\n".join(
                f"- {f.get('path', '?')} ({f.get('type', '?')})"
                for f in files
                if isinstance(f, dict)
            )
        else:
            files_summary = "(no files)"

        return self._prompt_template.format(
            author_agent_id=request.author_agent_id,
            task_id=request.task_id,
            approach=approach,
            files_summary=files_summary,
        )

    @staticmethod
    def _role_from_agent_id(agent_id: str) -> str:
        lowered = agent_id.lower()
        for role in ("backend", "frontend", "mlops", "cto"):
            if role in lowered:
                return role
        return "general"

    @staticmethod
    def _extract_result_snapshot(payload: dict[str, object]) -> dict[str, object]:
        raw = payload.get("result")
        if isinstance(raw, dict):
            return raw
        return {}

    @staticmethod
    def _utcnow() -> datetime:  # pragma: no cover — wrapper
        return datetime.now(timezone.utc)

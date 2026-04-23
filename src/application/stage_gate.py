"""StageGateMeeting — 규칙 기반 Gate 평가 + CTO 위임 하이브리드.

평가 절차:
  1. 수치 기준 자동 평가 (failure_rate, avg_duration)
  2. PASS → 즉시 반환 (LLM 호출 없음)
  3. FAIL → CTOAgent.review_progress() 위임 → REPLAN / ABORT 결정

이벤트 구독:
  - blocking.detected → 즉시 긴급 Gate 소집

Gate 기준값은 SystemConfig를 통해 주입 — 코드 수정 없이 프로젝트별 조정 가능.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from domain.contracts import MeetingDecision, ReviewDecision, WorkItem, WorkStatus
from domain.ports import EventBusPort, StoragePort
from observability.logger import get_logger

if TYPE_CHECKING:
    from application.cto_agent import CTOAgent
    from application.emergency_meeting import EmergencyMeeting

log = get_logger(__name__)

_GATE_RESULT_KEY_PREFIX = "gate_result:"


class GateVerdict(str, Enum):
    PASS = "PASS"
    REPLAN = "REPLAN"
    ABORT = "ABORT"


@dataclass(frozen=True)
class GateResult:
    """Gate 평가 결과."""

    verdict: GateVerdict
    reason: str
    failure_rate: float
    avg_duration: float
    total_items: int


@dataclass(frozen=True)
class GateConfig:
    """Gate 통과 기준값."""

    max_failure_rate: float = 0.3  # 실패율 30% 초과 시 FAIL
    max_avg_duration: float = 120.0  # 평균 120초 초과 시 경고 (FAIL 트리거 아님)


class StageGateMeeting:
    """규칙 기반 Gate 평가 + 실패 시 CTOAgent 위임.

    EventBus를 통해 blocking.detected 이벤트를 구독하고
    긴급 Gate를 소집한다. 일반 Gate는 run 완료 후 명시적으로
    evaluate()를 호출해 실행한다.
    """

    def __init__(
        self,
        cto: "CTOAgent",
        event_bus: EventBusPort,
        storage: StoragePort,
        run_id: str,
        config: GateConfig | None = None,
        emergency_meeting: "EmergencyMeeting | None" = None,
    ) -> None:
        self._cto = cto
        self._event_bus = event_bus
        self._storage = storage
        self._run_id = run_id
        self._config = config or GateConfig()
        self._emergency_meeting = emergency_meeting
        self._logger = get_logger(component="stage_gate", run_id=run_id)
        self._blocking_items: list[dict[str, object]] = []

        event_bus.subscribe("blocking.detected", self._on_blocking_detected)

    # ------------------------------------------------------------------
    # 퍼블릭 API
    # ------------------------------------------------------------------

    async def evaluate(self, work_items: list[WorkItem]) -> GateResult:
        """전체 WorkItem 목록을 평가해 Gate 결과를 반환한다."""
        self._logger.info("gate.evaluate.start", item_count=len(work_items))

        result = self._check_numeric_gate(work_items)

        if result.verdict is GateVerdict.PASS:
            self._logger.info(
                "gate.evaluate.pass",
                failure_rate=result.failure_rate,
                avg_duration=result.avg_duration,
            )
            await self._persist(result)
            return result

        # FAIL → CTO에게 위임
        self._logger.warning(
            "gate.evaluate.fail",
            failure_rate=result.failure_rate,
            reason=result.reason,
        )
        delegated = await self._delegate_to_cto(work_items, result)
        await self._persist(delegated)
        return delegated

    async def evaluate_emergency(self, blocking_item: dict[str, object]) -> GateResult:
        """blocking.detected 이벤트 수신 시 긴급 Gate 소집.

        Part 7 Stage 1: EmergencyMeeting 이 주입되어 있으면 실제 소규모 재합의를
        수행(DNA 가중 투표 → CTO 판단 → 3회 실패 시 DNA 폴백). 주입되지 않은
        경우(테스트·초기 배포 등) 기존 고정 REPLAN 동작 유지.
        """
        self._logger.warning(
            "gate.emergency.start",
            item_id=blocking_item.get("item_id"),
            agent_id=blocking_item.get("agent_id"),
        )

        if self._emergency_meeting is None:
            # 회의 모듈 미주입 — 기존 동작(즉시 REPLAN) 유지
            result = GateResult(
                verdict=GateVerdict.REPLAN,
                reason=f"blocking detected on item {blocking_item.get('item_id')}",
                failure_rate=1.0,
                avg_duration=0.0,
                total_items=1,
            )
            await self._persist(result)
            return result

        consensus = await self._emergency_meeting.convene(blocking_item)
        verdict = self._map_meeting_to_verdict(consensus.final_decision)
        reason = (
            f"meeting {consensus.meeting_id} → {consensus.final_decision.value} "
            f"(source={consensus.decision_source.value})"
        )
        result = GateResult(
            verdict=verdict,
            reason=reason,
            failure_rate=1.0,
            avg_duration=0.0,
            total_items=1,
        )
        self._logger.info(
            "gate.emergency.resolved",
            meeting_id=consensus.meeting_id,
            decision=consensus.final_decision.value,
            source=consensus.decision_source.value,
            verdict=verdict.value,
        )
        await self._persist(result)
        return result

    @staticmethod
    def _map_meeting_to_verdict(decision: MeetingDecision) -> GateVerdict:
        """회의 결정 → Gate verdict. ABORT만 중단, 나머지는 REPLAN."""
        if decision is MeetingDecision.ABORT:
            return GateVerdict.ABORT
        return GateVerdict.REPLAN

    # ------------------------------------------------------------------
    # 내부 평가 로직
    # ------------------------------------------------------------------

    def _check_numeric_gate(self, work_items: list[WorkItem]) -> GateResult:
        """순수 수치 기반 Gate 평가 — LLM 호출 없음."""
        total = len(work_items)
        if total == 0:
            return GateResult(
                verdict=GateVerdict.PASS,
                reason="no work items to evaluate",
                failure_rate=0.0,
                avg_duration=0.0,
                total_items=0,
            )

        failed = sum(
            1 for item in work_items if item.status in (WorkStatus.FAILED, WorkStatus.BLOCKED)
        )
        failure_rate = failed / total

        durations: list[float] = []
        for item in work_items:
            if item.result is not None and item.status is WorkStatus.DONE:
                delta = (item.updated_at - item.created_at).total_seconds()
                if delta > 0:
                    durations.append(delta)
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        if failure_rate > self._config.max_failure_rate:
            return GateResult(
                verdict=GateVerdict.ABORT,  # CTO가 REPLAN으로 바꿀 수 있음
                reason=(
                    f"failure rate {failure_rate:.1%} exceeds threshold "
                    f"{self._config.max_failure_rate:.1%}"
                ),
                failure_rate=failure_rate,
                avg_duration=avg_duration,
                total_items=total,
            )

        return GateResult(
            verdict=GateVerdict.PASS,
            reason="all numeric thresholds met",
            failure_rate=failure_rate,
            avg_duration=avg_duration,
            total_items=total,
        )

    async def _delegate_to_cto(
        self,
        work_items: list[WorkItem],
        gate_result: GateResult,
    ) -> GateResult:
        """Gate 실패 시 CTOAgent.review_progress()로 REPLAN/ABORT 결정."""
        from domain.contracts import WorkItem as _WI  # noqa: F401 — import guard

        # WorkItem 목록을 CTO review format으로 전달
        review = await self._cto.review_progress(work_items)

        if review.decision is ReviewDecision.REPLAN:
            verdict = GateVerdict.REPLAN
        else:
            verdict = GateVerdict.ABORT

        self._logger.info(
            "gate.cto_delegated",
            cto_decision=review.decision.value,
            cto_reason=review.reason,
            verdict=verdict.value,
        )
        return GateResult(
            verdict=verdict,
            reason=f"CTO: {review.reason}",
            failure_rate=gate_result.failure_rate,
            avg_duration=gate_result.avg_duration,
            total_items=gate_result.total_items,
        )

    async def _persist(self, result: GateResult) -> None:
        """Gate 결과를 SQLite에 저장한다."""
        key = f"{_GATE_RESULT_KEY_PREFIX}{self._run_id}_{datetime.now(timezone.utc).isoformat()}"
        payload: dict[str, object] = {
            "run_id": self._run_id,
            "result": result.verdict.value,
            "reason": result.reason,
            "failure_rate": result.failure_rate,
            "avg_duration": result.avg_duration,
            "total_items": result.total_items,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._storage.save(key, payload)

    def _on_blocking_detected(
        self, event_type: str = "blocking.detected", payload: dict[str, object] | None = None
    ) -> None:
        """EventBus 핸들러 — blocking.detected 이벤트 수신 시 비동기 긴급 Gate 소집.

        EventBusPort 의 EventHandler 시그니처(event_type, payload)와 일치해야 한다.
        직접 호출 편의를 위해 두 매개변수 모두 기본값을 가진다.
        """
        if payload is None:
            return
        self._blocking_items.append(payload)
        # EventBus 핸들러는 동기이므로 asyncio.create_task로 비동기 Gate 소집
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.evaluate_emergency(payload))
        except RuntimeError:
            # 이벤트 루프가 없는 컨텍스트(테스트 등)에서는 기록만 남김
            log.warning("gate.emergency.no_loop", item_id=payload.get("item_id"))

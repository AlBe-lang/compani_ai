"""EmergencyMeeting — Part 7 Stage 1 자율 협업 긴급 회의.

StageGate 의 blocking.detected 핸들러가 단일 아이템을 즉시 REPLAN 으로
고정하던 자리를 "실제 소규모 재합의" 로 확장한다. 의사결정 흐름:

  1. 참여자 선정 (3자 구조, 중복 제거)
     - blocking 소유자
     - 의존성 소스 에이전트 (blocking_item["dep_source_agent_id"] 가 있으면)
     - KnowledgeGraph 전문가 (blocking_reason 기반 find_best_responder)
  2. 투표 요청 발송 — MessageQueuePort.send + context dict 메타
  3. 투표 수집 — response_timeout 이내 미응답은 ABSTAIN 기록
  4. 집계 — DNA (collaboration/precision) 가중 투표 → CTO 최종 판단
     - CTO LLM 호출은 최대 cto_max_retries (기본 3) 회 재시도
     - 3회 모두 실패 시 DNA 가중 투표 결과로 폴백 (MetricsCollector 로 기록)
  5. 영속화 — SQLite + Qdrant (Rule 10 §1 컨텍스트 보존)
  6. 참여 집계 — DNAManager.update_meeting_participation (Stage 1 단순 카운트)

Rule 10 §3 (교체 가능한 스토리지) — 모든 외부 의존은 Port 인터페이스로 주입,
QdrantStorage / DNAManager / MetricsCollector 는 선택적 (None 허용).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from domain.contracts import (
    AgentDNA,
    ConsensusResult,
    DecisionSource,
    MeetingDecision,
    MeetingRequest,
    MeetingVote,
    Message,
    MessageType,
)
from domain.ports import KnowledgeGraphPort, LLMProvider, MessageQueuePort, StoragePort
from observability.logger import get_logger
from observability.parsers import ParseResponseError, parse_json_response

if TYPE_CHECKING:
    from adapters.qdrant_storage import QdrantStorage
    from application.dna_manager import DNAManager
    from observability.metrics import MetricsCollector

log = get_logger(__name__)

_MEETING_KEY_PREFIX = "meeting:"
_MEETING_SENDER_ID = "emergency_meeting"

# Default per-vote collection timeout (seconds). 30s aligns with
# base_agent._ask_question default so SLM response curves overlap.
_DEFAULT_RESPONSE_TIMEOUT_SEC = 30.0
_DEFAULT_CTO_MAX_RETRIES = 3
_DEFAULT_CTO_RETRY_INTERVAL_SEC = 2.0
_CTO_CALL_TIMEOUT_SEC = 30.0
_CTO_TEMPERATURE = 0.3
_CTO_MAX_TOKENS = 512

# Weights for DNA-based vote tally. collaboration speaks to meeting quality,
# precision to how reliable an agent's opinion tends to be; 50/50 split is
# the simplest defensible prior for Stage 1. Stage 2+ may tune per role.
_WEIGHT_COLLABORATION = 0.5
_WEIGHT_PRECISION = 0.5


@dataclass(frozen=True)
class EmergencyMeetingConfig:
    response_timeout_sec: float = _DEFAULT_RESPONSE_TIMEOUT_SEC
    cto_max_retries: int = _DEFAULT_CTO_MAX_RETRIES
    cto_retry_interval_sec: float = _DEFAULT_CTO_RETRY_INTERVAL_SEC
    cto_model: str = "llama3.1:8b"


class EmergencyMeeting:
    """Convene a small-scale meeting when a blocking.detected event arrives."""

    def __init__(
        self,
        *,
        queue: MessageQueuePort,
        storage: StoragePort,
        knowledge_graph: KnowledgeGraphPort | None,
        llm: LLMProvider,
        run_id: str,
        config: EmergencyMeetingConfig | None = None,
        dna_manager: "DNAManager | None" = None,
        qdrant: "QdrantStorage | None" = None,
        metrics: "MetricsCollector | None" = None,
    ) -> None:
        self._queue = queue
        self._storage = storage
        self._kg = knowledge_graph
        self._llm = llm
        self._run_id = run_id
        self._config = config or EmergencyMeetingConfig()
        self._dna_manager = dna_manager
        self._qdrant = qdrant
        self._metrics = metrics
        self._logger = get_logger(component="emergency_meeting", run_id=run_id)

    # ------------------------------------------------------------------
    # 퍼블릭 API
    # ------------------------------------------------------------------

    async def convene(self, blocking_item: dict[str, object]) -> ConsensusResult:
        """Full meeting lifecycle for a single blocking item."""
        meeting_id = f"meeting_{uuid.uuid4().hex[:16]}"
        participants = await self._select_participants(blocking_item)

        request = MeetingRequest(
            meeting_id=meeting_id,
            blocking_item_id=str(blocking_item.get("item_id", "")),
            blocking_owner_agent_id=str(blocking_item.get("agent_id", "")),
            blocking_reason=str(blocking_item.get("reason", "")),
            participant_agent_ids=participants,
        )
        self._logger.info(
            "meeting.convene.start",
            meeting_id=meeting_id,
            participants=participants,
            blocking_item=request.blocking_item_id,
        )

        await self._send_requests(request)
        votes = await self._collect_votes(request)
        result = await self._aggregate(request, votes)
        await self._persist(request, result)
        await self._update_participation(participants)

        self._logger.info(
            "meeting.convene.done",
            meeting_id=meeting_id,
            decision=result.final_decision.value,
            source=result.decision_source.value,
            abstain_count=result.abstain_count,
        )
        return result

    # ------------------------------------------------------------------
    # 1. 참여자 선정
    # ------------------------------------------------------------------

    async def _select_participants(self, blocking_item: dict[str, object]) -> list[str]:
        """3자 구조 + 중복 제거. 최소 1명(소유자만)도 허용."""
        owner = str(blocking_item.get("agent_id", ""))
        dep_source = str(blocking_item.get("dep_source_agent_id", "") or "")
        reason = str(blocking_item.get("reason", ""))

        participants: list[str] = []
        if owner:
            participants.append(owner)
        if dep_source and dep_source not in participants:
            participants.append(dep_source)

        if self._kg is not None and reason:
            try:
                expert = await self._kg.find_best_responder(reason)
            except Exception as exc:
                self._logger.warning("meeting.kg_error", detail=str(exc))
                expert = None
            if expert and expert not in participants:
                participants.append(expert)

        return participants

    # ------------------------------------------------------------------
    # 2. 요청 발송
    # ------------------------------------------------------------------

    async def _send_requests(self, request: MeetingRequest) -> None:
        """Broadcast one QUESTION message per participant with meeting meta."""
        for participant in request.participant_agent_ids:
            context: dict[str, object] = {
                "meeting_id": request.meeting_id,
                "meeting_role": "voter",
                "blocking_item_id": request.blocking_item_id,
                "blocking_reason": request.blocking_reason,
                "blocking_owner_agent_id": request.blocking_owner_agent_id,
                "possible_decisions": [d.value for d in MeetingDecision],
            }
            await self._queue.send(
                from_agent=_MEETING_SENDER_ID,
                to_agent=participant,
                content=f"[긴급 회의] 다음 결정 중 하나를 투표: {request.blocking_reason}",
                message_type=MessageType.QUESTION,
                context=context,
            )

    # ------------------------------------------------------------------
    # 3. 투표 수집
    # ------------------------------------------------------------------

    async def _collect_votes(self, request: MeetingRequest) -> list[MeetingVote]:
        """Wait for each participant's reply. Missing/invalid → ABSTAIN."""
        tasks = [
            asyncio.create_task(self._collect_one(request.meeting_id, participant))
            for participant in request.participant_agent_ids
        ]
        return list(await asyncio.gather(*tasks))

    async def _collect_one(self, meeting_id: str, participant: str) -> MeetingVote:
        """Single participant vote collector."""
        try:
            msg = await self._queue.receive(
                agent_id=_MEETING_SENDER_ID,
                timeout_sec=self._config.response_timeout_sec,
            )
        except Exception as exc:
            self._logger.warning("meeting.receive_error", participant=participant, detail=str(exc))
            return self._abstain(meeting_id, participant, "receive_error")

        if msg is None:
            return self._abstain(meeting_id, participant, "timeout")

        decision = self._parse_vote(msg)
        if decision is None:
            return self._abstain(meeting_id, participant, "invalid_vote")

        return MeetingVote(
            meeting_id=meeting_id,
            voter_agent_id=msg.from_agent or participant,
            decision=decision,
            rationale=msg.content[:500],
        )

    def _parse_vote(self, msg: Message) -> MeetingDecision | None:
        """Extract a MeetingDecision from a reply. Accepts context['decision']
        (preferred) or a leading word in ``content`` matching a decision enum.
        """
        raw = str((msg.context or {}).get("decision", "")).upper().strip()
        if not raw:
            # Fallback: first token of content
            token = msg.content.strip().split()[:1]
            raw = token[0].upper() if token else ""
        try:
            return MeetingDecision(raw)
        except ValueError:
            return None

    def _abstain(self, meeting_id: str, participant: str, reason: str) -> MeetingVote:
        """Construct an ABSTAIN vote with placeholder decision."""
        return MeetingVote(
            meeting_id=meeting_id,
            voter_agent_id=participant,
            decision=MeetingDecision.ABORT,  # ignored when abstained=True
            rationale=reason,
            abstained=True,
        )

    # ------------------------------------------------------------------
    # 4. 집계 (DNA 가중 → CTO → 폴백)
    # ------------------------------------------------------------------

    async def _aggregate(
        self, request: MeetingRequest, votes: list[MeetingVote]
    ) -> ConsensusResult:
        tally = await self._weighted_tally(votes)
        abstain_count = sum(1 for v in votes if v.abstained)

        cto_outcome = await self._invoke_cto_with_retry(request, votes, tally)
        if cto_outcome is not None:
            decision, reason = cto_outcome
            return ConsensusResult(
                meeting_id=request.meeting_id,
                final_decision=decision,
                decision_source=DecisionSource.CTO,
                weighted_tally=tally,
                votes=votes,
                cto_reason=reason,
                abstain_count=abstain_count,
            )

        # Fallback: DNA-weighted winner; tie-break by blocking owner vote
        if self._metrics is not None:
            self._metrics.record_fallback(
                run_id=self._run_id,
                component="emergency_meeting",
                reason="cto_max_retries",
            )
        winner = self._resolve_fallback_winner(tally, request, votes)
        return ConsensusResult(
            meeting_id=request.meeting_id,
            final_decision=winner,
            decision_source=DecisionSource.DNA_FALLBACK,
            weighted_tally=tally,
            votes=votes,
            fallback_reason="cto_unavailable_after_retries",
            abstain_count=abstain_count,
        )

    async def _weighted_tally(self, votes: list[MeetingVote]) -> dict[str, float]:
        """Sum DNA-weighted scores per decision, skipping abstentions."""
        tally: dict[str, float] = {d.value: 0.0 for d in MeetingDecision}
        for vote in votes:
            if vote.abstained:
                continue
            weight = await self._voter_weight(vote.voter_agent_id)
            tally[vote.decision.value] += weight
        return tally

    async def _voter_weight(self, agent_id: str) -> float:
        """DNA-based weight. Falls back to neutral 0.5 when DNAManager absent
        or load fails. collaboration × 0.5 + precision × 0.5."""
        if self._dna_manager is None:
            return 0.5
        try:
            dna: AgentDNA = await self._dna_manager.load(
                agent_id, role=self._role_from_agent_id(agent_id)
            )
        except Exception as exc:
            self._logger.warning("meeting.dna_load_error", agent_id=agent_id, detail=str(exc))
            return 0.5
        collab = dna.genes.get("collaboration", 0.5)
        precision = dna.genes.get("precision", 0.5)
        return _WEIGHT_COLLABORATION * collab + _WEIGHT_PRECISION * precision

    def _resolve_fallback_winner(
        self,
        tally: dict[str, float],
        request: MeetingRequest,
        votes: list[MeetingVote],
    ) -> MeetingDecision:
        """Pick the top-scoring decision. Ties → blocking owner's vote wins;
        if owner abstained or vote not in winners, pick alphabetically first
        (deterministic) among winners."""
        if all(score == 0.0 for score in tally.values()):
            # Everyone abstained. Conservative default: ESCALATE to CTO.
            return MeetingDecision.ESCALATE

        max_score = max(tally.values())
        winners = sorted(d for d, s in tally.items() if s == max_score)
        if len(winners) == 1:
            return MeetingDecision(winners[0])

        owner_vote = next(
            (
                v
                for v in votes
                if v.voter_agent_id == request.blocking_owner_agent_id and not v.abstained
            ),
            None,
        )
        if owner_vote is not None and owner_vote.decision.value in winners:
            return owner_vote.decision
        return MeetingDecision(winners[0])

    async def _invoke_cto_with_retry(
        self,
        request: MeetingRequest,
        votes: list[MeetingVote],
        tally: dict[str, float],
    ) -> tuple[MeetingDecision, str] | None:
        """Up to config.cto_max_retries LLM calls. None if all attempts fail."""
        prompt = self._build_cto_prompt(request, votes, tally)
        for attempt in range(1, self._config.cto_max_retries + 1):
            try:
                raw = await asyncio.wait_for(
                    self._llm.generate(
                        model=self._config.cto_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=_CTO_TEMPERATURE,
                        max_tokens=_CTO_MAX_TOKENS,
                    ),
                    timeout=_CTO_CALL_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                self._logger.warning(
                    "meeting.cto.timeout", attempt=attempt, meeting_id=request.meeting_id
                )
                raw = None
            except Exception as exc:
                self._logger.warning(
                    "meeting.cto.error",
                    attempt=attempt,
                    meeting_id=request.meeting_id,
                    detail=str(exc),
                )
                raw = None

            if raw is not None:
                parsed = self._parse_cto_response(raw)
                if parsed is not None:
                    return parsed

            if attempt < self._config.cto_max_retries:
                await asyncio.sleep(self._config.cto_retry_interval_sec)

        return None

    def _parse_cto_response(self, raw: str) -> tuple[MeetingDecision, str] | None:
        """Extract (decision, reason) from CTO JSON reply."""
        try:
            payload = parse_json_response(raw)
        except ParseResponseError:
            return None
        decision_str = str(payload.get("decision", "")).upper()
        try:
            decision = MeetingDecision(decision_str)
        except ValueError:
            return None
        reason = str(payload.get("reason", "")).strip()
        return decision, reason

    def _build_cto_prompt(
        self,
        request: MeetingRequest,
        votes: list[MeetingVote],
        tally: dict[str, float],
    ) -> str:
        vote_lines = "\n".join(
            (
                f"- {v.voter_agent_id}: ABSTAIN ({v.rationale})"
                if v.abstained
                else f"- {v.voter_agent_id}: {v.decision.value} — {v.rationale[:200]}"
            )
            for v in votes
        )
        tally_lines = "\n".join(
            f"- {decision}: weighted_score={score:.3f}"
            for decision, score in tally.items()
            if score > 0
        )
        if not tally_lines:
            tally_lines = "(all participants abstained)"

        return (
            "긴급 회의 최종 결정 요청.\n\n"
            f"Blocking 사유: {request.blocking_reason}\n"
            f"소유자 에이전트: {request.blocking_owner_agent_id}\n\n"
            "참여자 투표:\n"
            f"{vote_lines}\n\n"
            "DNA 가중 집계 (collaboration×0.5 + precision×0.5):\n"
            f"{tally_lines}\n\n"
            "가능한 결정: RETRY, REROUTE, ESCALATE, ABORT\n\n"
            "JSON 한 줄로만 응답:\n"
            '{"decision": "RETRY|REROUTE|ESCALATE|ABORT", "reason": "..."}\n'
        )

    # ------------------------------------------------------------------
    # 5. 영속화
    # ------------------------------------------------------------------

    async def _persist(self, request: MeetingRequest, result: ConsensusResult) -> None:
        """SQLite + Qdrant. Qdrant 실패는 로그만 남기고 진행(옵션 의존)."""
        payload: dict[str, object] = {
            "meeting_id": request.meeting_id,
            "blocking_item_id": request.blocking_item_id,
            "blocking_owner_agent_id": request.blocking_owner_agent_id,
            "blocking_reason": request.blocking_reason,
            "participant_agent_ids": request.participant_agent_ids,
            "final_decision": result.final_decision.value,
            "decision_source": result.decision_source.value,
            "weighted_tally": result.weighted_tally,
            "votes": [v.model_dump(mode="json") for v in result.votes],
            "cto_reason": result.cto_reason,
            "fallback_reason": result.fallback_reason,
            "abstain_count": result.abstain_count,
            "decided_at": result.decided_at.isoformat(),
            "run_id": self._run_id,
        }
        await self._storage.save(_MEETING_KEY_PREFIX + request.meeting_id, payload)

        if self._qdrant is not None:
            text = (
                f"[meeting] {request.blocking_reason} "
                f"→ {result.final_decision.value}: {result.cto_reason}"
            ).strip()
            qdrant_payload: dict[str, Any] = {
                "task_id": request.meeting_id,
                "agent_id": _MEETING_SENDER_ID,
                "approach": text,
                "success": result.final_decision is not MeetingDecision.ABORT,
                "run_id": self._run_id,
                "files": [],
            }
            try:
                await self._qdrant.add_task_result(qdrant_payload)
            except Exception as exc:
                self._logger.warning("meeting.qdrant_persist_error", detail=str(exc))

    # ------------------------------------------------------------------
    # 6. 참여 카운트
    # ------------------------------------------------------------------

    async def _update_participation(self, participants: list[str]) -> None:
        """DNAManager.update_meeting_participation per participant."""
        if self._dna_manager is None:
            return
        for agent_id in participants:
            try:
                await self._dna_manager.update_meeting_participation(
                    agent_id, role=self._role_from_agent_id(agent_id)
                )
            except Exception as exc:
                self._logger.warning(
                    "meeting.participation_update_error",
                    agent_id=agent_id,
                    detail=str(exc),
                )

    # ------------------------------------------------------------------
    # 공용 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _role_from_agent_id(agent_id: str) -> str:
        """Infer role from agent_id string (mirrors knowledge_graph helper)."""
        lowered = agent_id.lower()
        for role in ("backend", "frontend", "mlops", "cto"):
            if role in lowered:
                return role
        return "general"

    def _raise_on_invalid_request(self, request: MeetingRequest) -> None:
        """Validation gate — kept for clarity; Pydantic already enforces."""
        try:
            MeetingRequest.model_validate(request.model_dump())
        except ValidationError as exc:  # pragma: no cover — defense in depth
            raise ValueError(f"invalid MeetingRequest: {exc}") from exc

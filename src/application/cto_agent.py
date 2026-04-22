"""CTO agent for strategy planning."""

from __future__ import annotations

import asyncio
import heapq
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from domain.contracts import (
    Message,
    MessageType,
    ReviewDecision,
    ReviewResult,
    Strategy,
    Task,
    TaskResult,
    WorkItem,
    WorkStatus,
)
from domain.ports import AgentPort, LLMMessage, LLMProvider, MessageQueuePort, WorkSpacePort
from observability.error_codes import ErrorCode
from observability.logger import get_logger
from observability.parsers import ParseResponseError, parse_json_response

DEFAULT_MODEL = "llama3.1:70b"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_SEC = 120
DEFAULT_DECOMPOSE_TIMEOUT_SEC = 60
DEFAULT_REVIEW_TIMEOUT_SEC = 120
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAYS = (2.0, 4.0, 8.0)
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "cto" / "strategy.txt"
_DECOMPOSE_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "cto" / "decompose.txt"
_REVIEW_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "cto" / "review.txt"
_QA_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "cto" / "qa_response.txt"


class _ReviewSignal(BaseModel):
    """LLM review signal payload (decision + reason only)."""

    model_config = ConfigDict(extra="ignore")

    decision: ReviewDecision
    reason: str


@dataclass(frozen=True)
class CTOConfig:
    """Config for CTO strategy generation."""

    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    decompose_timeout_sec: int = DEFAULT_DECOMPOSE_TIMEOUT_SEC
    review_timeout_sec: int = DEFAULT_REVIEW_TIMEOUT_SEC
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS


class CTOAgentError(RuntimeError):
    """CTO agent domain error with classified code."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class CTOAgent:
    """Orchestrator agent that generates high-level project strategy."""

    def __init__(
        self,
        llm: LLMProvider,
        workspace: WorkSpacePort,
        team: dict[str, AgentPort],
        config: CTOConfig,
        run_id: str,
    ) -> None:
        self._llm = llm
        self._workspace = workspace
        self._team = team
        self._config = config
        self._run_id = run_id
        self._logger = get_logger(component="cto_agent", run_id=run_id).bind(agent_id="cto")
        self._strategy_prompt = self._load_strategy_prompt()
        self._decompose_prompt = self._load_decompose_prompt()
        self._review_prompt = self._load_review_prompt()
        self._qa_prompt = self._load_qa_prompt()
        self._last_strategy: Strategy | None = None

    async def create_strategy(self, project_request: str) -> Strategy:
        """Create a structured strategy from user project request."""
        self._logger.info("cto.strategy.start", request_length=len(project_request))
        last_error_code = ErrorCode.E_PARSE_JSON

        for attempt in range(1, self._config.max_retries + 1):
            raw = await self._llm.generate(
                model=self._config.model,
                messages=self._build_strategy_messages(project_request),
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                timeout_sec=self._config.timeout_sec,
            )
            try:
                payload = parse_json_response(raw)
                strategy = Strategy.model_validate(payload)
                self._last_strategy = strategy
                self._logger.info(
                    "cto.strategy.done",
                    attempt=attempt,
                    project_name=strategy.project_name,
                    task_count=0,
                    response_chars=self._response_chars(raw),
                )
                return strategy
            except ParseResponseError as exc:
                last_error_code = exc.code
                self._logger.warning(
                    "cto.strategy.retry",
                    attempt=attempt,
                    error_code=exc.code.value,
                    preview=raw[:200],
                )
            except ValidationError as exc:
                last_error_code = ErrorCode.E_PARSE_SCHEMA
                self._logger.warning(
                    "cto.strategy.retry",
                    attempt=attempt,
                    error_code=ErrorCode.E_PARSE_SCHEMA.value,
                    preview=raw[:200],
                    detail=str(exc),
                )

            if attempt < self._config.max_retries:
                await asyncio.sleep(self._delay_for_attempt(attempt - 1))

        self._logger.error(
            "cto.strategy.failed",
            error_code=last_error_code.value,
            attempts=self._config.max_retries,
        )
        raise CTOAgentError(last_error_code, "failed to create strategy from model response")

    async def decompose_tasks(self, strategy: Strategy) -> list[Task]:
        """Decompose strategy into executable task list."""
        self._logger.info("cto.decompose.start", project_name=strategy.project_name)
        last_error_code = ErrorCode.E_PARSE_SCHEMA

        for attempt in range(1, self._config.max_retries + 1):
            raw = await self._llm.generate(
                model=self._config.model,
                messages=self._build_decompose_messages(strategy),
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                timeout_sec=self._config.decompose_timeout_sec,
            )
            try:
                payload = parse_json_response(raw)
                raw_tasks = payload.get("tasks")
                if not isinstance(raw_tasks, list):
                    raise CTOAgentError(ErrorCode.E_PARSE_SCHEMA, "tasks field must be a list")

                tasks = [Task.model_validate(item) for item in raw_tasks]
                self._validate_task_count(tasks)
                self._validate_dependencies(tasks)
                ordered = self._topological_sort(tasks)

                self._logger.info(
                    "cto.decompose.done",
                    attempt=attempt,
                    task_count=len(ordered),
                    response_chars=self._response_chars(raw),
                )
                return ordered
            except ParseResponseError as exc:
                last_error_code = exc.code
                self._logger.warning(
                    "cto.decompose.retry",
                    attempt=attempt,
                    error_code=exc.code.value,
                    preview=raw[:200],
                )
            except ValidationError as exc:
                last_error_code = ErrorCode.E_PARSE_SCHEMA
                self._logger.warning(
                    "cto.decompose.retry",
                    attempt=attempt,
                    error_code=ErrorCode.E_PARSE_SCHEMA.value,
                    preview=raw[:200],
                    detail=str(exc),
                )
            except CTOAgentError as exc:
                last_error_code = exc.code
                self._logger.warning(
                    "cto.decompose.retry",
                    attempt=attempt,
                    error_code=exc.code.value,
                    preview=raw[:200],
                    detail=str(exc),
                )

            if attempt < self._config.max_retries:
                await asyncio.sleep(self._delay_for_attempt(attempt - 1))

        self._logger.error(
            "cto.decompose.failed",
            error_code=last_error_code.value,
            attempts=self._config.max_retries,
        )
        raise CTOAgentError(last_error_code, "failed to decompose tasks from model response")

    async def review_progress(self, work_items: list[WorkItem]) -> ReviewResult:
        """Review current work progress and decide next action."""
        total = len(work_items)
        failed_count = sum(1 for item in work_items if item.status is WorkStatus.FAILED)
        done_count = sum(1 for item in work_items if item.status is WorkStatus.DONE)

        if total > 0 and failed_count / total > 0.5:
            result = ReviewResult(
                decision=ReviewDecision.ABORT,
                reason="failed ratio is above 50%",
                new_tasks=[],
            )
            self._logger.info(
                "cto.review.done",
                decision=result.decision.value,
                done_count=done_count,
                failed_count=failed_count,
                total_count=total,
            )
            return result

        review_result, ignored_new_tasks_count, response_chars = await self._review_with_llm(work_items)
        if review_result.decision is not ReviewDecision.REPLAN:
            if ignored_new_tasks_count > 0:
                self._logger.info(
                    "cto.review.override_new_tasks",
                    decision=review_result.decision.value,
                    ignored_count=ignored_new_tasks_count,
                )
            self._logger.info(
                "cto.review.done",
                decision=review_result.decision.value,
                done_count=done_count,
                failed_count=failed_count,
                total_count=total,
                response_chars=response_chars,
            )
            return review_result

        if self._last_strategy is None:
            raise CTOAgentError(ErrorCode.E_SYSTEM_CONFIG, "strategy context is required for replan")

        if ignored_new_tasks_count > 0:
            self._logger.info(
                "cto.review.override_new_tasks",
                decision=review_result.decision.value,
                ignored_count=ignored_new_tasks_count,
            )

        planned = await self.decompose_tasks(self._last_strategy)
        done_task_ids = {item.task_id for item in work_items if item.status is WorkStatus.DONE}
        new_tasks = [task for task in planned if task.id not in done_task_ids]
        result = review_result.model_copy(update={"new_tasks": new_tasks})
        self._logger.info(
            "cto.review.done",
            decision=result.decision.value,
            done_count=done_count,
            failed_count=failed_count,
            total_count=total,
            new_task_count=len(result.new_tasks),
            response_chars=response_chars,
        )
        return result

    async def _review_with_llm(self, work_items: list[WorkItem]) -> tuple[ReviewResult, int, int]:
        last_error_code = ErrorCode.E_PARSE_JSON
        for attempt in range(1, self._config.max_retries + 1):
            raw = await self._llm.generate(
                model=self._config.model,
                messages=self._build_review_messages(work_items),
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                timeout_sec=self._config.review_timeout_sec,
            )
            try:
                payload = parse_json_response(raw)
                ignored_new_tasks_count = 0
                raw_new_tasks = payload.get("new_tasks")
                if isinstance(raw_new_tasks, list):
                    ignored_new_tasks_count = len(raw_new_tasks)
                signal = _ReviewSignal.model_validate(payload)
                result = ReviewResult(
                    decision=signal.decision,
                    reason=signal.reason,
                    new_tasks=[],
                )
                response_chars = self._response_chars(raw)
                return result, ignored_new_tasks_count, response_chars
            except ParseResponseError as exc:
                last_error_code = exc.code
                self._logger.warning(
                    "cto.review.retry",
                    attempt=attempt,
                    error_code=exc.code.value,
                    preview=raw[:200],
                )
            except ValidationError as exc:
                last_error_code = ErrorCode.E_PARSE_SCHEMA
                self._logger.warning(
                    "cto.review.retry",
                    attempt=attempt,
                    error_code=ErrorCode.E_PARSE_SCHEMA.value,
                    preview=raw[:200],
                    detail=str(exc),
                )

            if attempt < self._config.max_retries:
                await asyncio.sleep(self._delay_for_attempt(attempt - 1))

        raise CTOAgentError(last_error_code, "failed to review progress from model response")

    def _build_strategy_messages(self, project_request: str) -> list[LLMMessage]:
        return [
            {"role": "system", "content": self._strategy_prompt},
            {"role": "user", "content": project_request},
        ]

    def _build_decompose_messages(self, strategy: Strategy) -> list[LLMMessage]:
        return [
            {"role": "system", "content": self._decompose_prompt},
            {"role": "user", "content": json.dumps(strategy.model_dump(mode="json"))},
        ]

    def _build_review_messages(self, work_items: list[WorkItem]) -> list[LLMMessage]:
        payload = {"work_items": [item.model_dump(mode="json") for item in work_items]}
        return [
            {"role": "system", "content": self._review_prompt},
            {"role": "user", "content": json.dumps(payload)},
        ]

    def _validate_task_count(self, tasks: list[Task]) -> None:
        if len(tasks) < 3 or len(tasks) > 15:
            raise CTOAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"task count must be between 3 and 15: {len(tasks)}",
            )

    def _validate_dependencies(self, tasks: list[Task]) -> None:
        ids = [task.id for task in tasks]
        if len(set(ids)) != len(ids):
            raise CTOAgentError(ErrorCode.E_PARSE_SCHEMA, "task ids must be unique")

        id_set = set(ids)
        for task in tasks:
            for dep in task.dependencies:
                if dep not in id_set:
                    raise CTOAgentError(
                        ErrorCode.E_PARSE_SCHEMA,
                        f"unknown dependency {dep} in task {task.id}",
                    )

    def _topological_sort(self, tasks: list[Task]) -> list[Task]:
        task_by_id = {task.id: task for task in tasks}
        in_degree: dict[str, int] = {task.id: 0 for task in tasks}
        dependents: dict[str, list[str]] = defaultdict(list)

        for task in tasks:
            for dep in task.dependencies:
                dependents[dep].append(task.id)
                in_degree[task.id] += 1

        ready_heap: list[tuple[int, str]] = []
        for task in tasks:
            if in_degree[task.id] == 0:
                heapq.heappush(ready_heap, (task.priority, task.id))

        ordered: list[Task] = []
        while ready_heap:
            _, task_id = heapq.heappop(ready_heap)
            ordered.append(task_by_id[task_id])

            for dependent_id in sorted(dependents[task_id]):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    dep_task = task_by_id[dependent_id]
                    heapq.heappush(ready_heap, (dep_task.priority, dep_task.id))

        if len(ordered) != len(tasks):
            raise CTOAgentError(ErrorCode.E_DEPS_DEADLOCK, "cyclic dependency detected")
        return ordered

    def _delay_for_attempt(self, index: int) -> float:
        if not self._config.retry_delays:
            return 0.0
        bounded_index = min(index, len(self._config.retry_delays) - 1)
        return self._config.retry_delays[bounded_index]

    def _response_chars(self, text: str) -> int:
        return len(text)

    # ------------------------------------------------------------------
    # Q&A background handler
    # ------------------------------------------------------------------

    async def handle_questions(self, queue: MessageQueuePort) -> None:
        """Background loop: receive agent questions and respond via LLM.

        Runs concurrently with agent execution (asyncio.create_task).
        Exits cleanly on CancelledError when all agents finish.
        """
        self._logger.info("cto.qa_loop.start")
        try:
            while True:
                msg = await queue.receive("cto", timeout_sec=1.0)
                if msg is None:
                    await asyncio.sleep(0.05)
                    continue
                if msg.type is MessageType.QUESTION:
                    await self._handle_one_question(queue, msg)
        except asyncio.CancelledError:
            self._logger.info("cto.qa_loop.stopped")
            raise

    async def _handle_one_question(
        self, queue: MessageQueuePort, msg: Message
    ) -> None:
        """Generate an LLM answer and route it back to the asking agent."""
        self._logger.info(
            "cto.qa.received",
            from_agent=msg.from_agent,
            question_len=len(msg.content),
        )
        try:
            answer = await self._generate_qa_answer(msg)
            await queue.send(
                from_agent="cto",
                to_agent=msg.from_agent,
                content=answer,
                message_type=MessageType.ANSWER,
                context={"question_id": msg.id},
            )
            self._logger.info(
                "cto.qa.answered",
                from_agent=msg.from_agent,
                answer_len=len(answer),
            )
        except Exception as exc:
            # Do not crash the loop — log and continue
            self._logger.warning(
                "cto.qa.error",
                from_agent=msg.from_agent,
                detail=str(exc),
            )

    async def _generate_qa_answer(self, msg: Message) -> str:
        """Call LLM to produce a concise answer to an agent's question."""
        messages = self._build_qa_messages(msg)
        raw = await self._llm.generate(
            model=self._config.model,
            messages=messages,
            temperature=self._config.temperature,
            max_tokens=512,
            timeout_sec=30,
        )
        return raw.strip()

    def _build_qa_messages(self, msg: Message) -> list[LLMMessage]:
        context_str = ""
        if msg.context:
            import json as _json
            context_str = f"\n\nContext provided by agent:\n{_json.dumps(msg.context, indent=2)}"
        user_content = f"Question from {msg.from_agent}:\n{msg.content}{context_str}"
        return [
            {"role": "system", "content": self._qa_prompt},
            {"role": "user", "content": user_content},
        ]

    def _load_strategy_prompt(self) -> str:
        if _PROMPT_PATH.exists():
            return _PROMPT_PATH.read_text(encoding="utf-8")
        return (
            "You are a senior CTO. Return output as JSON only. "
            "Required fields: project_name, description, tech_stack, constraints"
        )

    def _load_decompose_prompt(self) -> str:
        if _DECOMPOSE_PROMPT_PATH.exists():
            return _DECOMPOSE_PROMPT_PATH.read_text(encoding="utf-8")
        return (
            "Decompose strategy into task list. Return JSON object with key tasks. "
            "Each task must include id, title, description, agent_role, dependencies, priority."
        )

    def _load_review_prompt(self) -> str:
        if _REVIEW_PROMPT_PATH.exists():
            return _REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
        return (
            "Review work items and return JSON with decision and reason. "
            "decision must be continue, replan, or abort."
        )

    def _load_qa_prompt(self) -> str:
        if _QA_PROMPT_PATH.exists():
            return _QA_PROMPT_PATH.read_text(encoding="utf-8")
        return (
            "You are the CTO. Answer the agent's question concisely and technically. "
            "Focus on what the agent needs to complete its task."
        )

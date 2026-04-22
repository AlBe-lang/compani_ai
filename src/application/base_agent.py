"""Shared execution flow for SLM agents."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from domain.contracts import AgentRole, Task, TaskResult, WorkItem, WorkStatus
from domain.ports import LLMMessage, LLMProvider, MessageQueuePort, WorkSpacePort
from observability.error_codes import ErrorCode
from observability.logger import get_logger
from observability.parsers import ParseResponseError, parse_json_response

DEFAULT_MODEL = "phi3.5"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_SEC = 90
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAYS = (2.0, 4.0, 8.0)
DEFAULT_DEP_TIMEOUT_SEC = 300.0
DEFAULT_DEP_POLL_SEC = 2.0
DEFAULT_QA_TIMEOUT_SEC = 30.0
_REQUIRED_FILE_KEYS = {"name", "path", "content", "type"}
_RETRY_JSON_ONLY_HINT = (
    "Return only valid JSON. Do not include markdown code fences or additional commentary."
)
_EXTERNAL_INTERFACE_KEYWORDS = ("api", "interface", "schema", "contract", "endpoint", "spec")


@dataclass(frozen=True)
class SLMConfig:
    """Config shared by SLM execution agents."""

    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS
    dep_timeout_sec: float = DEFAULT_DEP_TIMEOUT_SEC
    dep_poll_sec: float = DEFAULT_DEP_POLL_SEC
    qa_timeout_sec: float = DEFAULT_QA_TIMEOUT_SEC


class SLMAgentError(RuntimeError):
    """SLM execution error with classified code."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class BaseSLMAgent(ABC):
    """Template method implementation for SLM task execution."""

    def __init__(
        self,
        role: AgentRole,
        llm: LLMProvider,
        workspace: WorkSpacePort,
        queue: MessageQueuePort,
        config: SLMConfig,
        run_id: str,
        *,
        agent_id: str | None = None,
        prompt_path: Path | None = None,
    ) -> None:
        self._role = role
        self._llm = llm
        self._workspace = workspace
        self._queue = queue
        self._config = config
        self._run_id = run_id
        self._agent_id = agent_id or role.value
        self._prompt_path = prompt_path
        self._logger = get_logger(component=f"{role.value}_agent", run_id=run_id).bind(
            agent_id=self._agent_id,
            role=role.value,
        )
        self._system_prompt = self._get_system_prompt()

    async def execute_task(self, task: Task) -> TaskResult:
        """Execute a task with dependency wait, optional Q&A, and retry parsing."""
        self._validate_task_role(task)
        work_item_id: str | None = None
        self._logger.info(
            "slm.task.start",
            task_id=task.id,
            dependency_count=len(task.dependencies),
        )
        try:
            work_item = self._new_work_item(task)
            work_item_id = await self._workspace.register(work_item)
            await self._handle_dependencies(task, work_item_id)
            context = await self._build_context(task)
            result, response_chars = await self._generate_result_with_retry(task, context)
            await self._workspace.set_status(work_item_id, WorkStatus.DONE)
            await self._workspace.attach_result(work_item_id, result)
            self._logger.info(
                "slm.task.done",
                task_id=task.id,
                work_item_id=work_item_id,
                file_count=len(result.files),
                dependency_count=len(result.dependencies),
                response_chars=response_chars,
            )
            return result
        except SLMAgentError as exc:
            await self._mark_failed(work_item_id, task, exc.code)
            self._logger.error(
                "slm.task.failed",
                task_id=task.id,
                work_item_id=work_item_id,
                error_code=exc.code.value,
                detail=str(exc),
            )
            raise
        except Exception as exc:
            unknown = SLMAgentError(ErrorCode.E_SYSTEM_UNKNOWN, f"unexpected error: {exc}")
            await self._mark_failed(work_item_id, task, unknown.code)
            self._logger.error(
                "slm.task.failed",
                task_id=task.id,
                work_item_id=work_item_id,
                error_code=unknown.code.value,
                detail=str(exc),
            )
            raise unknown from exc

    def _validate_task_role(self, task: Task) -> None:
        if task.agent_role is not self._role:
            raise SLMAgentError(
                ErrorCode.E_SYSTEM_CONFIG,
                f"task role mismatch: expected {self._role.value}, got {task.agent_role.value}",
            )

    async def _handle_dependencies(self, task: Task, work_item_id: str) -> None:
        if not task.dependencies:
            await self._workspace.set_status(work_item_id, WorkStatus.IN_PROGRESS)
            return

        await self._workspace.set_status(work_item_id, WorkStatus.WAITING)
        self._logger.info(
            "slm.deps.waiting",
            task_id=task.id,
            dependencies=task.dependencies,
            poll_sec=self._config.dep_poll_sec,
            timeout_sec=self._config.dep_timeout_sec,
        )
        await self._wait_dependencies(task.dependencies)
        await self._workspace.set_status(work_item_id, WorkStatus.IN_PROGRESS)

    async def _wait_dependencies(self, dependencies: list[str]) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._config.dep_timeout_sec

        for dep_id in dependencies:
            while True:
                if loop.time() > deadline:
                    raise SLMAgentError(ErrorCode.E_DEPS_TIMEOUT, f"dependency timeout: {dep_id}")

                dep_item = await self._workspace.get_by_task_id(dep_id)
                if dep_item is None:
                    raise SLMAgentError(
                        ErrorCode.E_DEPS_BLOCKED,
                        f"dependency not found: {dep_id}",
                    )
                if dep_item.status is WorkStatus.DONE:
                    break
                if dep_item.status in (WorkStatus.FAILED, WorkStatus.BLOCKED):
                    raise SLMAgentError(
                        ErrorCode.E_DEPS_BLOCKED,
                        f"dependency blocked: {dep_id} status={dep_item.status.value}",
                    )

                await asyncio.sleep(self._config.dep_poll_sec)

    async def _build_context(self, task: Task) -> dict[str, object]:
        context: dict[str, object] = {}
        if await self._check_needs_info(task):
            question = self._formulate_question(task)
            qa_context: dict[str, object] = {"task_id": task.id, "task_title": task.title}
            answer = await self._ask_question(question, qa_context)
            context["qa_answer"] = answer
        return context

    async def _check_needs_info(self, task: Task) -> bool:
        if task.dependencies or "?" in task.description:
            return True
        return self._requires_external_interface(task.acceptance_criteria)

    def _requires_external_interface(self, acceptance_criteria: list[str]) -> bool:
        for criterion in acceptance_criteria:
            lowered = criterion.lower()
            if any(keyword in lowered for keyword in _EXTERNAL_INTERFACE_KEYWORDS):
                return True
        return False

    def _formulate_question(self, task: Task) -> str:
        return f"Need clarification for '{task.title}': {task.description}"

    async def _ask_question(self, question: str, context: dict[str, object]) -> str:
        try:
            self._logger.info(
                "slm.qa.sent",
                task_id=context.get("task_id"),
                question_preview=question[:120],
                to_agent="cto",
            )
            return await self._queue.ask(
                from_agent=self._agent_id,
                to_agent="cto",
                question=question,
                context=context,
                timeout_sec=self._config.qa_timeout_sec,
            )
        except asyncio.TimeoutError:
            self._logger.warning(
                "slm.qa.timeout",
                question=question[:120],
                task_id=context.get("task_id"),
            )
            return ""

    async def _generate_result_with_retry(
        self,
        task: Task,
        context: dict[str, object],
    ) -> tuple[TaskResult, int]:
        last_error_code = ErrorCode.E_PARSE_JSON

        for attempt in range(1, self._config.max_retries + 1):
            raw = await self._call_llm_once(task, context, attempt)
            result, error_code = self._parse_result_once(task, raw, attempt)
            if result is not None:
                return result, len(raw)
            last_error_code = error_code
            if attempt < self._config.max_retries:
                await asyncio.sleep(self._delay_for_attempt(attempt - 1))

        raise SLMAgentError(last_error_code, "failed to parse task result from model response")

    async def _call_llm_once(
        self,
        task: Task,
        context: dict[str, object],
        attempt: int,
    ) -> str:
        self._logger.info(
            "slm.llm.call",
            task_id=task.id,
            model=self._config.model,
            attempt=attempt,
            timeout_sec=self._config.timeout_sec,
        )
        return await self._llm.generate(
            model=self._config.model,
            messages=self._build_prompt(task, context, attempt),
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            timeout_sec=self._config.timeout_sec,
        )

    def _parse_result_once(
        self,
        task: Task,
        raw: str,
        attempt: int,
    ) -> tuple[TaskResult | None, ErrorCode]:
        try:
            return self._parse_response(task, raw), ErrorCode.E_PARSE_JSON
        except ParseResponseError as exc:
            self._log_retry(task.id, attempt, exc.code, raw)
            return None, exc.code
        except ValidationError as exc:
            error_code = ErrorCode.E_PARSE_SCHEMA
            self._log_retry(task.id, attempt, error_code, raw, detail=str(exc))
            return None, error_code
        except SLMAgentError as exc:
            self._log_retry(task.id, attempt, exc.code, raw, detail=str(exc))
            return None, exc.code

    def _log_retry(
        self,
        task_id: str,
        attempt: int,
        error_code: ErrorCode,
        raw: str,
        *,
        detail: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "task_id": task_id,
            "attempt": attempt,
            "error_code": error_code.value,
            "preview": raw[:200],
        }
        if detail:
            payload["detail"] = detail
        self._logger.warning("slm.task.retry", **payload)

    def _parse_response(self, task: Task, raw: str) -> TaskResult:
        payload = parse_json_response(raw)
        self._validate_files(payload)
        normalized = self._normalize_payload(task, payload)
        return TaskResult.model_validate(normalized)

    def _parse_task_result(self, task: Task, raw: str) -> TaskResult:
        return self._parse_response(task, raw)

    def _validate_files(self, payload: dict[str, object]) -> None:
        raw_files = payload.get("files")
        if raw_files is None:
            raise SLMAgentError(ErrorCode.E_PARSE_SCHEMA, "files field is required")
        if not isinstance(raw_files, list):
            raise SLMAgentError(ErrorCode.E_PARSE_SCHEMA, "files field must be a list")
        if not raw_files:
            raise SLMAgentError(ErrorCode.E_PARSE_SCHEMA, "files field must not be empty")

        for index, item in enumerate(raw_files):
            if not isinstance(item, dict):
                raise SLMAgentError(
                    ErrorCode.E_PARSE_SCHEMA,
                    f"files[{index}] must be an object",
                )
            missing = _REQUIRED_FILE_KEYS - set(item.keys())
            if missing:
                missing_sorted = ", ".join(sorted(missing))
                raise SLMAgentError(
                    ErrorCode.E_PARSE_SCHEMA,
                    f"files[{index}] missing keys: {missing_sorted}",
                )

    def _normalize_payload(self, task: Task, payload: dict[str, object]) -> dict[str, object]:
        normalized = dict(payload)
        normalized.setdefault("task_id", task.id)
        normalized.setdefault("agent_id", self._agent_id)
        normalized.setdefault("success", True)
        normalized.setdefault("dependencies", [])
        normalized.setdefault("setup_commands", [])

        raw_code = normalized.get("code")
        if isinstance(raw_code, dict):
            normalized["code"] = json.dumps(raw_code, ensure_ascii=False)

        return normalized

    def _build_prompt(
        self,
        task: Task,
        context: dict[str, object],
        attempt: int = 1,
    ) -> list[LLMMessage]:
        user_payload = {
            "task": task.model_dump(mode="json"),
            "context": context,
        }
        user_content = json.dumps(user_payload, ensure_ascii=False)
        if attempt >= 2:
            user_content = f"{_RETRY_JSON_ONLY_HINT}\n\n{user_content}"
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _build_messages(self, task: Task, context: dict[str, object]) -> list[LLMMessage]:
        return self._build_prompt(task, context)

    def _new_work_item(self, task: Task) -> WorkItem:
        return WorkItem(
            id=self._new_work_item_id(task.id),
            task_id=task.id,
            agent_id=self._agent_id,
            status=WorkStatus.PLANNED,
        )

    def _new_work_item_id(self, task_id: str) -> str:
        return f"work_{task_id}_{uuid4().hex[:8]}"

    async def _mark_failed(self, work_item_id: str | None, task: Task, code: ErrorCode) -> None:
        if not work_item_id:
            return
        try:
            await self._workspace.set_status(work_item_id, WorkStatus.FAILED)
            failure_result = TaskResult(
                task_id=task.id,
                agent_id=self._agent_id,
                approach="execution failed",
                code="",
                files=[],
                dependencies=[],
                setup_commands=[],
                success=False,
                error_code=code,
            )
            await self._workspace.attach_result(work_item_id, failure_result)
        except Exception as exc:  # pragma: no cover - defensive path
            self._logger.warning(
                "slm.task.fail_mark_error",
                task_id=task.id,
                work_item_id=work_item_id,
                detail=str(exc),
            )

    def _delay_for_attempt(self, index: int) -> float:
        if not self._config.retry_delays:
            return 0.0
        bounded_index = min(index, len(self._config.retry_delays) - 1)
        return self._config.retry_delays[bounded_index]

    def _get_system_prompt(self) -> str:
        if self._prompt_path and self._prompt_path.exists():
            return self._prompt_path.read_text(encoding="utf-8")
        return self._fallback_system_prompt()

    def _load_system_prompt(self) -> str:
        return self._get_system_prompt()

    @abstractmethod
    def _fallback_system_prompt(self) -> str:
        """Return fallback system prompt when prompt file is missing."""

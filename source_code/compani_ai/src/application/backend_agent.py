"""Backend SLM agent implementation for Part 2 Stage 1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain.contracts import AgentRole
from domain.ports import LLMProvider, MessageQueuePort, WorkSpacePort
from observability.error_codes import ErrorCode

from .base_agent import BaseSLMAgent, SLMConfig, SLMAgentError

DEFAULT_BACKEND_MODEL = "phi3.5"
DEFAULT_BACKEND_TEMPERATURE = 0.2
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "backend"
_STAGE_PROMPT_FILES: dict[int, str] = {
    1: "stage1_basic.txt",
    2: "stage2_database.txt",
    3: "stage3_validation.txt",
}


@dataclass(frozen=True)
class BackendSLMConfig(SLMConfig):
    """Backend-agent defaults for deterministic API generation."""

    model: str = DEFAULT_BACKEND_MODEL
    temperature: float = DEFAULT_BACKEND_TEMPERATURE
    stage: int = 1


class BackendSLMAgent(BaseSLMAgent):
    """FastAPI code-generation agent."""

    def __init__(
        self,
        llm: LLMProvider,
        workspace: WorkSpacePort,
        queue: MessageQueuePort,
        run_id: str,
        config: BackendSLMConfig | None = None,
    ) -> None:
        resolved_config = config or BackendSLMConfig()
        prompt_path = self._prompt_path_for_stage(resolved_config.stage)
        super().__init__(
            role=AgentRole.BACKEND,
            llm=llm,
            workspace=workspace,
            queue=queue,
            config=resolved_config,
            run_id=run_id,
            agent_id="backend",
            prompt_path=prompt_path,
        )
        self._stage = resolved_config.stage

    @staticmethod
    def _prompt_path_for_stage(stage: int) -> Path:
        file_name = _STAGE_PROMPT_FILES.get(stage)
        if file_name is None:
            raise SLMAgentError(
                ErrorCode.E_SYSTEM_CONFIG,
                f"unsupported backend stage: {stage}",
            )
        return _PROMPT_DIR / file_name

    def _validate_files(self, payload: dict[str, object]) -> None:
        super()._validate_files(payload)
        if self._stage >= 2:
            self._validate_stage2_files(payload)
        if self._stage >= 3:
            self._validate_stage3_files(payload)

    def _validate_stage2_files(self, payload: dict[str, object]) -> None:
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise SLMAgentError(ErrorCode.E_PARSE_SCHEMA, "files field must be a list")

        paths: list[str] = []
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            raw_path = item.get("path")
            if isinstance(raw_path, str):
                paths.append(raw_path.replace("\\", "/").strip("/"))

        has_database = any(path == "database.py" or path.endswith("/database.py") for path in paths)
        has_models = any("/models/" in f"/{path}/" and path.endswith(".py") for path in paths)
        has_env = any(
            path == "alembic/env.py" or path.endswith("/alembic/env.py")
            for path in paths
        )
        has_versions = any(
            "/alembic/versions/" in f"/{path}/" and path.endswith(".py")
            for path in paths
        )

        missing: list[str] = []
        if not has_database:
            missing.append("**/database.py")
        if not has_models:
            missing.append("**/models/**/*.py")
        if not has_env:
            missing.append("**/alembic/env.py")
        if not has_versions:
            missing.append("**/alembic/versions/*.py")

        if missing:
            missing_patterns = ", ".join(missing)
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage2 required files missing: {missing_patterns}",
            )

    def _validate_stage3_files(self, payload: dict[str, object]) -> None:
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise SLMAgentError(ErrorCode.E_PARSE_SCHEMA, "files field must be a list")

        entries: list[tuple[str, str]] = []
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            raw_path = item.get("path")
            raw_content = item.get("content")
            if isinstance(raw_path, str) and isinstance(raw_content, str):
                normalized_path = raw_path.replace("\\", "/").strip("/")
                entries.append((normalized_path, raw_content))

        has_http_exception = any("httpexception" in content.lower() for _, content in entries)
        has_error_response_schema = any(
            "/schemas/" in f"/{path}/"
            and path.endswith(".py")
            and "errorresponse" in content.lower()
            for path, content in entries
        )

        missing: list[str] = []
        if not has_http_exception:
            missing.append("HTTPException usage")
        if not has_error_response_schema:
            missing.append("ErrorResponse schema file in **/schemas/*.py")

        if missing:
            missing_patterns = ", ".join(missing)
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage3 required validation patterns missing: {missing_patterns}",
            )

    def _fallback_system_prompt(self) -> str:
        raise SLMAgentError(
            ErrorCode.E_SYSTEM_CONFIG,
            "missing backend prompt file for configured stage",
        )

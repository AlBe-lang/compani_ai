"""Backend SLM agent implementation for Part 2 Stages 1–5."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING

from domain.contracts import AgentRole
from domain.ports import LLMProvider, MessageQueuePort, WorkSpacePort
from observability.error_codes import ErrorCode

from .base_agent import BaseSLMAgent, SLMConfig, SLMAgentError

if TYPE_CHECKING:
    from application.dna_manager import DNAManager

DEFAULT_BACKEND_MODEL = "phi3.5"
DEFAULT_BACKEND_TEMPERATURE = 0.2
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "backend"
_STAGE_PROMPT_FILES: dict[int, str] = {
    1: "stage1_basic.txt",
    2: "stage2_database.txt",
    3: "stage3_validation.txt",
    4: "stage4_auth.txt",
    5: "stage5_tests.txt",
}
# Specific OAuth2/JWT patterns that appear only in real auth code, not in import paths
_AUTH_KEYWORDS = ("bearer", "oauth2", "jwt")


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
        dna_manager: "DNAManager | None" = None,
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
            dna_manager=dna_manager,
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
        if self._stage >= 4:
            self._validate_stage4_files(payload)
        if self._stage >= 5:
            self._validate_stage5_files(payload)

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

    def _validate_stage4_files(self, payload: dict[str, object]) -> None:
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
                entries.append((raw_path.replace("\\", "/").strip("/"), raw_content))

        has_auth_mechanism = any(
            any(kw in content.lower() for kw in _AUTH_KEYWORDS)
            for _, content in entries
        )
        has_depends_injection = any("depends(" in content.lower() for _, content in entries)

        missing: list[str] = []
        if not has_auth_mechanism:
            missing.append("OAuth2/JWT authentication mechanism (Bearer token / OAuth2PasswordBearer)")
        if not has_depends_injection:
            missing.append("FastAPI Depends() injection for protected routes")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage4 required auth patterns missing: {', '.join(missing)}",
            )

    def _validate_stage5_files(self, payload: dict[str, object]) -> None:
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
                entries.append((raw_path.replace("\\", "/").strip("/"), raw_content))

        # Files whose path indicates a test file
        test_entries = [
            (path, content)
            for path, content in entries
            if "/tests/" in f"/{path}/" or path.split("/")[-1].startswith("test_")
        ]

        # Unit tests must live under a tests/unit/ subdirectory
        unit_entries = [
            (path, content)
            for path, content in test_entries
            if "/tests/unit/" in f"/{path}/"
        ]
        has_unit_tests = any("def test_" in content for _, content in unit_entries)
        has_integration_tests = any(
            "httpx" in content.lower()
            or "asyncclient" in content.lower()
            or "testclient" in content.lower()
            for _, content in test_entries
        )

        missing: list[str] = []
        if not has_unit_tests:
            missing.append("unit test functions (def test_*) in test files")
        if not has_integration_tests:
            missing.append("integration tests using httpx.AsyncClient or TestClient")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage5 required test patterns missing: {', '.join(missing)}",
            )

    def _fallback_system_prompt(self) -> str:
        raise SLMAgentError(
            ErrorCode.E_SYSTEM_CONFIG,
            "missing backend prompt file for configured stage",
        )

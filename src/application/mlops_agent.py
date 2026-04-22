"""MLOps SLM agent implementation for Part 4 Stages 1–4."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain.contracts import AgentRole
from domain.ports import LLMProvider, MessageQueuePort, WorkSpacePort
from observability.error_codes import ErrorCode

from .base_agent import BaseSLMAgent, SLMAgentError, SLMConfig

DEFAULT_MLOPS_MODEL = "llama3.2:3b"
DEFAULT_MLOPS_TEMPERATURE = 0.1
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "mlops"
_STAGE_PROMPT_FILES: dict[int, str] = {
    1: "stage1_dockerfile.txt",
    2: "stage2_compose.txt",
    3: "stage3_cicd.txt",
    4: "stage4_monitoring.txt",
}


@dataclass(frozen=True)
class MLOpsSLMConfig(SLMConfig):
    """MLOps-agent defaults for infrastructure code generation."""

    model: str = DEFAULT_MLOPS_MODEL
    temperature: float = DEFAULT_MLOPS_TEMPERATURE
    stage: int = 1


class MLOpsSLMAgent(BaseSLMAgent):
    """Docker / CI-CD / monitoring code-generation agent."""

    def __init__(
        self,
        llm: LLMProvider,
        workspace: WorkSpacePort,
        queue: MessageQueuePort,
        run_id: str,
        config: MLOpsSLMConfig | None = None,
    ) -> None:
        resolved_config = config or MLOpsSLMConfig()
        prompt_path = self._prompt_path_for_stage(resolved_config.stage)
        super().__init__(
            role=AgentRole.MLOPS,
            llm=llm,
            workspace=workspace,
            queue=queue,
            config=resolved_config,
            run_id=run_id,
            agent_id="mlops",
            prompt_path=prompt_path,
        )
        self._stage = resolved_config.stage

    @staticmethod
    def _prompt_path_for_stage(stage: int) -> Path:
        file_name = _STAGE_PROMPT_FILES.get(stage)
        if file_name is None:
            raise SLMAgentError(
                ErrorCode.E_SYSTEM_CONFIG,
                f"unsupported mlops stage: {stage}",
            )
        return _PROMPT_DIR / file_name

    # ------------------------------------------------------------------
    # Payload normalization — strip MLOps-specific fields before TaskResult
    # ------------------------------------------------------------------

    def _normalize_payload(self, task: object, payload: dict[str, object]) -> dict[str, object]:
        normalized = super()._normalize_payload(task, payload)  # type: ignore[arg-type]
        # env_vars_required and ports_exposed are mlops-specific; already validated
        # in _validate_files — strip them so TaskResult (extra="forbid") accepts the dict
        normalized.pop("env_vars_required", None)
        normalized.pop("ports_exposed", None)
        return normalized

    # ------------------------------------------------------------------
    # Validation chain
    # ------------------------------------------------------------------

    def _validate_files(self, payload: dict[str, object]) -> None:
        super()._validate_files(payload)
        self._validate_mlops_extra_fields(payload)
        if self._stage >= 1:
            self._validate_stage1_files(payload)
        if self._stage >= 2:
            self._validate_stage2_files(payload)
        if self._stage >= 3:
            self._validate_stage3_files(payload)
        if self._stage >= 4:
            self._validate_stage4_files(payload)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_entries(self, payload: dict[str, object]) -> list[tuple[str, str]]:
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
        return entries

    def _validate_mlops_extra_fields(self, payload: dict[str, object]) -> None:
        env_vars = payload.get("env_vars_required")
        if not isinstance(env_vars, list):
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                "env_vars_required field must be a list",
            )
        ports = payload.get("ports_exposed")
        if not isinstance(ports, list):
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                "ports_exposed field must be a list",
            )

    # ------------------------------------------------------------------
    # Stage validators
    # ------------------------------------------------------------------

    def _validate_stage1_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_dockerfile = any(
            p == "Dockerfile" or p.endswith("/Dockerfile") for p in paths
        )
        all_content = " ".join(c for _, c in entries)

        has_from = "from " in all_content.lower()
        has_workdir = "workdir" in all_content.lower()
        has_non_root_user = "user " in all_content.lower()
        has_no_cache = "--no-cache-dir" in all_content
        has_dockerignore = any(
            p == ".dockerignore" or p.endswith("/.dockerignore") for p in paths
        )

        missing: list[str] = []
        if not has_dockerfile:
            missing.append("Dockerfile")
        if not has_from:
            missing.append("FROM instruction in Dockerfile")
        if not has_workdir:
            missing.append("WORKDIR instruction in Dockerfile")
        if not has_non_root_user:
            missing.append("non-root USER instruction in Dockerfile")
        if not has_no_cache:
            missing.append("--no-cache-dir flag in pip install")
        if not has_dockerignore:
            missing.append(".dockerignore file")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage1 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage2_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_compose = any(
            "docker-compose" in p and (p.endswith(".yml") or p.endswith(".yaml"))
            for p in paths
        )
        compose_content = " ".join(
            c for p, c in entries
            if "docker-compose" in p and (p.endswith(".yml") or p.endswith(".yaml"))
        )

        has_services = "services:" in compose_content
        has_healthcheck = "healthcheck:" in compose_content
        has_env_var_ref = "${" in compose_content
        has_restart = "restart:" in compose_content

        missing: list[str] = []
        if not has_compose:
            missing.append("docker-compose.yml")
        if not has_services:
            missing.append("services: section in docker-compose.yml")
        if not has_healthcheck:
            missing.append("healthcheck: in docker-compose.yml")
        if not has_env_var_ref:
            missing.append("environment variables via ${VAR} in docker-compose.yml")
        if not has_restart:
            missing.append("restart: policy in docker-compose.yml")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage2 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage3_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        # Accept GitHub Actions OR GitLab CI
        has_github_actions = any(
            ".github/workflows/" in p and (p.endswith(".yml") or p.endswith(".yaml"))
            for p in paths
        )
        has_gitlab_ci = any(p == ".gitlab-ci.yml" or p.endswith("/.gitlab-ci.yml") for p in paths)
        has_ci_pipeline = has_github_actions or has_gitlab_ci

        ci_content = " ".join(
            c for p, c in entries
            if (
                ".github/workflows/" in p
                or p.endswith(".gitlab-ci.yml")
                or p.endswith("/.gitlab-ci.yml")
            )
        )
        has_lint_job = "lint" in ci_content.lower()
        has_test_job = "test" in ci_content.lower()
        has_pip_cache = "cache" in ci_content.lower()

        has_makefile = any(p == "Makefile" or p.endswith("/Makefile") for p in paths)

        missing: list[str] = []
        if not has_ci_pipeline:
            missing.append("CI pipeline (.github/workflows/*.yml or .gitlab-ci.yml)")
        if not has_lint_job:
            missing.append("lint job/stage in CI pipeline")
        if not has_test_job:
            missing.append("test job/stage in CI pipeline")
        if not has_pip_cache:
            missing.append("pip cache configuration in CI pipeline")
        if not has_makefile:
            missing.append("Makefile")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage3 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage4_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_prometheus = any(
            "prometheus" in p and (p.endswith(".yml") or p.endswith(".yaml"))
            for p in paths
        )
        prometheus_content = " ".join(
            c for p, c in entries
            if "prometheus" in p and (p.endswith(".yml") or p.endswith(".yaml"))
        )
        has_scrape_configs = "scrape_configs" in prometheus_content

        has_env_example = any(
            p == ".env.example" or p.endswith("/.env.example") for p in paths
        )

        has_deploy_script = any(
            (p.endswith(".sh") and ("deploy" in p or "run" in p or "setup" in p))
            for p in paths
        )
        deploy_content = " ".join(
            c for p, c in entries if p.endswith(".sh")
        )
        has_set_e = "set -euo pipefail" in deploy_content or "set -e" in deploy_content
        has_info_prefix = "[info]" in deploy_content.lower() or "[error]" in deploy_content.lower()

        missing: list[str] = []
        if not has_prometheus:
            missing.append("prometheus.yml")
        if not has_scrape_configs:
            missing.append("scrape_configs in prometheus.yml")
        if not has_env_example:
            missing.append(".env.example")
        if not has_deploy_script:
            missing.append("deployment shell script (deploy/*.sh)")
        if not has_set_e:
            missing.append("set -euo pipefail in deployment script")
        if not has_info_prefix:
            missing.append("[INFO]/[ERROR] prefixed echo messages in deployment script")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage4 required patterns missing: {', '.join(missing)}",
            )

    def _fallback_system_prompt(self) -> str:
        raise SLMAgentError(
            ErrorCode.E_SYSTEM_CONFIG,
            "missing mlops prompt file for configured stage",
        )

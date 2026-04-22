"""Frontend SLM agent implementation for Part 3 Stages 1–6."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain.contracts import AgentRole
from domain.ports import LLMProvider, MessageQueuePort, WorkSpacePort
from observability.error_codes import ErrorCode

from .base_agent import BaseSLMAgent, SLMAgentError, SLMConfig

DEFAULT_FRONTEND_MODEL = "phi3.5"
DEFAULT_FRONTEND_TEMPERATURE = 0.2
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts" / "frontend"
_STAGE_PROMPT_FILES: dict[int, str] = {
    1: "stage1_react_basic.txt",
    2: "stage2_react_hooks.txt",
    3: "stage3_react_api.txt",
    4: "stage4_flutter_basic.txt",
    5: "stage5_flutter_state.txt",
    6: "stage6_tests.txt",
}
_REACT_STAGES = {1, 2, 3}
_FLUTTER_STAGES = {4, 5}
_TEST_STAGES = {6}


@dataclass(frozen=True)
class FrontendSLMConfig(SLMConfig):
    """Frontend-agent defaults for UI code generation."""

    model: str = DEFAULT_FRONTEND_MODEL
    temperature: float = DEFAULT_FRONTEND_TEMPERATURE
    stage: int = 1


class FrontendSLMAgent(BaseSLMAgent):
    """React / Flutter code-generation agent."""

    def __init__(
        self,
        llm: LLMProvider,
        workspace: WorkSpacePort,
        queue: MessageQueuePort,
        run_id: str,
        config: FrontendSLMConfig | None = None,
    ) -> None:
        resolved_config = config or FrontendSLMConfig()
        prompt_path = self._prompt_path_for_stage(resolved_config.stage)
        super().__init__(
            role=AgentRole.FRONTEND,
            llm=llm,
            workspace=workspace,
            queue=queue,
            config=resolved_config,
            run_id=run_id,
            agent_id="frontend",
            prompt_path=prompt_path,
        )
        self._stage = resolved_config.stage

    @staticmethod
    def _prompt_path_for_stage(stage: int) -> Path:
        file_name = _STAGE_PROMPT_FILES.get(stage)
        if file_name is None:
            raise SLMAgentError(
                ErrorCode.E_SYSTEM_CONFIG,
                f"unsupported frontend stage: {stage}",
            )
        return _PROMPT_DIR / file_name

    def _validate_files(self, payload: dict[str, object]) -> None:
        super()._validate_files(payload)
        self._validate_framework_field(payload)
        # React track (stages 1-3): cumulative
        if self._stage in _REACT_STAGES and self._stage >= 1:
            self._validate_stage1_files(payload)
        if self._stage in _REACT_STAGES and self._stage >= 2:
            self._validate_stage2_files(payload)
        if self._stage in _REACT_STAGES and self._stage >= 3:
            self._validate_stage3_files(payload)
        # Flutter track (stages 4-5): cumulative within Flutter
        if self._stage in _FLUTTER_STAGES:
            self._validate_stage4_files(payload)
        if self._stage in _FLUTTER_STAGES and self._stage >= 5:
            self._validate_stage5_files(payload)
        # Test stage (stage 6): validates both React and Flutter tests only
        if self._stage in _TEST_STAGES:
            self._validate_stage6_files(payload)

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

    def _validate_framework_field(self, payload: dict[str, object]) -> None:
        framework = payload.get("framework")
        if not isinstance(framework, str) or framework not in ("react", "flutter"):
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                "framework field must be 'react' or 'flutter'",
            )
        # React-only stages must declare react; Flutter-only stages must declare flutter
        # Test stage (6) accepts either since it tests both frameworks
        if self._stage in _REACT_STAGES and framework != "react":
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage{self._stage} expects framework='react', got '{framework}'",
            )
        if self._stage in _FLUTTER_STAGES and framework != "flutter":
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage{self._stage} expects framework='flutter', got '{framework}'",
            )

    # ------------------------------------------------------------------
    # Stage validators
    # ------------------------------------------------------------------

    def _validate_stage1_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_tsx = any(p.endswith(".tsx") for p in paths)
        has_component = any(
            "/components/" in f"/{p}/" and p.endswith(".tsx") for p in paths
        )
        has_props_interface = any(
            "interface" in c and "props" in c.lower() for _, c in entries
        )
        has_functional_component = any(
            "const " in c and "=>" in c and ("jsx" in c.lower() or "tsx" in c.lower() or "return (" in c)
            for _, c in entries
            if any(p.endswith(".tsx") for p in paths)
        )
        # Simpler check: any tsx file with a function/const component syntax
        has_functional_component = any(
            ("const " in c and "=>" in c) or "function " in c
            for p, c in entries
            if p.endswith(".tsx")
        )
        has_package_json = any(p.endswith("package.json") for p in paths)
        has_tsconfig = any("tsconfig" in p and p.endswith(".json") for p in paths)

        missing: list[str] = []
        if not has_tsx:
            missing.append(".tsx component file(s)")
        if not has_component:
            missing.append("component file under frontend/src/components/")
        if not has_props_interface:
            missing.append("TypeScript Props interface (interface ...Props)")
        if not has_functional_component:
            missing.append("functional component (const Foo = () => ... or function Foo)")
        if not has_package_json:
            missing.append("package.json")
        if not has_tsconfig:
            missing.append("tsconfig.json")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage1 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage2_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_usestate = any("usestate" in c.lower() for _, c in entries)
        has_useeffect = any("useeffect" in c.lower() for _, c in entries)
        has_custom_hook = any(
            "/hooks/" in f"/{p}/" and p.endswith(".ts") for p in paths
        )

        missing: list[str] = []
        if not has_usestate:
            missing.append("useState hook usage")
        if not has_useeffect:
            missing.append("useEffect hook usage")
        if not has_custom_hook:
            missing.append("custom hook file in frontend/src/hooks/*.ts")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage2 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage3_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_api_module = any(
            "/api/" in f"/{p}/" and p.endswith(".ts") for p in paths
        )
        has_try_catch = any("try" in c and "catch" in c for _, c in entries)
        has_env_var = any(
            "process.env" in c or "import.meta.env" in c for _, c in entries
        )
        has_loading_state = any("isloading" in c.lower() or "loading" in c.lower() for _, c in entries)
        has_error_state = any(
            "error" in c.lower() for _, c in entries
            if any(p.endswith(".tsx") for p in paths)
        )

        raw_endpoints = payload.get("api_endpoints_used")
        has_api_endpoints_used = (
            isinstance(raw_endpoints, list) and len(raw_endpoints) > 0
        )

        missing: list[str] = []
        if not has_api_module:
            missing.append("API module in frontend/src/api/*.ts")
        if not has_try_catch:
            missing.append("try/catch error handling in API calls")
        if not has_env_var:
            missing.append("environment variable for API URL (process.env or import.meta.env)")
        if not has_loading_state:
            missing.append("loading state (isLoading or loading variable)")
        if not has_error_state:
            missing.append("error state handling in component")
        if not has_api_endpoints_used:
            missing.append("api_endpoints_used list with at least one endpoint")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage3 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage4_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_dart = any(p.endswith(".dart") for p in paths)
        has_widget_file = any(
            (
                "/widgets/" in f"/{p}/" or "/screens/" in f"/{p}/"
            ) and p.endswith(".dart")
            for p in paths
        )
        has_stateless = any("statelesswidget" in c.lower() for _, c in entries)
        has_const_constructor = any("const " in c for _, c in entries)
        has_pubspec = any("pubspec.yaml" in p for p in paths)
        has_main_dart = any(p.endswith("main.dart") for p in paths)

        missing: list[str] = []
        if not has_dart:
            missing.append(".dart file(s)")
        if not has_widget_file:
            missing.append("widget/screen file under flutter/lib/widgets/ or flutter/lib/screens/")
        if not has_stateless:
            missing.append("StatelessWidget usage")
        if not has_const_constructor:
            missing.append("const constructor usage")
        if not has_pubspec:
            missing.append("pubspec.yaml")
        if not has_main_dart:
            missing.append("main.dart entry point")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage4 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage5_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        has_provider = any(
            "/providers/" in f"/{p}/" and p.endswith(".dart") for p in paths
        )
        has_riverpod = any("riverpod" in c.lower() for _, c in entries)
        has_http_call = any(
            "http" in c.lower() and ("get(" in c.lower() or "post(" in c.lower())
            for _, c in entries
        )
        has_try_catch = any("try" in c and "catch" in c for _, c in entries)

        raw_endpoints = payload.get("api_endpoints_used")
        has_api_endpoints_used = (
            isinstance(raw_endpoints, list) and len(raw_endpoints) > 0
        )

        missing: list[str] = []
        if not has_provider:
            missing.append("Riverpod provider file in flutter/lib/providers/*.dart")
        if not has_riverpod:
            missing.append("Riverpod usage (flutter_riverpod)")
        if not has_http_call:
            missing.append("http GET or POST call")
        if not has_try_catch:
            missing.append("try/catch error handling in http calls")
        if not has_api_endpoints_used:
            missing.append("api_endpoints_used list with at least one endpoint")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage5 required patterns missing: {', '.join(missing)}",
            )

    def _validate_stage6_files(self, payload: dict[str, object]) -> None:
        entries = self._extract_entries(payload)
        paths = [p for p, _ in entries]

        # React tests: .test.tsx / .test.ts or test_ prefix, under frontend
        react_test_entries = [
            (p, c) for p, c in entries
            if (
                p.endswith(".test.tsx")
                or p.endswith(".test.ts")
                or p.split("/")[-1].startswith("test_")
            ) and "flutter" not in p
        ]
        has_react_tests = any(
            "test(" in c.lower() or "it(" in c.lower() or "describe(" in c.lower()
            for _, c in react_test_entries
        )
        has_testing_library = any(
            "@testing-library" in c or "render(" in c or "renderHook" in c
            for _, c in react_test_entries
        )

        # Flutter tests: _test.dart files under flutter/test/
        flutter_test_entries = [
            (p, c) for p, c in entries
            if p.endswith("_test.dart")
        ]
        has_flutter_tests = any(
            "testwidgets(" in c.lower() or "test(" in c.lower()
            for _, c in flutter_test_entries
        )
        has_test_widgets = any(
            "testwidgets(" in c.lower() for _, c in flutter_test_entries
        )

        missing: list[str] = []
        if not has_react_tests:
            missing.append("React test functions (test() or it() or describe())")
        if not has_testing_library:
            missing.append("@testing-library/react usage (render or renderHook)")
        if not has_flutter_tests:
            missing.append("Flutter test file (*_test.dart)")
        if not has_test_widgets:
            missing.append("testWidgets() call in Flutter test")

        if missing:
            raise SLMAgentError(
                ErrorCode.E_PARSE_SCHEMA,
                f"stage6 required test patterns missing: {', '.join(missing)}",
            )

    def _normalize_payload(self, task: object, payload: dict[str, object]) -> dict[str, object]:
        normalized = super()._normalize_payload(task, payload)  # type: ignore[arg-type]
        # framework and api_endpoints_used are frontend-specific; already validated
        # in _validate_files — strip them so TaskResult (extra="forbid") accepts the dict
        normalized.pop("framework", None)
        normalized.pop("api_endpoints_used", None)
        return normalized

    def _fallback_system_prompt(self) -> str:
        raise SLMAgentError(
            ErrorCode.E_SYSTEM_CONFIG,
            "missing frontend prompt file for configured stage",
        )

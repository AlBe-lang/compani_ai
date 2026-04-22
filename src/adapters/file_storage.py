"""File output adapter — writes TaskResult files to disk and generates README."""

from __future__ import annotations

import re
from pathlib import Path

from domain.contracts import Strategy, TaskResult


def _slugify(name: str) -> str:
    return re.sub(r"[^\w-]", "-", name.lower()).strip("-")


class FileStorage:
    """Persist agent-generated files and generate a project README."""

    def save_result_files(
        self,
        project_name: str,
        results: list[TaskResult],
        output_dir: Path,
    ) -> Path:
        """Save files from successful task results into <output_dir>/<project_slug>/."""
        project_dir = output_dir / _slugify(project_name)
        for result in results:
            if not result.success:
                continue
            for file_info in result.files:
                dest = project_dir / file_info.path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(file_info.content, encoding="utf-8")
        return project_dir

    def generate_readme(
        self,
        project_name: str,
        strategy: Strategy,
        results: list[TaskResult],
    ) -> str:
        """Build a README.md string from strategy metadata and task results."""
        lines: list[str] = [
            f"# {project_name}",
            "",
            strategy.description,
            "",
        ]

        if strategy.tech_stack:
            lines += ["## Tech Stack", ""]
            for tech in strategy.tech_stack:
                lines.append(f"- {tech}")
            lines.append("")

        if strategy.constraints:
            lines += ["## Constraints", ""]
            for constraint in strategy.constraints:
                lines.append(f"- {constraint}")
            lines.append("")

        generated = [
            f"- `{fi.path}` ({fi.type})"
            for r in results
            if r.success
            for fi in r.files
        ]
        if generated:
            lines += ["## Generated Files", ""]
            lines.extend(generated)
            lines.append("")

        setup_cmds = [cmd for r in results for cmd in r.setup_commands]
        if setup_cmds:
            lines += ["## Setup", "", "```bash"]
            lines.extend(setup_cmds)
            lines += ["```", ""]

        return "\n".join(lines)

    def write_readme(
        self,
        project_name: str,
        strategy: Strategy,
        results: list[TaskResult],
        output_dir: Path,
    ) -> Path:
        """Write README.md to the project output directory and return its path."""
        project_dir = output_dir / _slugify(project_name)
        project_dir.mkdir(parents=True, exist_ok=True)
        readme_path = project_dir / "README.md"
        readme_path.write_text(
            self.generate_readme(project_name, strategy, results),
            encoding="utf-8",
        )
        return readme_path

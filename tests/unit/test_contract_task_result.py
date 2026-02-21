from __future__ import annotations

from domain.contracts import FileInfo, TaskResult


def test_task_result_serialization_roundtrip() -> None:
    result = TaskResult(
        task_id="task-1",
        agent_id="backend",
        approach="generate CRUD API",
        code="def handler(): pass",
        files=[
            FileInfo(
                name="main.py",
                path="app/main.py",
                content="from fastapi import FastAPI",
                type="python",
            )
        ],
        dependencies=["fastapi"],
        setup_commands=["pip install fastapi"],
        success=True,
    )

    restored = TaskResult.model_validate_json(result.model_dump_json())

    assert restored.task_id == "task-1"
    assert restored.files[0].name == "main.py"
    assert restored.dependencies == ["fastapi"]

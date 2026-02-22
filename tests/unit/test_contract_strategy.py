from __future__ import annotations

from domain.contracts import AgentRole, Strategy, Task


def test_strategy_and_task_serialization_roundtrip() -> None:
    strategy = Strategy(
        project_name="Todo",
        description="Build Todo app",
        tech_stack=["FastAPI", "React"],
        constraints=["local-only"],
    )
    task = Task(
        id="task-1",
        title="Build API",
        description="Create CRUD endpoints",
        agent_role=AgentRole.BACKEND,
        dependencies=[],
        priority=1,
    )

    restored_strategy = Strategy.model_validate_json(strategy.model_dump_json())
    restored_task = Task.model_validate_json(task.model_dump_json())

    assert restored_strategy.project_name == "Todo"
    assert restored_strategy.tech_stack == ["FastAPI", "React"]
    assert restored_task.agent_role is AgentRole.BACKEND
    assert restored_task.priority == 1

from __future__ import annotations

from observability.ids import generate_message_id, generate_run_id, generate_task_id


def test_id_generators_prefix_and_uniqueness() -> None:
    runs = {generate_run_id() for _ in range(100)}
    tasks = {generate_task_id() for _ in range(100)}
    messages = {generate_message_id() for _ in range(100)}

    assert len(runs) == 100
    assert len(tasks) == 100
    assert len(messages) == 100
    assert all(run_id.startswith("run_") for run_id in runs)
    assert all(task_id.startswith("task_") for task_id in tasks)
    assert all(message_id.startswith("msg_") for message_id in messages)

"""Unit tests for MetricsCollector."""

from __future__ import annotations

from observability.metrics import MetricsCollector


def test_record_and_summary_single_success() -> None:
    mc = MetricsCollector()
    mc.record_task("run1", "task_a", "backend", success=True, duration_sec=5.0)
    summary = mc.get_run_summary("run1")
    assert summary.total_tasks == 1
    assert summary.success_count == 1
    assert summary.fail_count == 0
    assert summary.avg_duration_sec == 5.0


def test_summary_mixed_results() -> None:
    mc = MetricsCollector()
    mc.record_task("run2", "task_a", "backend", success=True, duration_sec=4.0)
    mc.record_task("run2", "task_b", "frontend", success=False, duration_sec=2.0, retries=3)
    summary = mc.get_run_summary("run2")
    assert summary.total_tasks == 2
    assert summary.success_count == 1
    assert summary.fail_count == 1
    assert summary.avg_duration_sec == 3.0
    assert summary.total_retries == 3


def test_summary_empty_run() -> None:
    mc = MetricsCollector()
    summary = mc.get_run_summary("nonexistent")
    assert summary.total_tasks == 0
    assert summary.avg_duration_sec == 0.0


def test_metrics_isolated_per_run() -> None:
    mc = MetricsCollector()
    mc.record_task("run_a", "task_1", "backend", success=True, duration_sec=1.0)
    mc.record_task("run_b", "task_1", "backend", success=False, duration_sec=2.0)
    assert mc.get_run_summary("run_a").success_count == 1
    assert mc.get_run_summary("run_b").success_count == 0

"""Rich Live CLI dashboard for monitoring pipeline execution."""

from __future__ import annotations

import importlib
import importlib.util
import time
from collections.abc import Coroutine
from typing import Any, TypeVar

from domain.ports import EventBusPort, EventPayload

T = TypeVar("T")

_rich_available = importlib.util.find_spec("rich") is not None


def _import_rich() -> tuple[Any, Any, Any, Any]:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table

    return Console, Live, Panel, Table


class CLIDashboard:
    """Real-time pipeline dashboard powered by Rich Live.

    Subscribes to workspace events from EventBus and renders a task-status table
    on stdout while structured logs continue to flow to stderr.
    """

    _STATUS_STYLE: dict[str, str] = {
        "planned": "dim",
        "waiting": "yellow",
        "in_progress": "cyan",
        "done": "green",
        "failed": "red",
        "blocked": "red",
    }

    def __init__(self, run_id: str, event_bus: EventBusPort) -> None:
        self._run_id = run_id
        self._tasks: dict[str, dict[str, str]] = {}
        self._start_time = time.monotonic()
        self._live: Any = None
        event_bus.subscribe("work_item.updated", self._on_work_item_updated)

    def _on_work_item_updated(self, _event_type: str, payload: EventPayload) -> None:
        item_id = str(payload.get("item_id", ""))
        curr_status = str(payload.get("curr_status", ""))
        if item_id:
            entry = self._tasks.setdefault(item_id, {"status": curr_status, "item_id": item_id})
            entry["status"] = curr_status
        if self._live is not None:
            self._live.update(self._render())

    def _render(self) -> Any:
        if not _rich_available:
            return None
        _Console, _Live, Panel, Table = _import_rich()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Work Item", style="dim", no_wrap=True)
        table.add_column("Status")

        for item_id, data in self._tasks.items():
            status = data.get("status", "")
            style = self._STATUS_STYLE.get(status, "")
            table.add_row(item_id, f"[{style}]{status}[/{style}]" if style else status)

        elapsed = round(time.monotonic() - self._start_time, 1)
        return Panel(
            table,
            title=f"[bold]compani_ai[/bold] run=[cyan]{self._run_id}[/cyan] ({elapsed}s)",
            border_style="blue",
        )

    async def __aenter__(self) -> "CLIDashboard":
        if _rich_available:
            _Console, Live, _Panel, _Table = _import_rich()
            console = _Console(stderr=False)
            self._live = Live(
                self._render(),
                console=console,
                refresh_per_second=4,
                transient=False,
            )
            self._live.start(refresh=True)
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    async def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Execute a coroutine while displaying the live dashboard."""
        async with self:
            return await coro

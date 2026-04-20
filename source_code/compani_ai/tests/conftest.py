from __future__ import annotations

from pathlib import Path

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider(response='{"ok": true}')


@pytest.fixture
def mock_workspace() -> MockWorkSpace:
    return MockWorkSpace()


@pytest.fixture
def mock_queue() -> MockMessageQueue:
    return MockMessageQueue()


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "workspace.db"


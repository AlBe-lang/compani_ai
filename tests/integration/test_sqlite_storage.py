from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from adapters.errors import AdapterError
from adapters.sqlite_storage import SQLiteStorage
from observability.error_codes import ErrorCode


@pytest.fixture
async def storage() -> AsyncGenerator[SQLiteStorage, None]:
    s = SQLiteStorage(":memory:")
    await s.init()
    yield s
    await s.close()


async def test_save_and_load_round_trip(storage: SQLiteStorage) -> None:
    await storage.save("k1", {"name": "alice", "age": 30})
    result = await storage.load("k1")
    assert result == {"name": "alice", "age": 30}


async def test_load_missing_key_returns_none(storage: SQLiteStorage) -> None:
    result = await storage.load("nonexistent")
    assert result is None


async def test_save_duplicate_key_overwrites(storage: SQLiteStorage) -> None:
    await storage.save("k1", {"v": 1})
    await storage.save("k1", {"v": 2})
    result = await storage.load("k1")
    assert result == {"v": 2}


async def test_update_overwrites_existing(storage: SQLiteStorage) -> None:
    await storage.save("k1", {"status": "PLANNED"})
    await storage.update("k1", {"status": "IN_PROGRESS"})
    result = await storage.load("k1")
    assert result == {"status": "IN_PROGRESS"}


async def test_query_no_filters_returns_all(storage: SQLiteStorage) -> None:
    await storage.save("a", {"role": "backend"})
    await storage.save("b", {"role": "frontend"})
    results = await storage.query()
    assert len(results) == 2


async def test_query_single_filter(storage: SQLiteStorage) -> None:
    await storage.save("a", {"role": "backend", "status": "DONE"})
    await storage.save("b", {"role": "frontend", "status": "DONE"})
    await storage.save("c", {"role": "backend", "status": "PLANNED"})
    results = await storage.query(role="backend")
    assert len(results) == 2
    assert all(r["role"] == "backend" for r in results)


async def test_query_multiple_filters(storage: SQLiteStorage) -> None:
    await storage.save("a", {"role": "backend", "status": "DONE"})
    await storage.save("b", {"role": "backend", "status": "PLANNED"})
    await storage.save("c", {"role": "frontend", "status": "DONE"})
    results = await storage.query(role="backend", status="DONE")
    assert len(results) == 1
    assert results[0]["role"] == "backend"
    assert results[0]["status"] == "DONE"


async def test_query_no_match_returns_empty(storage: SQLiteStorage) -> None:
    await storage.save("a", {"role": "backend"})
    results = await storage.query(role="mlops")
    assert results == []


async def test_not_initialized_raises_adapter_error() -> None:
    s = SQLiteStorage(":memory:")
    with pytest.raises(AdapterError) as exc_info:
        await s.load("key")
    assert exc_info.value.code is ErrorCode.E_STORAGE_READ

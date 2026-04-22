"""Unit tests for RedisCache adapter."""

from __future__ import annotations

import pytest

from adapters.redis_cache import RedisCache, _MIN_TTL_SEC
from adapters.sqlite_storage import SQLiteStorage


@pytest.fixture
async def storage() -> SQLiteStorage:
    s = SQLiteStorage(":memory:")
    await s.init()
    return s


@pytest.fixture
async def cache(storage: SQLiteStorage) -> RedisCache:
    c = RedisCache(redis_url="redis://localhost:6379", fallback=storage)
    await c.connect()  # Redis is not running in unit tests — falls back to SQLite
    return c


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_default_ttl_below_minimum_raises(storage: SQLiteStorage) -> None:
    with pytest.raises(ValueError, match="TTL must be at least"):
        RedisCache(redis_url="redis://localhost:6379", fallback=storage, default_ttl=100)


def test_default_ttl_at_minimum_is_accepted(storage: SQLiteStorage) -> None:
    c = RedisCache(redis_url="redis://localhost:6379", fallback=storage, default_ttl=_MIN_TTL_SEC)
    assert c is not None


# ------------------------------------------------------------------
# Graceful degradation — Redis not running → falls back to SQLite
# ------------------------------------------------------------------


async def test_connect_does_not_raise_when_redis_unavailable(storage: SQLiteStorage) -> None:
    c = RedisCache(redis_url="redis://localhost:9999", fallback=storage)
    await c.connect()  # must not raise
    assert c.is_redis_active is False


async def test_set_uses_fallback_when_redis_unavailable(cache: RedisCache) -> None:
    await cache.set("test_key", {"value": 42})
    result = await cache.get("test_key")
    assert result is not None
    assert result["value"] == 42  # type: ignore[index]


async def test_get_returns_none_for_missing_key(cache: RedisCache) -> None:
    result = await cache.get("nonexistent_key")
    assert result is None


async def test_set_and_get_string_value(cache: RedisCache) -> None:
    await cache.set("str_key", "hello")
    result = await cache.get("str_key")
    assert result == "hello"


async def test_set_enforces_minimum_ttl(cache: RedisCache, storage: SQLiteStorage) -> None:
    with pytest.raises(ValueError, match="TTL must be"):
        await cache.set("k", {"x": 1}, ttl=1800)


async def test_delete_does_not_raise_when_unavailable(cache: RedisCache) -> None:
    await cache.set("del_key", "to be deleted")
    await cache.delete("del_key")  # must not raise


async def test_close_is_idempotent(cache: RedisCache) -> None:
    await cache.close()
    await cache.close()  # second call must not raise


# ------------------------------------------------------------------
# is_redis_active property
# ------------------------------------------------------------------


async def test_is_redis_active_false_when_server_not_running(storage: SQLiteStorage) -> None:
    c = RedisCache(redis_url="redis://127.0.0.1:9999", fallback=storage)
    await c.connect()
    assert c.is_redis_active is False

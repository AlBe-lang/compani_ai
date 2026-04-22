"""Redis cache adapter with SQLite fallback.

All keys must be stored with a TTL (minimum 3600s per infrastructure rules).
When Redis is unavailable at startup or during operation, all operations
transparently fall back to the SQLite StoragePort.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from domain.ports import StorageValue
from observability.error_codes import ErrorCode
from observability.logger import get_logger

if TYPE_CHECKING:
    from domain.ports import StoragePort

log = get_logger(__name__)

# Minimum TTL enforced by infrastructure rules (I-08)
_MIN_TTL_SEC = 3600
_DEFAULT_TTL_SEC = 3600

try:
    import redis.asyncio as aioredis  # type: ignore[import-untyped]

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REDIS_AVAILABLE = False


class RedisCache:
    """Cache adapter: Redis primary with automatic SQLite fallback.

    Key naming convention (per 04_INFRASTRUCTURE_RULES.md §5.1):
      work_item:{item_id}       WorkItem status
      agent_status:{agent_id}   Agent current status
      run_metrics:{run_id}      Run metrics snapshot
    """

    def __init__(
        self,
        redis_url: str,
        fallback: "StoragePort",
        default_ttl: int = _DEFAULT_TTL_SEC,
    ) -> None:
        if default_ttl < _MIN_TTL_SEC:
            raise ValueError(
                f"TTL must be at least {_MIN_TTL_SEC}s (got {default_ttl}s) — see I-08"
            )
        self._redis_url = redis_url
        self._fallback = fallback
        self._default_ttl = default_ttl
        self._client: "aioredis.Redis | None" = None  # type: ignore[name-defined]
        self._available = False

    async def connect(self) -> None:
        """Attempt Redis connection; silently degrade to fallback on failure."""
        if not _REDIS_AVAILABLE:
            log.info("redis_cache.no_library", detail="redis package not installed; using fallback")
            self._available = False
            return
        try:
            self._client = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._client.ping()
            self._available = True
            log.info("redis_cache.connected", url=self._redis_url)
        except Exception as exc:
            self._available = False
            log.warning(
                "redis_cache.unavailable",
                url=self._redis_url,
                detail=str(exc),
                fallback="sqlite",
            )

    async def set(self, key: str, value: StorageValue, ttl: int | None = None) -> None:
        """Store value with TTL. Falls back to SQLite on Redis failure."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        if effective_ttl < _MIN_TTL_SEC:
            raise ValueError(f"TTL must be >= {_MIN_TTL_SEC}s — see I-08")

        if self._available and self._client is not None:
            try:
                await self._client.setex(key, effective_ttl, json.dumps(value, default=str))
                log.debug("redis_cache.set", key=key, ttl=effective_ttl)
                return
            except Exception as exc:
                # Mark unavailable so subsequent calls skip Redis without retrying
                self._available = False
                log.warning("redis_cache.set.fallback", key=key, detail=str(exc))

        await self._fallback.save(key, value)

    async def get(self, key: str) -> StorageValue | None:
        """Retrieve value. Falls back to SQLite on Redis miss or failure."""
        if self._available and self._client is not None:
            try:
                raw = await self._client.get(key)
                if raw is not None:
                    log.debug("redis_cache.hit", key=key)
                    return json.loads(raw)  # type: ignore[no-any-return]
                log.debug("redis_cache.miss", key=key)
            except Exception as exc:
                self._available = False
                log.warning("redis_cache.get.fallback", key=key, detail=str(exc))

        return await self._fallback.load(key)

    async def delete(self, key: str) -> None:
        """Remove a key from Redis (best-effort; does not touch SQLite)."""
        if self._available and self._client is not None:
            try:
                await self._client.delete(key)
                log.debug("redis_cache.delete", key=key)
            except Exception as exc:
                log.warning("redis_cache.delete.error", key=key, detail=str(exc))

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._available = False

    @property
    def is_redis_active(self) -> bool:
        """True if Redis is currently reachable."""
        return self._available

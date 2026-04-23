"""SQLite-backed key-value storage adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from domain.ports import StorageValue
from observability.error_codes import ErrorCode

from .errors import AdapterError

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class SQLiteStorage:
    """StoragePort implementation backed by SQLite via aiosqlite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize DB connection and run pending migrations. Must be called once before use."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.commit()
        await self._run_migrations()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # StoragePort interface
    # ------------------------------------------------------------------

    async def save(self, key: str, value: StorageValue) -> None:
        conn = self._require_conn()
        try:
            await conn.execute(
                "INSERT OR REPLACE INTO kv_store (key, value, saved_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, default=str), _now_iso()),
            )
            await conn.commit()
        except Exception as exc:
            raise AdapterError(ErrorCode.E_STORAGE_WRITE, str(exc)) from exc

    async def load(self, key: str) -> StorageValue | None:
        conn = self._require_conn()
        try:
            cursor = await conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
            row = await cursor.fetchone()
        except Exception as exc:
            raise AdapterError(ErrorCode.E_STORAGE_READ, str(exc)) from exc
        if row is None:
            return None
        return json.loads(row[0])  # type: ignore[no-any-return]

    async def update(self, key: str, value: StorageValue) -> None:
        conn = self._require_conn()
        try:
            await conn.execute(
                "UPDATE kv_store SET value = ?, saved_at = ? WHERE key = ?",
                (json.dumps(value, default=str), _now_iso(), key),
            )
            await conn.commit()
        except Exception as exc:
            raise AdapterError(ErrorCode.E_STORAGE_WRITE, str(exc)) from exc

    async def query(self, **filters: object) -> list[StorageValue]:
        conn = self._require_conn()
        try:
            cursor = await conn.execute("SELECT value FROM kv_store")
            rows = await cursor.fetchall()
        except Exception as exc:
            raise AdapterError(ErrorCode.E_STORAGE_QUERY, str(exc)) from exc
        results: list[StorageValue] = []
        for (raw,) in rows:
            data: StorageValue = json.loads(raw)
            if all(data.get(k) == v for k, v in filters.items()):
                results.append(data)
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise AdapterError(
                ErrorCode.E_STORAGE_READ, "SQLiteStorage not initialized — call init() first"
            )
        return self._conn

    async def _run_migrations(self) -> None:
        conn = self._require_conn()
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS _migrations (
                name       TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )"""
        )
        await conn.commit()

        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            cursor = await conn.execute(
                "SELECT 1 FROM _migrations WHERE name = ?", (sql_file.name,)
            )
            if await cursor.fetchone() is not None:
                continue
            for stmt in sql_file.read_text(encoding="utf-8").split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(stmt)
            await conn.execute(
                "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
                (sql_file.name, _now_iso()),
            )
            await conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

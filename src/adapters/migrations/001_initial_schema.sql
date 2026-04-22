CREATE TABLE IF NOT EXISTS kv_store (
    key      TEXT PRIMARY KEY,
    value    TEXT NOT NULL,
    saved_at TEXT NOT NULL DEFAULT (datetime('now'))
);

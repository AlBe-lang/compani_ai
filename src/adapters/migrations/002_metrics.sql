-- Part 6 Stage 1: agent task metrics table for performance analytics
CREATE TABLE IF NOT EXISTS agent_metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    task_id      TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    success      INTEGER NOT NULL CHECK (success IN (0, 1)),
    duration_sec REAL    NOT NULL,
    retries      INTEGER NOT NULL DEFAULT 0,
    trace_id     TEXT    NOT NULL DEFAULT '',
    recorded_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_run_id  ON agent_metrics (run_id);
CREATE INDEX IF NOT EXISTS idx_metrics_agent_id ON agent_metrics (agent_id);

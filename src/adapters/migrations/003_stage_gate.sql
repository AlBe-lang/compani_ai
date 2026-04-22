-- Part 6 Stage 3: stage gate meeting results
CREATE TABLE IF NOT EXISTS stage_gate_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    result      TEXT    NOT NULL,   -- PASS / FAIL / REPLAN / ABORT
    reason      TEXT    NOT NULL DEFAULT '',
    failure_rate REAL   NOT NULL DEFAULT 0.0,
    avg_duration REAL   NOT NULL DEFAULT 0.0,
    total_items INTEGER NOT NULL DEFAULT 0,
    evaluated_at TEXT   NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gate_run_id ON stage_gate_results (run_id);

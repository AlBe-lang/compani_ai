-- Part 6 Stage 3: agent DNA persistence
CREATE TABLE IF NOT EXISTS agent_dna (
    agent_id     TEXT    PRIMARY KEY,
    role         TEXT    NOT NULL,
    expertise    TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    success_rate REAL    NOT NULL DEFAULT 0.0,
    avg_duration REAL    NOT NULL DEFAULT 0.0,
    total_tasks  INTEGER NOT NULL DEFAULT 0,
    genes        TEXT    NOT NULL DEFAULT '{}',   -- JSON object
    updated_at   TEXT    NOT NULL
);

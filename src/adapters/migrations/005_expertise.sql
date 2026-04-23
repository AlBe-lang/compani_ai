-- Part 7 Stage 3: KnowledgeGraph expertise EMA persistence (R-06)
-- Stores per-(role, topic) EMA values so expertise survives process restart.
-- Updates use INSERT OR REPLACE keyed on the composite (role, topic).
CREATE TABLE IF NOT EXISTS kg_expertise (
    role       TEXT    NOT NULL,
    topic      TEXT    NOT NULL,
    ema_value  REAL    NOT NULL,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (role, topic)
);

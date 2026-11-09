-- her_monitor_action_master/storage/schema.sql
-- 事件明细表。每个 Agent 一个 .db 文件，文件里只有这一张表。

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             INTEGER NOT NULL,
    user           TEXT    NOT NULL,
    action         TEXT    NOT NULL,
    flow           INTEGER NOT NULL,
    conn           TEXT    NOT NULL,
    level          TEXT    DEFAULT '',
    input_tokens   INTEGER DEFAULT 0,
    output_tokens  INTEGER DEFAULT 0,
    total_tokens   INTEGER DEFAULT 0,
    cost           REAL    DEFAULT 0.0,
    pid            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
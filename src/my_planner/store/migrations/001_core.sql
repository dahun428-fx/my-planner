-- 001: 대화, 앱 상태, 하루 사용량, 처리한 텔레그램 업데이트
-- 시각은 UTC ISO 8601 문자열, 날짜는 논리적 날짜 YYYY-MM-DD.

CREATE TABLE conversations (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('run', 'chat', 'plan')),
    run_id          INTEGER NULL,
    session_id      TEXT NULL,
    logical_date    TEXT NOT NULL,
    opened_at       TEXT NOT NULL,
    last_message_at TEXT NOT NULL,
    closed_at       TEXT NULL
);

CREATE INDEX idx_conversations_open ON conversations (kind, closed_at, last_message_at);

CREATE TABLE app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE usage_state (
    date               TEXT PRIMARY KEY,
    brain_calls        INTEGER NOT NULL DEFAULT 0,
    proactive_messages INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE telegram_updates (
    update_id   INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL
);

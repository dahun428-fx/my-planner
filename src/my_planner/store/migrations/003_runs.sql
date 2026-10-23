-- 003: 회차 (스펙 5.4). 두 단계 실행: 두뇌 답을 outbound_text에 저장한 뒤 보낸다.
-- 시각은 UTC ISO 8601 문자열.

CREATE TABLE runs (
    id              INTEGER PRIMARY KEY,
    loop            TEXT NOT NULL CHECK (loop IN ('morning_brief', 'evening_checkin', 'review', 'return')),
    cadence         TEXT NOT NULL DEFAULT 'day' CHECK (cadence IN ('day', 'week', 'month', 'quarter', 'year')),
    scheduled_for   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
        ('pending', 'queued', 'running', 'done', 'failed', 'skipped', 'interrupted')),
    skip_reason     TEXT NULL CHECK (skip_reason IS NULL OR skip_reason IN
        ('late', 'merged_into_return', 'paused', 'auth', 'rate_limit', 'daily_cap')),
    attempt         INTEGER NOT NULL DEFAULT 0,   -- 이 회차의 두뇌 실행 횟수(최대 2)
    started_at      TEXT NULL,
    finished_at     TEXT NULL,
    outbound_text   TEXT NULL,
    resent          INTEGER NOT NULL DEFAULT 0,   -- 5분 뒤 전송만 다시 한 번 했는지
    error           TEXT NULL,
    conversation_id INTEGER NULL,
    merged_run_ids  TEXT NOT NULL DEFAULT '[]',   -- JSON 배열
    created_at      TEXT NOT NULL,
    UNIQUE (loop, cadence, scheduled_for),
    CHECK ((status = 'skipped') = (skip_reason IS NOT NULL))
);

CREATE INDEX idx_runs_status ON runs (status, scheduled_for);

-- 002: 할 일, 영역, 변경 기록, 우선순위, 도구 호출 기록 (스펙 5.5)
-- 시각은 UTC ISO 8601 문자열, 날짜는 논리적 날짜 YYYY-MM-DD.

CREATE TABLE tasks (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('draft', 'open', 'done', 'dropped')),
    planned_for  TEXT NULL,
    scheduled_at TEXT NULL,
    parent_id    INTEGER NULL REFERENCES tasks (id),
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    completed_at TEXT NULL,
    deleted_at   TEXT NULL,
    CHECK (completed_at IS NULL OR status = 'done')
);

CREATE INDEX idx_tasks_status ON tasks (status, planned_for);

CREATE TABLE task_areas (
    task_id INTEGER NOT NULL REFERENCES tasks (id),
    area    TEXT NOT NULL CHECK (area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    PRIMARY KEY (task_id, area)
);

CREATE TABLE task_events (
    id           INTEGER PRIMARY KEY,
    task_id      INTEGER NOT NULL REFERENCES tasks (id),
    kind         TEXT NOT NULL CHECK (kind IN
        ('proposed', 'confirmed', 'created', 'updated', 'completed', 'moved', 'dropped', 'reopened')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    at           TEXT NOT NULL
);

CREATE INDEX idx_task_events_task ON task_events (task_id, at);

CREATE TABLE priorities (
    cadence TEXT NOT NULL CHECK (cadence IN ('day', 'week', 'month', 'quarter', 'year')),
    period  TEXT NOT NULL,
    rank    INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 3),
    task_id INTEGER NOT NULL REFERENCES tasks (id),
    PRIMARY KEY (cadence, period, rank),
    UNIQUE (cadence, period, task_id)
);

CREATE TABLE tool_events_log (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NULL,
    conversation_id INTEGER NULL,
    task_id         INTEGER NULL,
    kind            TEXT NOT NULL,
    at              TEXT NOT NULL
);

CREATE INDEX idx_tool_events_log_conv ON tool_events_log (conversation_id, kind);

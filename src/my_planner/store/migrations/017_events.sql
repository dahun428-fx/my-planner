-- 017: 스케줄 (SP9 스펙 5.1, ADR 0015). 시각은 UTC ISO 8601, 날짜는 현지 날짜 YYYY-MM-DD(논리적 날짜가 아니다).
-- 시각 있는 열린 할 일을 일정으로 옮기는 일은 이 SQL이 아니라 Python 훅 `hooks.after_017`이 한다(5.4).
CREATE TABLE events (
    id              INTEGER PRIMARY KEY,
    title           TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 100),
    all_day         INTEGER NOT NULL DEFAULT 0 CHECK (all_day IN (0, 1)),
    start_date      TEXT NOT NULL,              -- 첫 날의 현지 날짜
    start_time      TEXT NULL,                  -- 현지 "HH:MM". all_day = 1이면 NULL
    duration_min    INTEGER NULL CHECK (duration_min BETWEEN 5 AND 1440),
    repeat          TEXT NOT NULL DEFAULT 'none' CHECK (repeat IN ('none', 'daily', 'weekly', 'monthly')),
    weekdays        INTEGER NULL CHECK (weekdays BETWEEN 1 AND 127),  -- weekly만. 월=1, 화=2, … 일=64
    repeat_until    TEXT NULL,                  -- 마지막 날이 될 수 있는 현지 날짜(포함). NULL = 끝없음
    remind_min      INTEGER NULL CHECK (remind_min IN (0, 10, 30, 60, 1440)),  -- NULL = 알림 없음
    area            TEXT NULL CHECK (area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    note            TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 1000),
    origin          TEXT NOT NULL CHECK (origin IN ('user', 'chat', 'migrated')),
    from_task_id    INTEGER NULL REFERENCES tasks (id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    deleted_at      TEXT NULL,
    CHECK ((all_day = 1) = (start_time IS NULL)),
    CHECK ((repeat = 'weekly') = (weekdays IS NOT NULL)),
    CHECK (repeat <> 'none' OR repeat_until IS NULL)
);

CREATE INDEX idx_events_live ON events (deleted_at, start_date);

CREATE TABLE event_skips (
    event_id        INTEGER NOT NULL REFERENCES events (id),
    occurrence_date TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (event_id, occurrence_date)
);

-- 알림을 보냈거나 놓쳤다고 판정한 그날 일정. 같은 날에 두 번 보내지 않는다.
CREATE TABLE event_reminders (
    event_id        INTEGER NOT NULL REFERENCES events (id),
    occurrence_date TEXT NOT NULL,
    remind_at       TEXT NOT NULL,              -- UTC
    outcome         TEXT NOT NULL CHECK (outcome IN ('sent', 'late_sent', 'missed', 'failed', 'skipped')),
    decided_at      TEXT NOT NULL,
    dismissed_at    TEXT NULL,                  -- 오늘 화면에서 "놓친 알림" 줄을 닫았다
    PRIMARY KEY (event_id, occurrence_date)
);

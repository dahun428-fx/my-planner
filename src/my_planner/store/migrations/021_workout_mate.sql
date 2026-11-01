-- 021: 운동메이트 (SP12 스펙 5.1, 6.1, 7.1, 8.1, 10). 날짜는 논리적 날짜 YYYY-MM-DD, 시각은 UTC ISO 8601.
ALTER TABLE conversations ADD COLUMN agent TEXT NOT NULL DEFAULT 'secretary'
    CHECK (agent IN ('secretary', 'mate'));
ALTER TABLE inbound_pending ADD COLUMN agent TEXT NOT NULL DEFAULT 'secretary'
    CHECK (agent IN ('secretary', 'mate'));

CREATE TABLE body_notes (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('equipment', 'injury', 'preference', 'availability', 'other')),
    text        TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 120),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT NULL
);

CREATE TABLE workout_plans (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 30),
    note         TEXT NULL CHECK (note IS NULL OR length(note) <= 300),
    created_at   TEXT NOT NULL,
    replaced_at  TEXT NULL,          -- 다른 플랜으로 바뀐 시각. NULL이면 지금 플랜
    cleared_at   TEXT NULL           -- "플랜 없이 할래"로 내린 시각(7.2)
);
-- 지금 플랜은 하나뿐
CREATE UNIQUE INDEX idx_workout_plans_current ON workout_plans ((1)) WHERE replaced_at IS NULL AND cleared_at IS NULL;

CREATE TABLE workout_plan_sessions (
    id        INTEGER PRIMARY KEY,
    plan_id   INTEGER NOT NULL REFERENCES workout_plans (id),
    position  INTEGER NOT NULL CHECK (position BETWEEN 1 AND 7),
    label     TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 20),   -- "하체", "가볍게 걷기"
    weekdays  TEXT NULL CHECK (weekdays IS NULL OR json_valid(weekdays)),  -- JSON 정수 배열 0(월)~6(일), 중복 없음. NULL이면 요일 자유
    items     TEXT NOT NULL CHECK (json_valid(items) AND json_array_length(items) BETWEEN 1 AND 12),  -- 7.3
    UNIQUE (plan_id, position)
);

CREATE TABLE workout_logs (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,       -- 논리적 날짜(04:00 경계). 오늘−6 ~ 오늘
    title       TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 30),
    session_id  INTEGER NULL REFERENCES workout_plan_sessions (id),
    effort      INTEGER NULL CHECK (effort BETWEEN 1 AND 5),   -- 힘든 정도. 1 가벼움 ~ 5 아주 힘듦
    note        TEXT NULL CHECK (note IS NULL OR length(note) <= 200),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT NULL
);
CREATE INDEX idx_workout_logs_date ON workout_logs (date) WHERE deleted_at IS NULL;

CREATE TABLE workout_log_items (
    log_id       INTEGER NOT NULL REFERENCES workout_logs (id),
    position     INTEGER NOT NULL CHECK (position BETWEEN 1 AND 20),
    name         TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 30),
    sets         INTEGER NULL CHECK (sets BETWEEN 1 AND 20),
    reps         INTEGER NULL CHECK (reps BETWEEN 1 AND 200),
    weight_kg    REAL NULL CHECK (weight_kg BETWEEN 0 AND 500),
    minutes      INTEGER NULL CHECK (minutes BETWEEN 1 AND 600),
    distance_km  REAL NULL CHECK (distance_km BETWEEN 0 AND 200),
    PRIMARY KEY (log_id, position)
);

-- 경험치 원장의 source_kind CHECK에 'workout_log'를 더한다(스펙 10). 012와 같은 새 표 옮기기.
CREATE TABLE status_xp_ledger_new (
    id           INTEGER PRIMARY KEY,
    at           TEXT NOT NULL,
    logical_date TEXT NOT NULL,
    source_kind  TEXT NOT NULL CHECK (source_kind IN
        ('task_done', 'checkin_reply', 'condition', 'review_week', 'ladder', 'wheel',
         'year_review', 'rest_day', 'secretary', 'habit_check', 'workout_log')),
    source_ref   TEXT NOT NULL,
    amount       INTEGER NOT NULL CHECK (amount > 0),   -- 오르기만 한다(ADR 0006)
    area         TEXT NULL,
    label        TEXT NOT NULL,
    UNIQUE (source_kind, source_ref)
);
INSERT INTO status_xp_ledger_new (id, at, logical_date, source_kind, source_ref, amount, area, label)
    SELECT id, at, logical_date, source_kind, source_ref, amount, area, label FROM status_xp_ledger;
DROP TABLE status_xp_ledger;
ALTER TABLE status_xp_ledger_new RENAME TO status_xp_ledger;
CREATE INDEX idx_xp_date ON status_xp_ledger (logical_date);

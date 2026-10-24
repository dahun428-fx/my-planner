-- 012: 습관과 체크 (SP7 스펙 5.1). 날짜는 논리적 날짜 YYYY-MM-DD, 시각은 UTC ISO 8601.
CREATE TABLE habits (
    id               INTEGER PRIMARY KEY,
    title            TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 40),
    area             TEXT NOT NULL CHECK (area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    kind             TEXT NOT NULL CHECK (kind IN ('daily', 'weekly')),
    target_per_week  INTEGER NULL CHECK (target_per_week BETWEEN 1 AND 6),
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    sort_order       INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT NULL,          -- 되돌린 추가만. 도구로는 쓰지 않는다
    CHECK ((kind = 'daily') = (target_per_week IS NULL))
);

CREATE TABLE habit_checks (
    habit_id    INTEGER NOT NULL REFERENCES habits (id),
    date        TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    PRIMARY KEY (habit_id, date)
);
CREATE INDEX idx_habit_checks_date ON habit_checks (date);

-- 경험치 원장의 source_kind CHECK에 'habit_check'를 더한다(5.6). SQLite는 CHECK를 고칠 수 없어 새 표로 옮긴다.
CREATE TABLE status_xp_ledger_new (
    id           INTEGER PRIMARY KEY,
    at           TEXT NOT NULL,
    logical_date TEXT NOT NULL,
    source_kind  TEXT NOT NULL CHECK (source_kind IN
        ('task_done', 'checkin_reply', 'condition', 'review_week', 'ladder', 'wheel',
         'year_review', 'rest_day', 'secretary', 'habit_check')),
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

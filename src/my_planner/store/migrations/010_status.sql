-- 010: 상태창 원장, 칭호 (SP3-4 스펙 5.5). 원장은 오르기만 한다(amount > 0, UPDATE/DELETE 없음).
CREATE TABLE status_xp_ledger (
    id           INTEGER PRIMARY KEY,
    at           TEXT NOT NULL,
    logical_date TEXT NOT NULL,
    source_kind  TEXT NOT NULL CHECK (source_kind IN
        ('task_done', 'checkin_reply', 'condition', 'review_week', 'ladder', 'wheel',
         'year_review', 'rest_day', 'secretary')),
    source_ref   TEXT NOT NULL,          -- 'task:12', 'run:340', 'date:2026-10-24', 'ladder:2026-10', ...
    amount       INTEGER NOT NULL CHECK (amount > 0),   -- 오르기만 한다(ADR 0006)
    area         TEXT NULL,
    label        TEXT NOT NULL,          -- 상태창 "최근 경험치" 줄: '할 일 완료', '쉬는 날' 등. 제목은 넣지 않는다
    UNIQUE (source_kind, source_ref)
);
CREATE INDEX idx_xp_date ON status_xp_ledger (logical_date);

CREATE TABLE status_titles (
    id           INTEGER PRIMARY KEY,
    milestone_id INTEGER NOT NULL UNIQUE REFERENCES curve_milestones (id),
    granted_at   TEXT NOT NULL
);

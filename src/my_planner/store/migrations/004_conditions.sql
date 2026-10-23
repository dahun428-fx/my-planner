-- 004: 그날 컨디션 (스펙 5.5). 날짜는 논리적 날짜 YYYY-MM-DD, 같은 날 다시 기록하면 덮어쓴다.

CREATE TABLE conditions (
    date        TEXT PRIMARY KEY,
    score       INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    note        TEXT NULL,
    recorded_at TEXT NOT NULL
);

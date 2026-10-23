-- 004: 그날 컨디션 (스펙 5.5). 날짜는 논리적 날짜 YYYY-MM-DD, 같은 날 다시 기록하면 덮어쓴다.

CREATE TABLE conditions (
    date        TEXT PRIMARY KEY CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    score       INTEGER NOT NULL CHECK (score IN (1, 2, 3, 4, 5)),  -- BETWEEN은 3.5(REAL)를 통과시킨다
    note        TEXT NULL,
    recorded_at TEXT NOT NULL
);

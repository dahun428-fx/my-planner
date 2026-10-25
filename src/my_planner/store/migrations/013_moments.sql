-- 013: 이룬 순간 (SP8 스펙 6.1, ADR 0013). 개인 글이라 이 DB에만 둔다(내보내기·로그·원문 기록·활동 summary 없음).
CREATE TABLE status_moments (
    id           INTEGER PRIMARY KEY,
    date         TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),  -- 논리적 날짜
    slot         INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 3),
    text         TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 60),
    area         TEXT NULL CHECK (area IS NULL OR area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    sources_json TEXT NOT NULL DEFAULT '[]',   -- ["task:12", "habit:3", "condition", "chat"]. 글은 넣지 않는다
    hidden_at    TEXT NULL,                    -- 숨김. NULL이면 보인다
    created_at   TEXT NOT NULL,
    UNIQUE (date, slot)
);
CREATE INDEX idx_moments_date ON status_moments (date);

CREATE TABLE status_moment_days (            -- 날마다 정리했는지(중복 방지, 따라잡기)
    date        TEXT PRIMARY KEY,
    state       TEXT NOT NULL CHECK (state IN ('pending', 'done', 'empty', 'failed')),
    saved       INTEGER NOT NULL DEFAULT 0,  -- 처음 저장한 개수. 지워도 그대로(다시 만들지 않는 근거)
    attempts    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

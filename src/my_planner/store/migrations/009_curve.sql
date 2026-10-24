-- 009: 인생 곡선 (SP3-4 스펙 5.4). 초안은 지운다(ON DELETE SET NULL).
CREATE TABLE curve_chapters (
    id          INTEGER PRIMARY KEY,
    seed_key    TEXT NULL UNIQUE,     -- 시드의 챕터 id(예: 'C1'). 시드로 만든 것만
    title       TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 100),
    theme       TEXT NULL,            -- 주제 한 줄
    start_month TEXT NOT NULL CHECK (start_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    end_month   TEXT NULL CHECK (end_month IS NULL OR end_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),  -- NULL = 지금까지
    sketch      TEXT NULL,            -- 과거 그래프의 방향 메모(시드 curve_sketch.direction, 자유 글)
    certainty   TEXT NOT NULL DEFAULT 'fact' CHECK (certainty IN ('fact', 'estimate')),
    status      TEXT NOT NULL CHECK (status IN ('draft', 'confirmed')),
    origin      TEXT NOT NULL CHECK (origin IN ('seed', 'chat', 'review')),
    source_ref  TEXT NULL,            -- 시드의 출처 메모. 화면에는 내보내지 않는다
    draft_since TEXT NULL,            -- 초안 만료 시계의 시작. 초안이면 NOT NULL(제안 시각, 되돌린 시각), 확정하면 NULL로 되돌린다
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK (end_month IS NULL OR end_month >= start_month)
);

CREATE TABLE curve_milestones (
    id             INTEGER PRIMARY KEY,
    chapter_id     INTEGER NULL REFERENCES curve_chapters (id) ON DELETE SET NULL,  -- 챕터 초안을 지우면 NULL
    date_text      TEXT NOT NULL,     -- 'YYYY' | 'YYYY-MM' | 'YYYY-MM-DD' (기억하는 만큼만)
    precision      TEXT NOT NULL CHECK (precision IN ('year', 'month', 'day')),
    sort_date      TEXT NOT NULL,     -- 정렬용: 그 기간의 첫날 YYYY-MM-DD
    kind           TEXT NOT NULL CHECK (kind IN ('high', 'low', 'turning_point')),
    kind_certainty TEXT NOT NULL DEFAULT 'fact' CHECK (kind_certainty IN ('fact', 'estimate')),
    title          TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 100),
    note           TEXT NULL,
    sensitive      INTEGER NOT NULL DEFAULT 0 CHECK (sensitive IN (0, 1)),
    certainty      TEXT NOT NULL DEFAULT 'fact' CHECK (certainty IN ('fact', 'estimate')),
    status         TEXT NOT NULL CHECK (status IN ('draft', 'confirmed')),
    origin         TEXT NOT NULL CHECK (origin IN ('seed', 'chat', 'review')),
    title_label    TEXT NULL,         -- 칭호 이름을 사용자가 고쳤을 때(9.4)
    conversation_id INTEGER NULL,     -- 초안을 꺼낸 대화("전부 저장" 버튼)
    source_ref     TEXT NULL,
    draft_since    TEXT NULL,         -- 초안 만료 시계의 시작(제안 시각, 확정을 되돌린 시각). 확정하면 NULL
    created_at     TEXT NOT NULL,
    confirmed_at   TEXT NULL,
    updated_at     TEXT NOT NULL,
    CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL))
);
CREATE INDEX idx_milestones_sort ON curve_milestones (status, sort_date);

CREATE TABLE curve_ladder_scores (
    period      TEXT PRIMARY KEY CHECK (period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),  -- 달
    now         INTEGER NULL CHECK (now IS NULL OR now IN (0,1,2,3,4,5,6,7,8,9,10)),
    future      INTEGER NULL CHECK (future IS NULL OR future IN (0,1,2,3,4,5,6,7,8,9,10)),  -- 5년 뒤
    note        TEXT NULL,
    recorded_at TEXT NOT NULL,
    CHECK (now IS NOT NULL OR future IS NOT NULL)   -- 5년 뒤만 먼저 답해도 된다
);

CREATE TABLE curve_area_scores (
    period         TEXT NOT NULL CHECK (period GLOB '[0-9][0-9][0-9][0-9]-Q[1-4]'),  -- 분기
    area           TEXT NOT NULL CHECK (area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    score          INTEGER NOT NULL CHECK (score IN (1,2,3,4,5,6,7,8,9,10)),
    note           TEXT NULL,
    recovery_quest TEXT NULL CHECK (recovery_quest IS NULL OR length(recovery_quest) <= 80),  -- 내려갔을 때 제안
    recorded_at    TEXT NOT NULL,
    PRIMARY KEY (period, area)
);

CREATE TABLE curve_area_defaults (           -- 영역별 기본 회복 퀘스트(시드 areas[].quest, 확인한 것만)
    area           TEXT PRIMARY KEY,
    recovery_quest TEXT NOT NULL CHECK (length(recovery_quest) <= 80),
    updated_at     TEXT NOT NULL
);

CREATE TABLE curve_questions (               -- 시드 questions[]: 회고에서 하나씩 묻는다(11.1)
    id          INTEGER PRIMARY KEY,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'asked', 'answered', 'skipped')),
    asked_at    TEXT NULL,
    answered_at TEXT NULL
);

-- 라이프 매니저와 전문가 패널 (SP15 스펙 5.1, 5.4, 7.1, 9.1, 10).
-- `conversations.agent`·`inbound_pending.agent`의 CHECK에 'manager'를 더하는 표 옮기기와 결정 첫 줄은 훅
-- (`hooks.after_024`)이 한다. 표를 새로 만들어 옮기므로 `migrate`가 이 번호 동안 `foreign_keys`를 끈다.

CREATE TABLE owner_statements (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('fact', 'preference', 'decision')),
    area       TEXT CHECK (area IN ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    key        TEXT UNIQUE,              -- decision만: 'career_first' 같은 짧은 키
    text       TEXT NOT NULL CHECK (length(text) <= 200),
    source_ref TEXT,                     -- 'conversation:<id>' 또는 'suggestion:<id>'
    created_at TEXT NOT NULL,
    retired_at TEXT                      -- "그건 이제 아니야"면 채움(지우지 않음)
);

CREATE TABLE panel_suggestions (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations (id),
    kind            TEXT NOT NULL CHECK (kind IN ('task', 'habit')),
    title           TEXT NOT NULL,
    area            TEXT NOT NULL
        CHECK (area IN ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    size_min        INTEGER NOT NULL CHECK (size_min BETWEEN 5 AND 120),  -- 예상 소요(분)
    per_week        INTEGER NULL CHECK (per_week BETWEEN 1 AND 7),         -- 습관이면 주 몇 번(7 = 매일)
    due_hint        TEXT,                -- 'YYYY-MM-DD' 또는 NULL
    experts         TEXT NOT NULL,       -- 'career,finance'
    evidence_json   TEXT NOT NULL,
    week            TEXT NOT NULL,       -- 'YYYY-Www' 나온 주(논리적 날짜)
    state           TEXT NOT NULL
        CHECK (state IN ('proposed', 'accepted', 'done', 'postponed', 'dismissed', 'expired')),
    result_ref      TEXT,                -- 받으면 'task:<id>' / 'habit:<id>'
    dismiss_reason  TEXT CHECK (dismiss_reason IN ('no_time', 'not_interested', 'already', 'too_big', 'none')),
    created_at      TEXT NOT NULL,
    decided_at      TEXT,
    CHECK ((kind = 'habit') = (per_week IS NOT NULL))
);
CREATE INDEX panel_suggestions_week ON panel_suggestions (week);
CREATE INDEX panel_suggestions_area ON panel_suggestions (area, created_at);

CREATE TABLE panel_predictions (
    id              INTEGER PRIMARY KEY,
    metric          TEXT NOT NULL,       -- SP13 지표 또는 'axis:<축>'
    predicted       REAL NOT NULL,
    due             TEXT NOT NULL,       -- 'YYYY-MM-DD'
    made_at         TEXT NOT NULL,
    actual          REAL,
    checked_at      TEXT,
    conversation_id INTEGER NULL REFERENCES conversations (id)  -- 한 대화 2개 상한
);

CREATE TABLE life_reports (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    json       TEXT NOT NULL CHECK (json_valid(json))
);

-- 사건 기록·받은편지함·관찰 (SP14 스펙 5.1). 훅 없음.

CREATE TABLE agent_events (
    id          INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL,           -- UTC ISO
    day         TEXT NOT NULL,           -- 논리적 날짜
    kind        TEXT NOT NULL,           -- 5.2 목록. 코드가 목록 밖 값을 거절
    ref         TEXT NOT NULL,           -- 'task:12', 'event:7', 'memo:3', 'measure:40' …
    area        TEXT,                    -- 알 수 있으면 영역 하나. 메모·일정은 NULL
    origin      TEXT NOT NULL CHECK (origin IN ('app', 'telegram', 'scheduler', 'brain', 'import'))
);
CREATE INDEX agent_events_day ON agent_events (day);

CREATE TABLE agent_inbox (
    agent     TEXT NOT NULL CHECK (agent IN ('mate', 'manager')),
    event_id  INTEGER NOT NULL REFERENCES agent_events (id) ON DELETE CASCADE,
    seen_at   TEXT,                      -- 하루 끝 판단이나 즉시 판단이 읽으면 채움
    PRIMARY KEY (agent, event_id)
);
CREATE INDEX agent_inbox_unseen ON agent_inbox (agent) WHERE seen_at IS NULL;

CREATE TABLE agent_notes (
    id         INTEGER PRIMARY KEY,
    agent      TEXT NOT NULL CHECK (agent IN ('mate', 'manager')),
    day        TEXT NOT NULL,            -- 판단한 논리적 날짜
    text       TEXT NOT NULL CHECK (length(text) <= 120),
    priority   INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 3),
    refs_json  TEXT NOT NULL,            -- 근거 사건·기록 id 목록
    shown_at   TEXT,                     -- 아침 브리핑에 붙은 시각
    created_at TEXT NOT NULL
);

-- 007: 활동 기록, 요청 중복 방지, 확인 대기 (SP3-4 스펙 5.2).
CREATE TABLE activity (
    id                 INTEGER PRIMARY KEY,
    at                 TEXT NOT NULL,
    actor              TEXT NOT NULL CHECK (actor IN ('secretary', 'user')),
    channel            TEXT NOT NULL CHECK (channel IN ('app', 'telegram', 'scheduler')),
    kind               TEXT NOT NULL,          -- 6.4.4 표
    target             TEXT NULL,              -- 'task:12', 'condition:2026-10-24', 'priorities:week:2026-W43',
                                               -- 'ladder:2026-10', 'areas:2026-Q4', 'milestone:7', 'chapter:3', 'card:2'
    summary            TEXT NOT NULL,          -- 확인 문구 한 줄(SP1 부록 A 형식). 메시지 본문은 넣지 않는다
    risk               TEXT NOT NULL CHECK (risk IN ('low', 'confirm')),
    undo_json          TEXT NULL,              -- 되돌릴 때 쓸 이전 값. NULL이면 되돌릴 수 없다
    undone_at          TEXT NULL,
    undone_by          INTEGER NULL REFERENCES activity (id),
    conversation_id    INTEGER NULL,
    run_id             INTEGER NULL,
    inbound_id         INTEGER NULL
);
CREATE INDEX idx_activity_at ON activity (at);
CREATE INDEX idx_activity_target ON activity (target, at);

CREATE TABLE api_idempotency (
    client_msg_id   TEXT PRIMARY KEY,
    endpoint        TEXT NOT NULL CHECK (endpoint IN ('chat', 'actions', 'undo')),
    status_code     INTEGER NOT NULL,
    response_json   TEXT NULL,     -- actions·undo: 응답 JSON. chat: {"conversation_id", "reply_text"(가린 뒤의 답 글, 확인 문구 포함)}
    conversation_id INTEGER NULL,
    at              TEXT NOT NULL
);

CREATE TABLE pending_confirms (            -- 확인을 기다리는 변경(6.4.2 needs_confirm, 10.1 회차 차례의 확인)
    token           TEXT PRIMARY KEY,      -- 'ct_' + secrets.token_urlsafe(16)
    action          TEXT NOT NULL,         -- 6.4.2 표의 action 이름
    args_json       TEXT NOT NULL,
    summary         TEXT NOT NULL,         -- 확인 문구 한 줄
    origin          TEXT NOT NULL CHECK (origin IN ('actions', 'run_turn')),
    run_id          INTEGER NULL,
    conversation_id INTEGER NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,         -- actions: +10분, run_turn: 그 회차 답장 창 끝
    resolved_at     TEXT NULL,
    resolution      TEXT NULL CHECK (resolution IS NULL OR resolution IN ('applied', 'declined', 'expired', 'stale'))
);

-- 006: 통로, 회차 전달, 답한 회차 (SP3-4 스펙 5.1). 기존 행은 모두 telegram이다.
ALTER TABLE conversations ADD COLUMN channel TEXT NOT NULL DEFAULT 'telegram'
    CHECK (channel IN ('telegram', 'app'));
ALTER TABLE conversations ADD COLUMN forked_from INTEGER NULL REFERENCES conversations (id);
CREATE INDEX idx_conversations_channel ON conversations (channel, kind, closed_at, last_message_at);

ALTER TABLE inbound_pending ADD COLUMN channel TEXT NOT NULL DEFAULT 'telegram'
    CHECK (channel IN ('telegram', 'app'));
ALTER TABLE inbound_pending ADD COLUMN client_msg_id TEXT NULL;
ALTER TABLE inbound_pending ADD COLUMN checkin_id INTEGER NULL;      -- 앱이 답한 회차(runs.id)
CREATE UNIQUE INDEX idx_inbound_client_msg ON inbound_pending (client_msg_id)
    WHERE client_msg_id IS NOT NULL;

ALTER TABLE runs ADD COLUMN answered_at  TEXT NULL;
ALTER TABLE runs ADD COLUMN answered_via TEXT NULL CHECK (answered_via IS NULL OR answered_via IN ('telegram', 'app'));

CREATE TABLE run_deliveries (
    run_id              INTEGER NOT NULL REFERENCES runs (id),
    channel             TEXT NOT NULL CHECK (channel IN ('telegram', 'app')),
    mode                TEXT NOT NULL CHECK (mode IN ('full', 'fallback')),  -- fallback: 푸시가 안 돼 텔레그램으로
    status              TEXT NOT NULL CHECK (status IN ('sent', 'not_sent')),
    telegram_message_id INTEGER NULL,   -- 버튼이 붙은 마지막 조각. 답한 뒤 버튼을 거둘 때 쓴다
    push_ok             INTEGER NOT NULL DEFAULT 0,
    push_failed         INTEGER NOT NULL DEFAULT 0,
    at                  TEXT NOT NULL,
    PRIMARY KEY (run_id, channel)
);

-- 020: 사진 (SP10 스펙 5.1). 바이트는 data/photos/ 파일에만, 여기는 연결과 정보만.
CREATE TABLE photos (
    id           INTEGER PRIMARY KEY,
    sha256       TEXT NOT NULL CHECK (length(sha256) = 64),
    path         TEXT NOT NULL UNIQUE,          -- data/photos/ 기준 상대 경로, 예: 2026/10/12-3fa2c1d0.jpg
    thumb_path   TEXT NOT NULL UNIQUE,          -- 예: 2026/10/12-3fa2c1d0-t.jpg
    bytes        INTEGER NOT NULL CHECK (bytes BETWEEN 1 AND 5000000),
    width        INTEGER NOT NULL CHECK (width BETWEEN 1 AND 2048),
    height       INTEGER NOT NULL CHECK (height BETWEEN 1 AND 2048),
    origin       TEXT NOT NULL CHECK (origin IN ('memo', 'chat')),
    read_text    TEXT NULL CHECK (read_text IS NULL OR length(read_text) <= 8000),  -- 마지막 사진 읽기 결과(다시 읽지 않으려고)
    created_at   TEXT NOT NULL,
    unlinked_at  TEXT NULL                      -- 마지막 연결이 끊긴 때(메모에서 빼기). 다시 붙으면 NULL
);

CREATE TABLE memo_photos (
    memo_id     INTEGER NOT NULL REFERENCES memos(id) ON DELETE CASCADE,
    photo_id    INTEGER NOT NULL UNIQUE REFERENCES photos(id) ON DELETE CASCADE,   -- 한 사진은 한 메모에만
    position    INTEGER NOT NULL CHECK (position BETWEEN 0 AND 9),
    PRIMARY KEY (memo_id, photo_id),
    UNIQUE (memo_id, position)
);

CREATE TABLE message_photos (
    inbound_id       INTEGER NOT NULL,          -- 받은 메시지 큐의 행 id(`inbound.id`)
    conversation_id  INTEGER NOT NULL,          -- 앱 메시지는 늘 대화가 있다(`route_app_message`)
    photo_id         INTEGER NOT NULL UNIQUE REFERENCES photos(id) ON DELETE CASCADE,  -- 한 사진은 한 메시지에만
    PRIMARY KEY (inbound_id, photo_id)
);

CREATE INDEX idx_message_photos_conv ON message_photos (conversation_id);

ALTER TABLE usage_state ADD COLUMN photo_reads INTEGER NOT NULL DEFAULT 0;   -- 하루 사진 읽기 수(5.4)

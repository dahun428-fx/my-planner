-- 016: 메모 (SP9 스펙 6.1). Dahun이 쓴 글만. 이룬 순간(SP8)·기억 카드와 서로 참조하지 않는다.
CREATE TABLE memos (
    id          INTEGER PRIMARY KEY,
    body        TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 20000),
    area        TEXT NULL CHECK (area IN
        ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life')),
    pinned_at   TEXT NULL,
    origin      TEXT NOT NULL CHECK (origin IN ('user', 'chat')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT NULL
);

CREATE INDEX idx_memos_list ON memos (deleted_at, pinned_at, updated_at);

CREATE VIRTUAL TABLE memos_fts USING fts5(body, content='memos', content_rowid='id', tokenize='trigram');

-- 삽입·수정·삭제 트리거로 memos_fts를 맞춘다. 색인에는 살아 있는 메모(`deleted_at IS NULL`)만 둔다:
-- 지우면(소프트 삭제) 색인에서 빼고, 되살리면 다시 넣는다. 외부 내용 표라 'delete'에는 색인한 그대로의 본문을 준다.
CREATE TRIGGER memos_ai AFTER INSERT ON memos WHEN new.deleted_at IS NULL BEGIN
    INSERT INTO memos_fts (rowid, body) VALUES (new.id, new.body);
END;

CREATE TRIGGER memos_ad AFTER DELETE ON memos WHEN old.deleted_at IS NULL BEGIN
    INSERT INTO memos_fts (memos_fts, rowid, body) VALUES ('delete', old.id, old.body);
END;

CREATE TRIGGER memos_au AFTER UPDATE OF body, deleted_at ON memos BEGIN
    INSERT INTO memos_fts (memos_fts, rowid, body) SELECT 'delete', old.id, old.body WHERE old.deleted_at IS NULL;
    INSERT INTO memos_fts (rowid, body) SELECT new.id, new.body WHERE new.deleted_at IS NULL;
END;

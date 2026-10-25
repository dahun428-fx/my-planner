-- 018: 대화 제목·요약·지우기 (SP9 스펙 7.1, ADR 0014)
ALTER TABLE conversations ADD COLUMN title TEXT NULL;               -- 20자 이하
ALTER TABLE conversations ADD COLUMN summary TEXT NULL;             -- 600자 이하. 짧은 대화(두뇌 없이 제목만)는 ''
ALTER TABLE conversations ADD COLUMN summary_through TEXT NULL;     -- 요약이 덮는 마지막 줄의 시각
ALTER TABLE conversations ADD COLUMN user_messages INTEGER NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN deleted_at TEXT NULL;
-- 지난 대화를 골라 새로 연 `chat`(고른 것이 계획 대화이거나 답장 창이 지난 회차 대화, 7.3): 새 세션 앞머리에 그 대화의
-- 요약을 붙인다. 스펙 7.1 표에 없는 칸이다(티켓 SP9-09 결정: 받을 때 고른 뒤 처리할 때까지 DB에 남겨 재시작을 넘긴다)
ALTER TABLE conversations ADD COLUMN continued_from INTEGER NULL REFERENCES conversations (id);
-- 앱 메시지가 실은 `resume_conversation_id`(0번 규칙, 7.3): 재시작 뒤 다시 넣을 때도 같은 대화로 고른다(SP9-09 리뷰)
ALTER TABLE inbound_pending ADD COLUMN resume_conversation_id INTEGER NULL;
-- 하루 요약 호출 수(`limits.daily_summaries`, 7.2). `brain_calls`에도 센다
ALTER TABLE usage_state ADD COLUMN summaries INTEGER NOT NULL DEFAULT 0;

CREATE VIRTUAL TABLE conversations_fts USING fts5(title, summary, content='conversations', content_rowid='id', tokenize='trigram');

-- 색인에는 지우지 않았고 제목이나 요약이 있는 대화만 둔다. 외부 내용 표라 'delete'에는 색인한 그대로의 값을 준다.
CREATE TRIGGER conversations_au AFTER UPDATE OF title, summary, deleted_at ON conversations BEGIN
    INSERT INTO conversations_fts (conversations_fts, rowid, title, summary)
        SELECT 'delete', old.id, old.title, old.summary
        WHERE old.deleted_at IS NULL AND (old.title IS NOT NULL OR old.summary IS NOT NULL);
    INSERT INTO conversations_fts (rowid, title, summary)
        SELECT new.id, new.title, new.summary
        WHERE new.deleted_at IS NULL AND (new.title IS NOT NULL OR new.summary IS NOT NULL);
END;

CREATE TRIGGER conversations_ad AFTER DELETE ON conversations
    WHEN old.deleted_at IS NULL AND (old.title IS NOT NULL OR old.summary IS NOT NULL) BEGIN
    INSERT INTO conversations_fts (conversations_fts, rowid, title, summary)
        VALUES ('delete', old.id, old.title, old.summary);
END;

-- 대화 하나에 생긴 두뇌 세션 id 모두(resume 실패, 가르기, 말아 넣기로 바뀐다). 지우기(7.7)가 전부 지운다.
CREATE TABLE conversation_sessions (
    conversation_id INTEGER NOT NULL REFERENCES conversations (id),
    session_id      TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    PRIMARY KEY (conversation_id, session_id)
);

INSERT INTO conversation_sessions SELECT id, session_id, opened_at FROM conversations WHERE session_id IS NOT NULL;

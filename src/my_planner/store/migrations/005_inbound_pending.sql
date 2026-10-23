-- 005: 받았지만 아직 답하지 못한 사용자 메시지 (최종 리뷰 Important 1, 2차 결정).
-- 텔레그램은 받아 간 업데이트를 다시 주지 않으므로, 디스패처에 넣기 전에 여기에 먼저 쓴다.
-- 처리 완료(telegram_updates)로 기록할 때 지우고, 시작할 때 남은 행을 다시 넣는다.
-- 다시 넣어도 같은 일을 두 번 하지 않는다(회차의 두 단계 실행과 같다, 스펙 5.4-3):
--   user_logged: 사용자 줄을 원문 기록에 썼다 → 다시 쓰지 않는다
--   brain_done/reply_text: 두뇌 답(확인 문구 포함, 가린 뒤)을 보내기 전에 저장했다 → 그 답만 다시 보낸다
--   tool_events_log.inbound_id: 이 메시지 처리 중 도구가 썼다 → 두뇌를 다시 부르지 않는다
--   attempts: 시작 때 다시 넣은 횟수. 3회를 넘으면 버린다
-- 본문은 가린 뒤의 글만 둔다(스펙 5.8: 저장 전에 가린다). 시각은 UTC ISO 8601 문자열.

CREATE TABLE inbound_pending (
    update_id       INTEGER PRIMARY KEY,
    text_redacted   TEXT NOT NULL,
    sent_at         TEXT NOT NULL,   -- 텔레그램이 기록한 보낸 시각(message.date)
    received_at     TEXT NOT NULL,   -- 하네스가 받은 시각
    user_logged     INTEGER NOT NULL DEFAULT 0 CHECK (user_logged IN (0, 1)),
    brain_done      INTEGER NOT NULL DEFAULT 0 CHECK (brain_done IN (0, 1)),
    reply_text      TEXT NULL,
    conversation_id INTEGER NULL,    -- 답이 속한 대화(brain_done일 때)
    attempts        INTEGER NOT NULL DEFAULT 0
);

-- 회차가 run_id로 도구 호출을 잇듯, 사용자 메시지는 inbound_id(묶음의 첫 update_id)로 잇는다.
-- data_json은 확인 문구와 초안 버튼을 다시 만들 ToolEvent 데이터다(제목 등, 로그 파일에는 쓰지 않는다).
ALTER TABLE tool_events_log ADD COLUMN inbound_id INTEGER NULL;
ALTER TABLE tool_events_log ADD COLUMN data_json TEXT NULL;
CREATE INDEX idx_tool_events_log_inbound ON tool_events_log (inbound_id);

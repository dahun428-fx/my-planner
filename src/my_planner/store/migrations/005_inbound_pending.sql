-- 005: 받았지만 아직 답하지 못한 사용자 메시지 (최종 리뷰 Important 1).
-- 텔레그램은 받아 간 업데이트를 다시 주지 않으므로, 디스패처에 넣기 전에 여기에 먼저 쓴다.
-- 처리 완료(telegram_updates)로 기록할 때 지우고, 시작할 때 남은 행을 다시 넣는다.
-- 본문은 가린 뒤의 글만 둔다(스펙 5.8: 저장 전에 가린다). 시각은 UTC ISO 8601 문자열.

CREATE TABLE inbound_pending (
    update_id     INTEGER PRIMARY KEY,
    text_redacted TEXT NOT NULL,
    sent_at       TEXT NOT NULL,   -- 텔레그램이 기록한 보낸 시각(message.date)
    received_at   TEXT NOT NULL    -- 하네스가 받은 시각
);

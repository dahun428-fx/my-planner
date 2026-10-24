-- 008: 푸시 구독, 고정 카드 (SP3-4 스펙 5.3). 주 통로는 app_state.notify_primary.
CREATE TABLE push_subscriptions (
    id              INTEGER PRIMARY KEY,
    endpoint        TEXT NOT NULL UNIQUE,   -- 비밀값처럼 다룬다: 로그에 남기지 않는다
    p256dh          TEXT NOT NULL,
    auth            TEXT NOT NULL,
    label           TEXT NULL,              -- 사용자가 붙인 기기 이름(예: "폰")
    created_at      TEXT NOT NULL,
    last_success_at TEXT NULL,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    disabled_at     TEXT NULL               -- 404/410을 받았거나 연속 5번 안 됨
);

CREATE TABLE app_cards (
    id              INTEGER PRIMARY KEY,
    component       TEXT NOT NULL,          -- ui 카탈로그의 이름 (6.4.7)
    props_json      TEXT NOT NULL,          -- 카탈로그 스키마로 검증한 값. 할 일은 id로만 가리킨다
    sort_order      INTEGER NOT NULL,
    pinned_at       TEXT NOT NULL,
    unpinned_at     TEXT NULL,
    conversation_id INTEGER NULL
);

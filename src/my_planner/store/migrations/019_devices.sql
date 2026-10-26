-- 019: 연결된 기기와 기기 토큰 (기기 연결 스펙 4.1, ADR 0018). 토큰 원문은 두지 않는다
CREATE TABLE devices (
    id           INTEGER PRIMARY KEY,
    token_hash   TEXT NOT NULL UNIQUE,   -- sha256(토큰) 16진수
    label        TEXT NOT NULL,          -- "iPhone · 앱", "Windows · 대시보드"
    client       TEXT NOT NULL CHECK (client IN ('app', 'dashboard')),
    created_at   TEXT NOT NULL,
    last_used_at TEXT NULL,              -- 하루에 한 번만 갱신한다(4.4)
    revoked_at   TEXT NULL
);

-- 기기 토큰으로 만든 구독의 주인(4.6). API 토큰으로 만들었으면 NULL
ALTER TABLE push_subscriptions ADD COLUMN device_id INTEGER NULL REFERENCES devices (id);

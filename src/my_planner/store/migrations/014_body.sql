-- 014: 몸 기록 (SP8 스펙 7.1). 걸음 수와 잠(분) 두 값만. 56일 지난 행은 하루 한 번 작업이 지운다.
CREATE TABLE body_days (
    date          TEXT PRIMARY KEY CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    steps         INTEGER NULL CHECK (steps IS NULL OR steps BETWEEN 0 AND 100000),
    sleep_minutes INTEGER NULL CHECK (sleep_minutes IS NULL OR sleep_minutes BETWEEN 0 AND 1440),
    updated_at    TEXT NOT NULL,
    CHECK (steps IS NOT NULL OR sleep_minutes IS NOT NULL)
);

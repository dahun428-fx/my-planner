-- 객관적 위치(SP13 스펙 6.1): 측정값과 분기 스냅숏.

CREATE TABLE standing_measures (
    id            INTEGER PRIMARY KEY,
    metric        TEXT NOT NULL,            -- 스펙 6.2 목록. 코드가 목록 밖 값을 거절한다
    value_num     REAL,                     -- 숫자 값
    value_text    TEXT,                     -- 범주 값(예: education_tier = 'seoul_mid_low')
    measured_on   TEXT NOT NULL,            -- 'YYYY-MM-DD' 측정일(올린 날이 아니라)
    source_kind   TEXT NOT NULL CHECK (source_kind IN ('photo', 'pdf', 'manual', 'shortcut', 'import', 'derived')),
    source_ref    TEXT NULL,                -- 'photo:<id>', 'body_day:<date>' 등. 원본 파일 경로는 두지 않는다
    reliability   TEXT NOT NULL DEFAULT 'mid' CHECK (reliability IN ('high', 'mid', 'low')),
    created_at    TEXT NOT NULL,
    deleted_at    TEXT NULL,                -- 지우기는 표시만(되돌리기 24시간)
    CHECK (value_num IS NOT NULL OR value_text IS NOT NULL)
);
CREATE INDEX standing_measures_metric ON standing_measures (metric, measured_on) WHERE deleted_at IS NULL;

CREATE TABLE standing_snapshots (
    period        TEXT NOT NULL,            -- 'YYYY-Qn'
    axis          TEXT NOT NULL,
    cohort        TEXT NOT NULL CHECK (cohort IN ('national', 'peer')),
    score         INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    bench_version TEXT NOT NULL,            -- 기준표 파일의 version
    inputs_json   TEXT NOT NULL,            -- 계산에 쓴 측정값 id와 값(하락 이유 나누기용)
    taken_at      TEXT NOT NULL,
    PRIMARY KEY (period, axis, cohort)
);

-- 경험치 원장의 source_kind CHECK에 'standing'을 더한다(021과 같은 새 표 옮기기).
CREATE TABLE status_xp_ledger_new (
    id           INTEGER PRIMARY KEY,
    at           TEXT NOT NULL,
    logical_date TEXT NOT NULL,
    source_kind  TEXT NOT NULL CHECK (source_kind IN
        ('task_done', 'checkin_reply', 'condition', 'review_week', 'ladder', 'wheel',
         'year_review', 'rest_day', 'secretary', 'habit_check', 'workout_log', 'standing')),
    source_ref   TEXT NOT NULL,
    amount       INTEGER NOT NULL CHECK (amount > 0),   -- 오르기만 한다(ADR 0006)
    area         TEXT NULL,
    label        TEXT NOT NULL,
    UNIQUE (source_kind, source_ref)
);
INSERT INTO status_xp_ledger_new (id, at, logical_date, source_kind, source_ref, amount, area, label)
    SELECT id, at, logical_date, source_kind, source_ref, amount, area, label FROM status_xp_ledger;
DROP TABLE status_xp_ledger;
ALTER TABLE status_xp_ledger_new RENAME TO status_xp_ledger;
CREATE INDEX idx_xp_date ON status_xp_ledger (logical_date);

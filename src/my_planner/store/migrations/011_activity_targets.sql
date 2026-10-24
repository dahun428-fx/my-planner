-- 011: 활동의 대상 전부 (SP3-4 스펙 5.2). 한 활동이 여러 대상을 바꿀 수 있다(초안 묶음 확정, 초안 정리,
-- 할 일 내려놓기로 지워진 우선순위 칸). `activity.target`은 대상이 하나일 때 그 값, 여럿이면 NULL로 그대로 두고,
-- 대상 판정(확인 토큰 stale, 되돌리기 U3)은 모든 활동이 대상을 적는 이 표로 한다.
CREATE TABLE activity_targets (
    activity_id INTEGER NOT NULL REFERENCES activity (id),
    target      TEXT NOT NULL,
    PRIMARY KEY (activity_id, target)
);
CREATE INDEX idx_activity_targets_target ON activity_targets (target);

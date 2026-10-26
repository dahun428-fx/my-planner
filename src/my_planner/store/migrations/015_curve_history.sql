-- 015: 히스토리용 칸 (SP8 스펙 8.1). 둘 다 비워 둘 수 있다. 시드 가져오기와 대화 초안이 채운다.
ALTER TABLE curve_milestones ADD COLUMN area TEXT NULL CHECK (area IS NULL OR area IN
    ('career', 'finance', 'health', 'relationships', 'learning', 'quality_of_life'));
ALTER TABLE curve_chapters ADD COLUMN ladder_remembered INTEGER NULL
    CHECK (ladder_remembered IS NULL OR ladder_remembered BETWEEN 0 AND 10);  -- 그 시기를 돌아보며 기억하는 사다리 칸

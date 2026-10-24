"""상태창의 경험치, 레벨, 영역 이름 (SP3-4 스펙 9장, 부록 A).

숫자는 제안값이고 `config.toml`로 바꾸지 않는다(바꾸면 지난 원장과 레벨 계산이 어긋난다, 9장).
경험치는 오르기만 한다(ADR 0006): 이 모듈에는 깎는 값이 없다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

# 9.1 경험치
XP_TASK: Final = 10  # X1 할 일 완료(우선순위가 아님)
XP_TASK_PRIORITY: Final = {"day": 15, "week": 25, "month": 50, "quarter": 100, "year": 200}  # X2
XP_CHECKIN_REPLY: Final = 5  # X3
XP_CONDITION: Final = 5  # X4
XP_REVIEW_WEEK: Final = 30  # X5
XP_LADDER: Final = 10  # X6
XP_WHEEL: Final = 20  # X7
XP_YEAR_REVIEW: Final = 50  # X8
XP_REST_DAY: Final = 5  # X9
XP_SECRETARY: Final = (5, 10)  # X10 비서가 주는 값
SECRETARY_DAILY_MAX: Final = 3  # X10 하루 3회까지
SECRETARY_REASON_MAX: Final = 60  # X10 `reason` 글자 수(10장)
REST_DAY_MAX_DAYS: Final = 14  # X9 한 번에 보는 날 수(9.1)

# 원장 `label`(상태창 "최근 경험치" 줄, 5.5). 제목은 넣지 않는다. X10은 비서가 준 사유(`reason`)를 쓴다
LABEL_TASK: Final = "할 일 완료"  # X1, X2
LABEL_CHECKIN_REPLY: Final = "회차 답"  # X3
LABEL_CONDITION: Final = "컨디션 기록"  # X4
LABEL_REVIEW_WEEK: Final = "주간 회고"  # X5
LABEL_LADDER: Final = "사다리 점수"  # X6
LABEL_WHEEL: Final = "영역 점수"  # X7
LABEL_YEAR_REVIEW: Final = "연말 회고"  # X8
LABEL_REST_DAY: Final = "쉬는 날"  # X9

# 영역 이름(스펙 영역 6개, 표시 순서)
AREA_LABELS: Final = {
    "career": "커리어",
    "finance": "경제",
    "health": "건강",
    "relationships": "관계",
    "learning": "배움",
    "quality_of_life": "삶의 질",
}

# 부록 A "기본 회복 퀘스트"
DEFAULT_RECOVERY_QUESTS: Final = {
    "career": "하고 싶은 일 한 줄 적기",
    "finance": "이번 주 지출 한 번 훑어보기",
    "health": "20분 걷기",
    "relationships": "생각나는 사람에게 안부 한 줄",
    "learning": "읽고 싶던 글 한 편",
    "quality_of_life": "좋아하는 것 30분 하기",
}


def xp_threshold(level: int) -> int:
    """레벨 L에 닿는 누적 경험치 `T(L) = 25 × (L − 1) × (L + 4)` (9.2)."""
    return 25 * (level - 1) * (level + 4)


def level_for(xp_total: int) -> int:
    """`T(L) <= xp_total`인 가장 큰 L. 상한 없음."""
    xp = max(0, xp_total)
    # 25(L-1)(L+4) = xp  ->  L^2 + 3L - 4 - xp/25 = 0
    level = max(1, int((-3 + math.sqrt(25 + 4 * xp / 25)) / 2) + 1)
    while xp_threshold(level) > xp:
        level -= 1
    while xp_threshold(level + 1) <= xp:
        level += 1
    return level


def task_xp(biggest_cadence: str | None) -> int:
    """X1/X2: 완료 순간 그 할 일이 든 우선순위 가운데 가장 큰 주기(없으면 X1)."""
    return XP_TASK_PRIORITY[biggest_cadence] if biggest_cadence is not None else XP_TASK


def level_up_to(before: int, after: int) -> int | None:
    """경험치 합계가 `before`에서 `after`로 바뀌어 레벨이 올랐으면 새 레벨, 아니면 None."""
    new = level_for(after)
    return new if new > level_for(before) else None


@dataclass
class XpGain:
    """한 차례(두뇌 답 하나, 즉시 갈래 요청 하나, 버튼 하나)가 **스스로** 쌓은 경험치와 그 쌓기가 넘긴 레벨(9.2).

    원장에 한 줄을 쌓는 그 자리(`StatusRepo.grant`)에서 쌓기 직전·직후 합계로 동기적으로 적는다. 그래서 같은 두뇌
    호출 사이에 끼어든 다른 갈래(4.3)의 경험치는 이 차례의 레벨 오름으로 세지 않는다.
    """

    gained: int = 0
    level_up: int | None = None

    def add(self, before: int, after: int) -> None:
        self.gained += after - before
        self.note(level_up_to(before, after))

    def note(self, level: int | None) -> None:
        """다른 차례가 알려 준 레벨 오름(예: 버튼이 부른 즉시 갈래 응답의 `xp.level_up`)을 합친다."""
        if level is not None and (self.level_up is None or level > self.level_up):
            self.level_up = level

    def merge(self, other: XpGain) -> None:
        self.gained += other.gained
        self.note(other.level_up)


def progress(xp_total: int) -> tuple[int, int, int]:
    """(레벨, 이 레벨에서 쌓은 경험치 `xp_into_level`, 다음 레벨까지 필요한 양 `xp_for_next`)."""
    level = level_for(xp_total)
    base = xp_threshold(level)
    return level, xp_total - base, xp_threshold(level + 1) - base


def title_name(kind: str, title: str, title_label: str | None) -> str:
    """칭호 이름: `title_label`이 있으면 그것, 없으면 틀(9.4, 부록 A). 저점에는 칭호가 없다."""
    if title_label:
        return title_label
    if kind == "high":
        return f"「{title}」의 순간"
    if kind == "turning_point":
        return f"「{title}」을 지나온 사람"
    raise ValueError("칭호가 없는 사건 종류예요.")

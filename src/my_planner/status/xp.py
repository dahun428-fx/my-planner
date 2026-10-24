"""상태창의 경험치, 레벨, 영역 이름 (SP3-4 스펙 9장, 부록 A).

숫자는 제안값이고 `config.toml`로 바꾸지 않는다(바꾸면 지난 원장과 레벨 계산이 어긋난다, 9장).
경험치는 오르기만 한다(ADR 0006): 이 모듈에는 깎는 값이 없다.
"""

from __future__ import annotations

import math
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

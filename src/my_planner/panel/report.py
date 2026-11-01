"""인생 리포트와 "전체 진단"(SP15 스펙 6.2, 8장).

이 모듈의 지금 몫(계획 Task 12)은 전체 진단 상한이다: 하루 1회, 같은 ISO 주 2회, 사용자 몫 안의 남은 두뇌 호출.
진단한 날은 `app_state`의 `FULL_DAYS_KEY`(ISO 날짜 JSON 목록, 지난 14일만)에 둔다. 리포트를 저장한 진단만 센다:
`mark_full_diagnosis`는 리포트 저장(`save_life_report`, Task 13)이 그 트랜잭션 안에서 부른다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Literal

from my_planner.store.repos.state import StateRepo

FULL_DAYS_KEY = "panel_full_diagnosis_days"
FULL_PER_DAY = 1
FULL_PER_WEEK = 2
# 사용자 몫(`MOMENTS_RESERVE_CALLS`, 하루 마지막 10회 창) 안에서 이보다 적게 남았으면 시작하지 않는다(스펙 6.2)
FULL_MIN_CALLS_LEFT = 3
FULL_KEEP_DAYS = 14

FullBlock = Literal["day", "week", "calls"]
FULL_BLOCK_REPLIES: dict[FullBlock, str] = {
    "day": "전체 진단은 오늘 이미 했어요. 내일 다시 할 수 있어요.",
    "week": "전체 진단은 이번 주에 두 번 했어요. 다음 주에 다시 할 수 있어요.",
    "calls": "오늘은 두뇌 호출이 얼마 없어 전체 진단을 시작하지 않았어요. 내일 해 볼까요?",
}
# 전체 진단 두뇌 호출이 오류(시간 초과 포함)로 끝났다. 다시 부르지 않는다(디스패처)
FULL_FAILED_REPLY = "전체 진단이 중간에 멈췄어요. 횟수에는 세지 않았어요. 잠시 뒤 다시 눌러 주세요."


def full_diagnosis_days(state: StateRepo) -> list[date]:
    """기록된 진단 날짜(오래된 것부터, 겹침 없음). 없거나 깨진 값은 빈 목록."""
    try:
        raw = json.loads(state.get(FULL_DAYS_KEY) or "[]")
    except ValueError:
        return []
    days: set[date] = set()
    for v in raw if isinstance(raw, list) else []:
        try:
            days.add(date.fromisoformat(v))
        except (TypeError, ValueError):
            continue
    return sorted(days)


def full_diagnosis_block(state: StateRepo, today: date, calls_left: int) -> FullBlock | None:
    """전체 진단을 막는 이유. `today`는 논리적 날짜, `calls_left`는 사용자 몫 창 안에서 남은 두뇌 호출 수."""
    days = full_diagnosis_days(state)
    if sum(d == today for d in days) >= FULL_PER_DAY:
        return "day"
    week = today.isocalendar()[:2]
    if sum(d.isocalendar()[:2] == week for d in days) >= FULL_PER_WEEK:
        return "week"
    if calls_left < FULL_MIN_CALLS_LEFT:
        return "calls"
    return None


def mark_full_diagnosis(state: StateRepo, today: date) -> None:
    """오늘을 진단한 날로 적는다. 지난 `FULL_KEEP_DAYS`일(오늘 포함)만 남긴다."""
    since = today - timedelta(days=FULL_KEEP_DAYS - 1)
    days = sorted({d for d in full_diagnosis_days(state) if d >= since} | {today})
    state.set(FULL_DAYS_KEY, json.dumps([d.isoformat() for d in days]))

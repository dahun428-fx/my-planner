"""ToolEvent → 확인 문구 (스펙 5.5). 도구가 돌려준 이벤트만 근거로 하네스가 만든다."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from my_planner.domain import ToolEvent


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _day_label(d: date, today: date) -> str:
    if d == today:
        return "오늘"
    if d == today + timedelta(days=1):
        return "내일"
    return _md(d)


_CADENCE_LABEL = {"day": "오늘", "week": "이번 주", "month": "이번 달", "quarter": "이번 분기", "year": "올해"}


def _line(e: ToolEvent, today: date) -> str | None:
    title = e.data.get("title", "")
    if e.kind == "task_added":
        out = f"✓ 추가: {title}"
        if e.data.get("scheduled_at"):
            at = datetime.fromisoformat(e.data["scheduled_at"])
            return f"{out} ({_md(at.date())} {at:%H:%M})"
        if e.data.get("planned_for"):
            return f"{out} → {_day_label(date.fromisoformat(e.data['planned_for']), today)}"
        return out
    if e.kind == "task_moved":
        pf = e.data.get("planned_for")
        label = _day_label(date.fromisoformat(pf), today) if pf else "날짜 없음"
        return f"✓ 옮김: {title} → {label}"
    if e.kind == "priorities_set":
        label = _CADENCE_LABEL[e.data["cadence"]]
        titles = e.data.get("titles", [])
        if not titles:
            return f"✓ 우선순위({label}): 비움"
        return f"✓ 우선순위({label}): " + " ".join(f"{i}. {t}" for i, t in enumerate(titles, start=1))
    return {
        "task_completed": f"✓ 완료: {title}",
        "task_reopened": f"✓ 되돌림: {title}",
        "task_dropped": f"✓ 내려놓음: {title}",
        "task_updated": f"✓ 바꿈: {title}",
        "tasks_confirmed": f"✓ 확정: {title}",
    }.get(e.kind)


def render_confirmations(events: list[ToolEvent], today: date) -> str:
    """이벤트마다 한 줄. 문구가 없는 종류(조회 등)는 건너뛴다. 없으면 빈 문자열."""
    lines = [ln for e in events if (ln := _line(e, today)) is not None]
    return "\n".join(lines)


def draft_dropped_reply(title: str) -> str:
    """`✗ 빼기` 버튼을 눌렀을 때의 알림. 버튼 낱말에 맞춘다(`drop_task`의 "내려놓음"과 다르다)."""
    return f"✗ 뺐어요: {title}"

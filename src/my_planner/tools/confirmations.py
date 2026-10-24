"""ToolEvent → 확인 문구 (스펙 5.5). 도구가 돌려준 이벤트만 근거로 하네스가 만든다."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

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


def confirmation_line(e: ToolEvent, today: date) -> str | None:
    """이벤트 하나의 확인 문구 한 줄(SP1 5.5). 문구가 없는 종류는 None. 활동의 `summary`도 이것이다(5.2)."""
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
    lines = [ln for e in events if (ln := confirmation_line(e, today)) is not None]
    return "\n".join(lines)


def titles_summary(verb: str, titles: list[str]) -> str:
    """할 일 여럿을 한 활동으로 남길 때의 한 줄: `✓ 확정: 물 마시기, 스트레칭`."""
    return f"✓ {verb}: " + ", ".join(titles)


def condition_summary(score: int) -> str:
    """컨디션 기록 활동의 한 줄. SP1 버튼 답과 같은 문구이고 메모는 넣지 않는다(5.2)."""
    return f"컨디션 {score} 기록했어요."


_CARD_LABEL = {"ui_todo_list": "할 일 목록", "ui_choice": "고르기", "ui_summary_card": "요약"}


def _card_label(component: str, props: Any) -> str:
    """카드 활동의 이름: props의 제목(`title`, `ui_choice`는 `question`), 없으면 컴포넌트 이름."""
    p = props if isinstance(props, dict) else {}
    name = p.get("title") if component != "ui_choice" else p.get("question")
    return name.strip() if isinstance(name, str) and name.strip() else _CARD_LABEL.get(component, component)


def card_pinned_summary(component: str, props: Any) -> str:
    return f"✓ 카드 고정: {_card_label(component, props)}"


def card_unpinned_summary(component: str, props: Any) -> str:
    return f"✓ 카드 고정 해제: {_card_label(component, props)}"


def cards_reordered_summary() -> str:
    return "✓ 카드 순서 바꿈"


def drafts_expired_summary(count: int) -> str:
    return f"✓ 초안 정리: {count}개"


def confirm_declined_summary(summary: str) -> str:
    return f"✗ 그대로 뒀어요 ({summary})"


_UNDO_VERB = {"되돌림": "다시 열기"}  # `✓ 되돌림: 운동`(다시 연 것)을 되돌리면 "운동 되돌림"이 겹친다
# `confirmation_line`이 `추가`·`옮김` 뒤에 붙이는 날짜 꼬리. 제목 안의 "→ X"는 건드리지 않는다
_DATE_TAIL = re.compile(r"( → (오늘|내일|날짜 없음|\d{1,2}/\d{1,2})| \(\d{1,2}/\d{1,2} \d{2}:\d{2}\))$")
_DATE_TAIL_VERBS = frozenset({"추가", "옮김"})
_SUMMARY = re.compile(r"^✓ (?P<verb>[^:]+): (?P<rest>.*)$")
_BARE = re.compile(r"^✓ (?P<verb>[^:]+)$")  # 대상 이름이 없는 한 줄(`✓ 카드 순서 바꿈`)
_CONDITION = re.compile(r"^(?P<what>컨디션 \d+) 기록했어요\.$")


def undo_summary(summary: str) -> str:
    """되돌림 확인(부록 A): `↩ 되돌림: {확인 문구 요지}`. `✓ 완료: 운동` → `↩ 되돌림: 운동 완료`.

    요지는 원래 활동의 확인 문구에서 만든다: 날짜 꼬리(`→ 내일`, `(10/25 14:00)`)는 떼고, 우선순위는 목록 이름만.
    """
    if (m := _SUMMARY.match(summary)) is not None:
        verb, rest = m["verb"], m["rest"]
        if verb.startswith("우선순위"):
            gist = verb
        else:
            if verb in _DATE_TAIL_VERBS:
                rest = _DATE_TAIL.sub("", rest)
            gist = f"{rest} {_UNDO_VERB.get(verb, verb)}"
    elif (b := _BARE.match(summary)) is not None:
        gist = b["verb"]
    elif (c := _CONDITION.match(summary)) is not None:
        gist = f"{c['what']} 기록"
    else:
        gist = summary
    return f"↩ 되돌림: {gist}"


def period_label(cadence: str, period: str, current: str) -> str:
    """지금 기간이면 `이번 분기` 같은 말, 아니면 기간 그대로(`2027-Q1`)."""
    return _CADENCE_LABEL[cadence] if period == current else period


def draft_dropped_reply(title: str) -> str:
    """`✗ 빼기` 버튼을 눌렀을 때의 알림. 버튼 낱말에 맞춘다(`drop_task`의 "내려놓음"과 다르다)."""
    return f"✗ 뺐어요: {title}"

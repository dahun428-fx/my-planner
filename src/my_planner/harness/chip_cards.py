"""퀵 칩 카드 보장 (SP9c 스펙 4.4).

칩 차례가 정상으로 끝나면(정상 답 경로, `result.status == "ok"`) 두뇌가 그리지 않은 결과 카드를 하네스가 정한다.
디스패처가 `Outbound.chip_cards`에 싣고 `harness_cards`가 맨 뒤에 조각 id `h_chip`으로 붙인다.

- 두뇌가 이미 그 칩의 카드를 그렸으면(`ctx.ui_drawn_names`) 붙이지 않는다.
- 두뇌 조각 수(`ctx.ui_drawn`)와 합쳐 `UI_PARTS_PER_REPLY`(2)를 넘지 않는다. 하네스 조각은 세지 않는다.
- props와 출력은 두뇌 조각과 같은 함수로 만든다(`ui_result_items`, `ui_period_data`, `occurrence_item` →
  `to_api_times` → `ui_event_items`, `memo_title`). 붙이기 전에 `validate_props`(하네스 조각: 글 검사 없음)를 거친다.

로그에는 칩 키와 컴포넌트 이름만 남긴다(본문, 제목, 인자 없음).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.clock import logical_date
from my_planner.domain import RunContext
from my_planner.harness.redact import redact
from my_planner.store.repos.events import RANGE_MAX_DAYS, Occurrence, expand, sort_key
from my_planner.store.repos.memos import memo_lines, memo_title
from my_planner.timefmt import to_api_times
from my_planner.tools.core import period_day_bounds
from my_planner.tools.events import occurrence_item, ui_event_items
from my_planner.tools.mcp_adapter import UI_PARTS_PER_REPLY
from my_planner.tools.ui import validate_props

if TYPE_CHECKING:
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

ChipCard = tuple[str, dict[str, Any], dict[str, Any]]  # (컴포넌트, props, 출력)

# 두뇌가 이 가운데 하나를 그렸으면 그대로 둔다(4.4 표 둘째 칸)
DRAWN_ENOUGH: dict[str, frozenset[str]] = {
    "todo": frozenset({"ui_result", "ui_period_list", "ui_events"}),
    "event": frozenset({"ui_events"}),
    "memo": frozenset({"ui_summary_card"}),
    "today": frozenset({"ui_period_list"}),
    "next": frozenset({"ui_events"}),
}
RESULT_MAX = 2  # `ui_result.task_ids` 상한
PERIOD_FROM = 3  # 할 일이 이만큼이면 `ui_period_list`
HIGHLIGHT_MAX = 30  # `ui_period_list.highlight_task_ids` 상한
EVENTS_MAX = 10  # `ui_events.items` 상한
NEXT_MAX = 3
NEXT_DAYS = 7  # 오늘부터 7일 안(오늘 포함)
MEMO_LINES = 3
MEMO_LINE_MAX = 120
MEMO_TITLE_ONLY = "메모 탭에서 볼 수 있어요."  # 스펙 5장


def chip_cards(chip: str, ctx: RunContext, tools: Tools, now: datetime) -> list[ChipCard]:
    """칩 차례에 하네스가 붙일 카드(남은 자리만큼, 지금은 많아야 하나). 필요 없거나 만들 수 없으면 빈 목록."""
    room = UI_PARTS_PER_REPLY - ctx.ui_drawn
    enough = DRAWN_ENOUGH.get(chip)
    if room <= 0 or enough is None or enough & set(ctx.ui_drawn_names):
        return []
    try:
        card = _BUILDERS[chip](ctx, tools, now)
    except Exception as e:  # noqa: BLE001 - 카드가 안 돼도 답은 나간다. 종류만 남긴다
        log.warning("chip_card_error", extra={"chip": chip, "error_type": type(e).__name__})
        return []
    if card is None:
        return []
    component, props, _ = card
    if validate_props(component, props, harness=True) is not None:
        log.warning("chip_card_invalid", extra={"chip": chip, "component": component})
        return []
    log.info("chip_card_added", extra={"chip": chip, "component": component})
    return [card]


# --- 칩마다 ---


def _todo(ctx: RunContext, tools: Tools, now: datetime) -> ChipCard | None:
    """할 일 1~2개 `ui_result`, 3개 이상 첫 할 일 날짜의 `ui_period_list`(범위 밖이면 앞 2개 `ui_result`).
    할 일 대신 일정을 만들었으면 `event`처럼 `ui_events`."""
    ids = _created_ids(ctx, "task_added")
    if not ids:
        return _event(ctx, tools, now)
    if len(ids) >= PERIOD_FROM:
        first = tools.tasks.get(ids[0])
        day = first.planned_for if first is not None else None
        lo, hi = period_day_bounds(_today(tools, now))
        if day is not None and lo <= day <= hi:
            return _period(tools, {"day": day.isoformat(), "highlight_task_ids": ids[:HIGHLIGHT_MAX]})
    ids = ids[:RESULT_MAX]
    items = tools.ui_result_items(ctx, ids)
    if not items:
        return None
    return "ui_result", {"task_ids": ids}, {"ok": True, "data": {"today": tools.today().isoformat(), "items": items}}


def _event(ctx: RunContext, tools: Tools, now: datetime) -> ChipCard | None:
    """만든 일정마다 첫 그날 일정 한 줄(반복이면 시작일), 시각순(하루 종일 먼저), 10개까지."""
    repo = tools.events
    if repo is None:
        return None
    skips = repo.skips()
    occ: list[Occurrence] = []
    for eid in _created_ids(ctx, "event_created", key="event_id"):
        e = repo.get(eid)
        if e is None:
            continue
        got = expand(e, e.start_date, e.start_date + timedelta(days=RANGE_MAX_DAYS - 1), tz=repo.tz,
                     skips=skips.get(e.id, set()))
        if got:
            occ.append(got[0])
    return _events(sorted(occ, key=sort_key)[:EVENTS_MAX])


def _memo(ctx: RunContext, tools: Tools, now: datetime) -> ChipCard | None:
    """이번 차례 마지막 메모의 `ui_summary_card`: 가린 본문의 제목(`memo_title`)과 그 뒤 비지 않은 줄 앞 3줄."""
    ids = _created_ids(ctx, "memo_created", key="memo_id")
    if not ids or tools.memos is None:
        return None
    m = tools.memos.get(ids[-1])
    if m is None:
        return None
    body = redact(m.body)[0]  # 카드 글은 스트림으로 간다: 두뇌에 가는 제목처럼 가린 글로
    lines = [s[:MEMO_LINE_MAX] for s in memo_lines(body)[1:1 + MEMO_LINES]] or [MEMO_TITLE_ONLY]
    return "ui_summary_card", {"title": memo_title(body), "lines": lines}, {"ok": True}


def _today_card(ctx: RunContext, tools: Tools, now: datetime) -> ChipCard | None:
    return _period(tools, {"day": _today(tools, now).isoformat()})


def _next(ctx: RunContext, tools: Tools, now: datetime) -> ChipCard | None:
    """지금 이후 시작하는 일정(오늘부터 7일 안) 시작 시각순 3개. 하루 종일은 오늘보다 뒤 날짜만, 그날 00:00(현지)로."""
    repo = tools.events
    if repo is None:
        return None
    today = _today(tools, now)

    def start_of(o: Occurrence) -> datetime:
        return o.start if o.start is not None else datetime.combine(o.date, time(0), tzinfo=repo.tz)

    got = [
        o for o in repo.occurrences(today, today + timedelta(days=NEXT_DAYS - 1))
        # 01:30(논리적 오늘은 전날)이면 달력 오늘의 하루 종일 일정도 "다음"에 든다: 의도한 규칙
        if (o.date > today if o.all_day else o.start is not None and o.start >= now)
    ]
    got.sort(key=lambda o: (start_of(o), not o.all_day, o.event_id))
    return _events(got[:NEXT_MAX])


_BUILDERS: dict[str, Callable[[RunContext, Any, datetime], ChipCard | None]] = {
    "todo": _todo, "event": _event, "memo": _memo, "today": _today_card, "next": _next,
}


# --- 공통 ---


def _today(tools: Tools, now: datetime) -> date:
    return logical_date(now, tools.tz, tools.boundary)


def _created_ids(ctx: RunContext, kind: str, *, key: str | None = None) -> list[int]:
    """이번 차례 활동(`ctx.events`)에서 만든 것의 번호, 만든 순서로 한 번씩. `key`가 없으면 `task_id`."""
    out: list[int] = []
    for e in ctx.events:
        if e.kind != kind:
            continue
        i = e.task_id if key is None else e.data.get(key)
        if isinstance(i, int) and i not in out:
            out.append(i)
    return out


def _period(tools: Tools, props: dict[str, Any]) -> ChipCard | None:
    data = tools.ui_period_data(props)
    return ("ui_period_list", props, {"ok": True, "data": data}) if data is not None else None


def _events(occ: list[Occurrence]) -> ChipCard | None:
    """`ui_events`: 두뇌가 `list_events` 항목을 넘길 때와 같은 칸(시각은 UTC `Z`). 출력은 두뇌 조각처럼 `{"ok": true}`."""
    if not occ:
        return None
    return "ui_events", {"items": ui_event_items(to_api_times([occurrence_item(o) for o in occ]))}, {"ok": True}

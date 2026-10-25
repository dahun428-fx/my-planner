"""체크인 시간 바꾸기 (SP9 스펙 8장, 9.7). `Tools`가 이 mixin을 상속한다.

- 바꾼 시각은 `app_state.schedule_override`(`StateRepo.get_schedule_override`)에 칸마다 `{"time", "from", "prev"}`로
  둔다. 날짜별 시각은 `loop.schedule.checkin_time`이 정한다. 러너는 tick마다 다시 읽는다(재시작 없음).
- 허용 범위: 아침 05:00~11:30, 저녁 15:00~23:30, 10분 단위(`validate_checkin_time`). 벗어나면 API는
  `422 checkin_time_invalid`.
- 적용 시점(`decide_from`)은 논리적 날짜 기준이다: 오늘 그 루프의 회차가 이미 있으면 내일, 없고 새 시각과 원래 시각이
  모두 지금보다 뒤면 오늘, 그 밖에는 내일. 그래서 오늘 회차가 사라지거나 두 번 생기지 않는다.
- 즉시 갈래(앱 설정 `PUT /settings/checkin-times`, 확인 카드의 `/actions`)는 `apply_checkin_time`으로 바로 적용하고
  되돌릴 수 있다(이전 칸으로). 두뇌 도구 `set_checkin_time`은 언제나 `needs_confirm`이다(아무것도 바꾸지 않는다).
- 활동 `kind = "checkin_time_set"`, 대상 `checkin_time:<loop>:<day_type>`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from my_planner.clock import logical_date
from my_planner.domain import LoopKey, RunContext, ToolEvent
from my_planner.loop.schedule import (
    CHECKIN_LOOPS,
    DAY_TYPES,
    CheckinSlot,
    DayType,
    Overrides,
    config_time,
    day_type_of,
    review_time,
    slot_time,
)
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import register_undo
from my_planner.tools.confirmations import (
    checkin_set_line,
    confirm_checkin_summary,
    slot_label,
)

if TYPE_CHECKING:
    from my_planner.config import Settings
    from my_planner.store.repos.runs import Run, RunsRepo
    from my_planner.store.repos.state import StateRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

ACTION = "set_checkin_time"
KIND = "checkin_time_set"
CHAT_CONFIRM_TTL = timedelta(minutes=10)  # 앱 대화(사용자 차례)의 확인 토큰. `/actions` 토큰과 같다

# 허용 범위(8장): 아침은 아침 답장 창 12:00보다 30분 앞까지
RANGES: dict[LoopKey, tuple[time, time]] = {
    LoopKey.morning_brief: (time(5, 0), time(11, 30)),
    LoopKey.evening_checkin: (time(15, 0), time(23, 30)),
}
STEP_MIN = 10
_HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


Applies = Literal["today", "tomorrow"]

MSG_INVALID = "체크인 시간은 아침 05:00~11:30, 저녁 15:00~23:30 사이에서 10분 단위로 정할 수 있어요."
MSG_LOOP = "loop는 morning_brief, evening_checkin 중 하나예요."
MSG_DAY_TYPE = "day_type은 weekday, weekend 중 하나예요."
MSG_UNAVAILABLE = "체크인 시간을 바꿀 수 없어요."


def checkin_target(loop: LoopKey | str, day_type: str) -> str:
    return f"checkin_time:{LoopKey(loop).value}:{day_type}"


def parse_loop(v: Any) -> LoopKey | None:
    try:
        loop = LoopKey(v)
    except ValueError:
        return None
    return loop if loop in CHECKIN_LOOPS else None


def parse_day_type(v: Any) -> DayType | None:
    return v if v in DAY_TYPES else None


def validate_checkin_time(loop: LoopKey, v: Any) -> time | None:
    """`"HH:MM"`이 그 루프의 범위 안이고 10분 단위면 그 시각, 아니면 None."""
    if not isinstance(v, str) or (m := _HHMM.match(v)) is None:
        return None
    t = time(int(m[1]), int(m[2]))
    lo, hi = RANGES[loop]
    if not lo <= t <= hi or t.minute % STEP_MIN:
        return None
    return t


def _runs_today(runs: Iterable[Run], loops: set[LoopKey], today: date, settings: Settings) -> bool:
    return any(
        r.loop in loops and logical_date(r.scheduled_for, settings.timezone, settings.day_boundary) == today
        for r in runs
    )


def _follows_review(settings: Settings, loop: LoopKey, day_type: DayType, d: date) -> bool:
    """d가 주간 회고 요일이고 이 칸이 주말 저녁이면 회고도 이 칸을 따라간다(8장)."""
    return (
        loop is LoopKey.evening_checkin and day_type == "weekend"
        and d.weekday() == settings.schedule.review.week.weekday_index
    )


def _today_values(
    settings: Settings, overrides: Overrides, loop: LoopKey, day_type: DayType, d: date
) -> tuple[time, ...]:
    """날짜 d에 이 칸이 정하는 시각들: 그 칸의 시각, 회고 요일의 주말 저녁이면 회고 시각도."""
    out = (slot_time(settings, overrides, loop, day_type, d),)
    if _follows_review(settings, loop, day_type, d):
        out += (review_time(settings, overrides, d),)
    return out


def decide_from(
    now: datetime, loop: LoopKey, day_type: DayType, new: time, overrides: Overrides, runs: Iterable[Run],
    *, settings: Settings,
) -> date:
    """새 시각이 적용되는 첫 날(`from`, 8장 적용 시점). 오늘 = 논리적 날짜(04:00 경계).

    `runs`는 오늘(논리적 날짜) 회차들이다(만들어짐·보냄·건너뜀 모두 "있음"). 오늘이 그 칸의 요일 묶음이 아니면
    오늘은 그 칸을 쓰지 않으므로 내일이다. 주말 저녁을 일요일에 바꾸면 주간 회고(같은 시각을 따라감)도 함께 본다.
    """
    tz, boundary = settings.timezone, settings.day_boundary
    today = logical_date(now, tz, boundary)
    tomorrow = today + timedelta(days=1)
    if day_type_of(today) != day_type:
        return tomorrow
    z = ZoneInfo(tz)
    loops = {loop}
    originals = list(_today_values(settings, overrides, loop, day_type, today))
    if _follows_review(settings, loop, day_type, today):
        loops.add(LoopKey.review)
    if _runs_today(runs, loops, today, settings):
        return tomorrow
    if datetime.combine(today, new, z) > now and all(datetime.combine(today, t, z) > now for t in originals):
        return today
    return tomorrow


def checkin_items(settings: Settings, overrides: Overrides, today: date) -> list[dict[str, Any]]:
    """`GET /settings/checkin-times`의 네 칸(평일 아침, 평일 저녁, 주말 아침, 주말 저녁). `time`은 앞으로의 값,
    `from`은 그 값이 적용되는 첫 날(바꾼 적이 없으면 null), `effective_today`는 오늘(논리적 날짜)의 값."""
    out: list[dict[str, Any]] = []
    for day_type in DAY_TYPES:
        for loop in CHECKIN_LOOPS:
            slot = overrides.get(loop, {}).get(day_type)
            latest = slot.time if slot is not None else slot_time(settings, overrides, loop, day_type, today)
            out.append({
                "loop": loop.value,
                "day_type": day_type,
                "time": f"{latest:%H:%M}",
                "from": slot.from_.isoformat() if slot is not None and slot.from_ else None,
                "effective_today": f"{slot_time(settings, overrides, loop, day_type, today):%H:%M}",
            })
    return out


def _slot_json(slot: CheckinSlot | None) -> dict[str, Any] | None:
    if slot is None:
        return None
    return {
        "time": f"{slot.time:%H:%M}",
        "from": slot.from_.isoformat() if slot.from_ else None,
        "prev": f"{slot.prev:%H:%M}" if slot.prev else None,
    }


def _slot_from_json(v: Any) -> CheckinSlot | None:
    if not isinstance(v, dict):
        return None
    return CheckinSlot(
        time.fromisoformat(v["time"]),
        date.fromisoformat(v["from"]) if v.get("from") else None,
        time.fromisoformat(v["prev"]) if v.get("prev") else None,
    )


class CheckinTimeTools:
    """`Tools`가 상속한다. `self.state`, `self.settings`, `self.runs`가 없으면 거절한다."""

    state: StateRepo | None
    settings: Settings | None
    runs: RunsRepo | None

    def _checkin_ready(self: Tools) -> bool:
        return self.state is not None and self.settings is not None and self.runs is not None

    def _plan_checkin(
        self: Tools, loop: LoopKey, day_type: DayType, new: time
    ) -> tuple[Overrides, CheckinSlot | None, CheckinSlot, time, Applies]:
        """(지금 칸들, 바꾸기 전 칸, 새 칸, 바꾸기 전 시각, 적용 시점). 쓰지 않는다."""
        assert self.state is not None and self.settings is not None and self.runs is not None
        s = self.settings
        ov = self.state.get_schedule_override()
        old = ov.get(loop, {}).get(day_type)
        today = self.today()
        if old is not None and old.from_ is not None and old.from_ > today:
            # 이미 from이 미래인 칸을 다시 바꾸면 prev와 from은 그대로 두고 time만 바꾼다(8장)
            new_slot = CheckinSlot(new, old.from_, old.prev)
            before = old.time
        else:
            before = slot_time(s, ov, loop, day_type, today)
            runs = self.runs.on_logical_date(today, s.timezone, s.day_boundary)
            from_ = decide_from(self.clock.now(), loop, day_type, new, ov, runs, settings=s)
            new_slot = CheckinSlot(new, from_, before)
        applies: Applies = "today" if new_slot.from_ is not None and new_slot.from_ <= today else "tomorrow"
        return ov, old, new_slot, before, applies

    def apply_checkin_time(self: Tools, ctx: RunContext, loop: Any = None, day_type: Any = None,
                           time: Any = None, applies: Any = None) -> dict[str, Any]:
        """즉시 갈래(앱 설정, 확인 카드): 바로 적용하고 되돌릴 수 있게 활동을 남긴다(한 트랜잭션).

        `applies`는 확인 카드가 물었던 적용 시점(오늘부터/내일부터)이다. 적용 시점은 지금 다시 정하므로, 물은 뒤에
        달라졌으면 아무것도 바꾸지 않고 `{"stale": True}`(→ 409 stale, 카드가 다시 묻게)."""
        checked = self._check_checkin(loop, day_type, time)
        if isinstance(checked, str):
            return _err(checked)
        lk, dt, new = checked
        ov, old, new_slot, before, now_applies = self._plan_checkin(lk, dt, new)
        if applies is not None and applies != now_applies:
            log.info("checkin_time_stale", extra={"loop": lk.value, "day_type": dt})
            return {"stale": True}
        applies = now_applies
        assert self.state is not None
        ov.setdefault(lk, {})[dt] = new_slot
        with self.tasks.transaction():
            self.state.set_schedule_override(ov)
            self._record_checkin(ctx, lk, dt, old, checkin_set_line(lk, dt, before, new, applies))
        log.info("checkin_time_set", extra={"loop": lk.value, "day_type": dt, "applies": applies})
        return {
            "loop": lk.value, "day_type": dt, "time": f"{new:%H:%M}",
            "from": new_slot.from_.isoformat() if new_slot.from_ else None, "applies": applies,
        }

    def _record_checkin(
        self: Tools, ctx: RunContext, loop: LoopKey, day_type: DayType, old: CheckinSlot | None, summary: str
    ) -> None:
        from my_planner.tools.activity import record_activity

        target = checkin_target(loop, day_type)
        # 확인 카드로 적용해도(`risk = confirm`) 되돌릴 수 있다(8장 "되돌리기 있음(이전 값으로)")
        record_activity(
            self.activity, ctx, kind=KIND, target=target, summary=summary, risk="low",
            undo={"loop": loop.value, "day_type": day_type, "slot": _slot_json(old)},
        )

    def _check_checkin(self: Tools, loop: Any, day_type: Any, t: Any) -> tuple[LoopKey, DayType, time] | str:
        if not self._checkin_ready():
            return MSG_UNAVAILABLE
        lk = parse_loop(loop)
        if lk is None:
            return MSG_LOOP
        dt = parse_day_type(day_type)
        if dt is None:
            return MSG_DAY_TYPE
        new = validate_checkin_time(lk, t)
        if new is None:
            return MSG_INVALID
        return lk, dt, new

    @_tool
    def set_checkin_time(self: Tools, ctx: RunContext, loop: Any = None, day_type: Any = None,
                         time: Any = None) -> dict[str, Any]:
        """두뇌 도구(앱 대화에만): 언제나 확인을 묻는다. 아무것도 바꾸지 않고 확인 토큰만 만든다."""
        checked = self._check_checkin(loop, day_type, time)
        if isinstance(checked, str):
            return _err(checked)
        if self.confirms is None:
            return _err(MSG_UNAVAILABLE)
        lk, dt, new = checked
        _, _, _, before, applies = self._plan_checkin(lk, dt, new)
        summary = confirm_checkin_summary(lk, dt, before, new, applies)
        # 물을 때의 적용 시점도 싣는다: 확인할 때 달라졌으면 적용하지 않는다(`apply_checkin_time`)
        args = {"loop": lk.value, "day_type": dt, "time": f"{new:%H:%M}", "applies": applies}
        button = f"체크인 시간: {slot_label(lk, dt)}"
        if ctx.run_turn and ctx.run_id is not None:
            return self._request_confirm(ctx, ACTION, args, summary, button)
        return self._chat_confirm(ctx, args, summary, button)

    def _chat_confirm(
        self: Tools, ctx: RunContext, args: dict[str, Any], summary: str, button: str, *, action: str = ACTION,
    ) -> dict[str, Any]:
        """사용자 차례의 확인 요청: 토큰(10분, `origin = actions`), 호출 기록, 활동 `confirm_requested`를 한 트랜잭션.
        ToolEvent의 `card`는 앱 답 스트림에 확인 카드(`ui_confirm`)를 붙이라는 표시다."""
        from my_planner.tools.confirmations import confirm_requested_summary

        assert self.confirms is not None
        with self.tasks.transaction():
            p = self.confirms.create(
                action=action, args=args, summary=summary, origin="actions",
                expires_at=self.clock.now() + CHAT_CONFIRM_TTL, run_id=ctx.run_id, conversation_id=ctx.conversation_id,
            )
            data = {"action": action, "summary": summary, "button": button, "confirm_token": p.token}
            self.tasks.log_tool_event(
                ctx.run_id, ctx.conversation_id, None, "confirm_requested", inbound_id=ctx.inbound_id, data=data
            )
            self._record(ctx, "confirm_requested", None, confirm_requested_summary(summary), None)
        ctx.events.append(
            ToolEvent(kind="confirm_requested", task_id=None, data={**data, "args": args, "card": True})
        )
        log.info("confirm_requested", extra={"action": action, "run_id": ctx.run_id})
        return {"status": "needs_confirm", "confirm_token": p.token, "summary": summary}


def _undo_checkin_time(tools: Tools, payload: dict[str, Any], ctx: RunContext) -> str | None:
    """되돌리기 = "이전 시각으로 다시 바꾸기"(8장 적용 시점 규칙을 그대로 탄다).

    이전 칸(없었으면 칸을 지워 config 값)을 그대로 두면 오늘 값이 달라지는 경우, 오늘 회차가 이미 있거나 이전 시각이
    이미 지났으면(`decide_from`이 내일) 오늘은 지금 값을 두고 내일부터 이전 시각: `CheckinSlot(이전 시각, 내일, 지금 오늘 값)`.
    그래서 되돌려도 오늘 회차가 사라지거나 두 번 생기지 않는다.
    """
    assert tools.state is not None and tools.settings is not None and tools.runs is not None
    s = tools.settings
    loop, day_type = LoopKey(payload["loop"]), payload["day_type"]
    ov = tools.state.get_schedule_override()
    old = _slot_from_json(payload.get("slot"))
    restored = {k: dict(v) for k, v in ov.items()}
    slots = restored.setdefault(loop, {})
    if old is None:
        slots.pop(day_type, None)
    else:
        slots[day_type] = old
    now = tools.clock.now()
    today = logical_date(now, s.timezone, s.day_boundary)
    if day_type_of(today) == day_type:
        current = _today_values(s, ov, loop, day_type, today)
        back = _today_values(s, restored, loop, day_type, today)
        if back != current:
            runs = tools.runs.on_logical_date(today, s.timezone, s.day_boundary)
            from_ = decide_from(now, loop, day_type, back[0], ov, runs, settings=s)
            if from_ != today:
                forward = old.time if old is not None else config_time(s, loop, day_type)
                slots[day_type] = CheckinSlot(forward, from_, current[0])
    tools.state.set_schedule_override({k: v for k, v in restored.items() if v})
    return None


register_undo(KIND, _undo_checkin_time)

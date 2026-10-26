"""스케줄 도구와 일정 동작 (SP9 스펙 5.1, 5.2, 5.5, 5.6, ADR 0015). `Tools`가 이 mixin을 상속한다.

- 두뇌 도구(앱 대화에만, `APP_ONLY_TOOLS`): `list_events`, `create_event`, `update_event`, `delete_event`.
- 확인(5.5, 자율성 B): `create_event`는 바로 적용하고 되돌릴 수 있다. 회차 차례(`ctx.run_turn`)에서만 확인 토큰을
  만든다(앱 체크인 상세의 `ui_confirm`). `update_event`는 제목·메모·영역은 바로, 날짜·시각·하루 종일·길이·반복·알림이
  바뀌면 두뇌가 부를 때 언제나 확인(`needs_confirm` "일정을 바꿔요: {title} → {새 때}"). `delete_event`는 두뇌가 부를
  때 언제나 확인. 앱이 `POST /actions`로 부른 것(사용자가 누른 것)은 확인 없이 적용하고 되돌리기를 준다.
- 즉시 갈래 전용 동작 `dismiss_missed_reminder`(오늘 화면의 놓친 알림 줄 닫기, 활동 없음).
- 활동 `event_created`/`event_updated`/`event_skipped`/`event_repeat_ended`/`event_deleted`, 대상 `event:<id>`(건너뛰기는
  `event:<id>:<date>`). 바꾸면 `tool_events_log`에 `{"event_id", "title", …}`를 써서 다시 처리할 때 두뇌를 다시 부르지
  않는다(같은 일정을 두 번 만들지 않는다).
- 로그에는 일정 번호와 결과만 남긴다(제목·메모 없이).
- 오류 코드(`code`): `remind_invalid`, `start_not_in_weekdays`, `too_many_events`(422). `tools/actions.py`가 HTTP로 바꾼다.
"""

from __future__ import annotations

import logging
import re
from datetime import date as _date
from datetime import time as _time
from typing import TYPE_CHECKING, Any

from my_planner.clock import local, to_iso
from my_planner.domain import Area, RunContext, ToolEvent
from my_planner.store.db import transaction
from my_planner.store.repos.events import (
    ALL_DAY_REMIND_CHOICES,
    EVENTS_MAX,
    REMIND_CHOICES,
    TIMING_FIELDS,
    WEEKDAY_NAMES,
    Event,
    EventFields,
    EventsRepo,
    Occurrence,
    check_range,
    weekday_bit,
    weekday_names,
    weekdays_mask,
)
from my_planner.timefmt import api_time
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import SUPERSEDED, UndoRefused, register_undo
from my_planner.tools.confirmations import (
    confirm_event_create_summary,
    confirm_event_delete_summary,
    confirm_event_update_summary,
    event_line,
    when_label,
)

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.activity import ConfirmsRepo
    from my_planner.store.repos.tasks import TasksRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

TITLE_MAX = 100
NOTE_MAX = 1000
DURATION_MIN, DURATION_MAX = 5, 1440
DEFAULT_REMIND, DEFAULT_ALL_DAY_REMIND = 10, 0  # 5.1: 기본 10분 전, 하루 종일은 그날 09:00

REMIND_INVALID = "remind_invalid"
START_NOT_IN_WEEKDAYS = "start_not_in_weekdays"
TOO_MANY_EVENTS = "too_many_events"

MSG_NO_EVENTS = "일정을 다룰 수 없어요."
MSG_NOT_FOUND = "없는 일정이에요."
MSG_TITLE = "일정 제목은 1~100자로 알려 주세요."
MSG_DATE = "date는 YYYY-MM-DD 형식으로 알려 주세요."
MSG_TIME = "time은 HH:MM 형식(예: 14:00)으로 알려 주세요."
MSG_NEED_TIME = "시각(time)을 알려 주세요. 하루 종일이면 all_day를 true로 보내 주세요."
MSG_ALL_DAY_TIME = "하루 종일 일정에는 시각(time)을 넣지 않아요."
MSG_ALL_DAY = "all_day는 true 또는 false예요."
MSG_DURATION = "duration_min은 5~1440 사이 정수예요."
MSG_REPEAT = "repeat는 none, daily, weekly, monthly 가운데 하나예요."
MSG_WEEKDAYS = "weekdays는 mon, tue, wed, thu, fri, sat, sun 가운데 하나 이상의 목록이에요."
MSG_WEEKDAYS_NOT_WEEKLY = "weekdays는 매주 반복(weekly)에만 써요."
MSG_START_NOT_IN_WEEKDAYS = "첫 날(date)의 요일이 반복 요일(weekdays)에 들어 있어야 해요."
MSG_UNTIL = "repeat_until은 반복 일정에만, 첫 날(date)과 같거나 뒤의 날짜로 알려 주세요."
MSG_REMIND = "remind_min은 0, 10, 30, 60, 1440 가운데 하나이거나 null(알림 없음)이에요."
MSG_REMIND_ALL_DAY = "하루 종일 일정의 알림은 정시(0, 그날 09:00)나 하루 전(1440)만 고를 수 있어요."
MSG_AREA = "area는 career, finance, health, relationships, learning, quality_of_life 가운데 하나예요."
MSG_NOTE = "메모(note)는 1,000자까지 쓸 수 있어요."
MSG_TOO_MANY = "일정은 300개까지 둘 수 있어요. 지난 일정을 지우면 새로 만들 수 있어요."
MSG_RANGE = "기간은 62일까지 볼 수 있어요."
MSG_RANGE_ORDER = "end는 start와 같거나 뒤의 날짜예요."
MSG_SCOPE = "scope는 one(이번만 건너뛰기), following(이후 반복 끝내기), all(모두 지우기) 가운데 하나예요."
MSG_SCOPE_DATE = "scope가 one이나 following이면 그날 일정의 날짜(date)를 알려 주세요."
MSG_NOT_OCCURRENCE = "그날은 이 일정이 있는 날이 아니에요."
MSG_NOTHING = "바꿀 내용을 알려 주세요."
MSG_REMINDER_NOT_FOUND = "닫을 알림이 없어요."
# 5.4: 할 일은 시각을 받지 않는다. 도구 이름은 앱 대화의 두뇌에게만(텔레그램에는 `create_event`가 없고, 사람이 보는
# 글(`/actions` 오류, 텔레그램)에는 도구 이름을 쓰지 않는다)
MSG_TIMED_TASK = "시간이 정해진 일은 앱의 스케줄에서 만들어요."
MSG_TIMED_TASK_APP_BRAIN = "시간이 정해진 일은 스케줄로 만들어요. create_event를 써 주세요."


def timed_task_message(ctx: RunContext) -> str:
    """시각 있는 할 일을 거절하는 문구: 앱 대화의 두뇌에게만 `create_event`를 가리킨다."""
    return MSG_TIMED_TASK_APP_BRAIN if ctx.channel == "app" and ctx.actor == "secretary" else MSG_TIMED_TASK

_HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REPEATS = ("none", "daily", "weekly", "monthly")
_KEEP: Any = object()  # 고치기에서 뺀 칸(그대로), 만들기에서 뺀 `remind_min`(기본값)
# API·도구 칸 이름 → 017 칸 이름
_API_TO_FIELD = {"date": "start_date", "time": "start_time"}
EDITABLE = ("title", "date", "time", "all_day", "duration_min", "repeat", "weekdays", "repeat_until", "remind_min",
            "area", "note")


class EventInvalid(ValueError):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def event_target(event_id: int) -> str:
    return f"event:{event_id}"


def event_day_target(event_id: int, d: _date) -> str:
    """이번만 건너뛰기(5.2): 그날 일정 하나."""
    return f"event:{event_id}:{d.isoformat()}"


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _date_of(v: Any, msg: str = MSG_DATE) -> _date:
    if not isinstance(v, str) or not _ISO_DATE.match(v):
        raise EventInvalid(msg)
    try:
        return _date.fromisoformat(v)
    except ValueError:
        raise EventInvalid(msg) from None


def _time_of(v: Any) -> _time:
    if not isinstance(v, str) or (m := _HHMM.match(v)) is None:
        raise EventInvalid(MSG_TIME)
    return _time(int(m[1]), int(m[2]))


def event_args(e: Event) -> dict[str, Any]:
    """정의 → API·도구 칸 모양(`date`, `time` "HH:MM", `weekdays` 이름 목록). `/actions`·확인 토큰 `args`와 같다."""
    return {
        "title": e.title,
        "date": e.start_date.isoformat(),
        "time": f"{e.start_time:%H:%M}" if e.start_time is not None else None,
        "all_day": e.all_day,
        "duration_min": e.duration_min,
        "repeat": e.repeat,
        "weekdays": weekday_names(e.weekdays),
        "repeat_until": e.repeat_until.isoformat() if e.repeat_until else None,
        "remind_min": e.remind_min,
        "area": e.area.value if e.area is not None else None,
        "note": e.note,
    }


def event_dict(e: Event, skipped: list[_date] | None = None) -> dict[str, Any]:
    """`Event` 모양(`GET /events/{id}`): 정의 전부와 건너뛴 날."""
    return {
        "id": e.id, **event_args(e), "origin": e.origin,
        "skipped_dates": [d.isoformat() for d in (skipped or [])],
        "created_at": to_iso(e.created_at), "updated_at": to_iso(e.updated_at),
    }


def event_result(e: Event) -> dict[str, Any]:
    """동작·두뇌 도구 결과: 정의에서 메모(`note`)를 뺀 것(중복 방지 기록과 두뇌 결과에 메모가 남지 않게)."""
    out = {"id": e.id, **event_args(e), "origin": e.origin, "updated_at": to_iso(e.updated_at)}
    out.pop("note")
    return out


def occurrence_item(o: Occurrence) -> dict[str, Any]:
    """`EventItem`(5.6): 그날 일정 한 줄. `start`·`end`는 UTC datetime(API 경계에서 `Z`가 된다)."""
    return {
        "event_id": o.event_id, "date": o.date.isoformat(), "start": o.start, "end": o.end, "all_day": o.all_day,
        "title": o.title, "area": o.area.value if o.area is not None else None, "remind_min": o.remind_min,
        "repeat": o.repeat, "origin": o.origin,
    }


def _normalize(raw: dict[str, Any]) -> tuple[EventFields, dict[str, Any]]:
    """API 칸 전부(`EDITABLE`) → (017 칸, 정규화한 API 칸). 틀리면 `EventInvalid`(문구, 코드)."""
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > TITLE_MAX:
        raise EventInvalid(MSG_TITLE)
    all_day = raw.get("all_day")
    if not isinstance(all_day, bool):
        raise EventInvalid(MSG_ALL_DAY)
    start_date = _date_of(raw.get("date"))
    start_time: _time | None = None
    if all_day:
        if raw.get("time") is not None:
            raise EventInvalid(MSG_ALL_DAY_TIME)
    else:
        if raw.get("time") is None:
            raise EventInvalid(MSG_NEED_TIME)
        start_time = _time_of(raw["time"])
    duration = raw.get("duration_min")
    if duration is not None and (not _is_int(duration) or not DURATION_MIN <= duration <= DURATION_MAX):
        raise EventInvalid(MSG_DURATION)
    repeat = raw.get("repeat")
    if repeat not in _REPEATS:
        raise EventInvalid(MSG_REPEAT)
    weekdays = raw.get("weekdays")
    mask: int | None = None
    if repeat == "weekly":
        if not isinstance(weekdays, list) or not weekdays or any(w not in WEEKDAY_NAMES for w in weekdays):
            raise EventInvalid(MSG_WEEKDAYS)
        mask = weekdays_mask(weekdays)
        if not mask & weekday_bit(start_date):  # 5.1: RFC 5545의 첫 날(DTSTART)과 `expand()`가 같게
            raise EventInvalid(MSG_START_NOT_IN_WEEKDAYS, START_NOT_IN_WEEKDAYS)
    elif weekdays is not None:
        raise EventInvalid(MSG_WEEKDAYS_NOT_WEEKLY)
    until = raw.get("repeat_until")
    repeat_until: _date | None = None
    if until is not None:
        if repeat == "none":
            raise EventInvalid(MSG_UNTIL)
        repeat_until = _date_of(until, MSG_UNTIL)
        if repeat_until < start_date:
            raise EventInvalid(MSG_UNTIL)
    remind = raw.get("remind_min")
    if remind is not None and (not _is_int(remind) or remind not in REMIND_CHOICES):
        raise EventInvalid(MSG_REMIND, REMIND_INVALID)
    if all_day and remind is not None and remind not in ALL_DAY_REMIND_CHOICES:
        raise EventInvalid(MSG_REMIND_ALL_DAY, REMIND_INVALID)
    area = raw.get("area")
    if area is not None:
        try:
            area = Area(area)
        except ValueError:
            raise EventInvalid(MSG_AREA) from None
    note = raw.get("note")
    note = "" if note is None else note
    if not isinstance(note, str) or len(note) > NOTE_MAX:
        raise EventInvalid(MSG_NOTE)
    fields: EventFields = {
        "title": title.strip(), "all_day": all_day, "start_date": start_date, "start_time": start_time,
        "duration_min": duration, "repeat": repeat, "weekdays": mask, "repeat_until": repeat_until,
        "remind_min": remind, "area": area, "note": note,
    }
    api = {
        "title": title.strip(), "date": start_date.isoformat(),
        "time": f"{start_time:%H:%M}" if start_time is not None else None, "all_day": all_day,
        "duration_min": duration, "repeat": repeat, "weekdays": weekday_names(mask),
        "repeat_until": repeat_until.isoformat() if repeat_until else None, "remind_min": remind,
        "area": area.value if area is not None else None, "note": note,
    }
    return fields, api


def _merged(current: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
    """고치기: 지금 정의에 준 칸을 덮는다. 함께 바뀌어야 하는 칸을 맞춘다(준 칸이 없을 때만).
    하루 종일로 바꾸면 시각을 지우고, 알림이 10·30·60분이면 정시(0)로. 매주가 아니게 되면 요일을, 한 번짜리가 되면
    끝을 지운다. 매주로 바꾸고 요일을 안 주면 첫 날의 요일."""
    out = {**current, **given}
    if given.get("all_day") is True and "time" not in given:
        out["time"] = None
    if out.get("all_day") is True and "remind_min" not in given and out.get("remind_min") not in (
        None, *ALL_DAY_REMIND_CHOICES,
    ):
        out["remind_min"] = DEFAULT_ALL_DAY_REMIND
    if "repeat" in given and given["repeat"] != "weekly" and "weekdays" not in given:
        out["weekdays"] = None
    if out.get("repeat") == "weekly" and out.get("weekdays") is None and "weekdays" not in given:
        out["weekdays"] = _weekday_of(out.get("date"))
    if out.get("repeat") == "none" and "repeat_until" not in given:
        out["repeat_until"] = None
    return out


def _weekday_of(v: Any) -> list[str] | None:
    try:
        return [WEEKDAY_NAMES[_date_of(v).weekday()]]
    except EventInvalid:
        return None


class EventTools:
    """일정 도구 넷(두뇌)과 동작(즉시 갈래). `Tools`의 공통 부품(`_record`, `_request_confirm`, `_chat_confirm`)을 쓴다."""

    events: EventsRepo | None

    if TYPE_CHECKING:
        clock: Clock
        tasks: TasksRepo
        confirms: ConfirmsRepo | None
        tz: Any

        def today(self) -> _date: ...

        def _record(self, ctx: RunContext, kind: str, target: str | None, summary: str | None,
                    undo: dict[str, Any] | None, *, targets: list[str] | None = None) -> None: ...

        def _confirm_first(self, ctx: RunContext) -> bool: ...

        def _request_confirm(self, ctx: RunContext, action: str, args: dict[str, Any], summary: str,
                             button: str) -> dict[str, Any]: ...

        def _chat_confirm(self, ctx: RunContext, args: dict[str, Any], summary: str, button: str,
                          *, action: str = ...) -> dict[str, Any]: ...

    # --- 공통 ---

    def _event(self, id: Any) -> Event | str:
        assert self.events is not None
        e = self.events.get(id) if _is_int(id) else None
        return e if e is not None else MSG_NOT_FOUND

    def _event_change(
        self, ctx: RunContext, kind: str, e: Event, undo: dict[str, Any] | None, *, target: str | None = None,
        day: _date | None = None,
    ) -> None:
        """트랜잭션 안에서: 도구 호출 기록(`tool_events_log`), 활동 한 행, 확인 문구 이벤트. 메모(`note`)는 넣지 않는다."""
        data: dict[str, Any] = {"event_id": e.id, "title": e.title}
        if kind == "event_created":
            data["when"] = when_label(event_args(e))
        if day is not None:
            data["date"] = day.isoformat()
        self.tasks.log_tool_event(ctx.run_id, ctx.conversation_id, None, kind, inbound_id=ctx.inbound_id, data=data)
        self._record(ctx, kind, target or event_target(e.id), event_line(kind, data), undo)
        ctx.events.append(ToolEvent(kind, None, data))

    def _confirm(self, ctx: RunContext, action: str, args: dict[str, Any], summary: str, button: str) -> dict[str, Any]:
        """두뇌가 부른 확인: 회차 차례는 회차 토큰(체크인 상세 `ui_confirm`), 사용자 차례는 답 스트림의 확인 카드."""
        if self.confirms is None:
            return _err(MSG_NO_EVENTS)
        if ctx.run_turn and ctx.run_id is not None:
            return self._request_confirm(ctx, action, args, summary, button)
        return self._chat_confirm(ctx, args, summary, button, action=action)

    @staticmethod
    def _invalid(e: EventInvalid) -> dict[str, Any]:
        return {"error": e.message, "code": e.code} if e.code else _err(e.message)

    def _by_brain(self, ctx: RunContext) -> bool:
        """두뇌가 부른 변경(확인 토큰으로 적용하는 것이 아니다)."""
        return ctx.actor == "secretary" and ctx.risk != "confirm"

    # --- 두뇌 도구 ---

    @_tool
    def list_events(self, ctx: RunContext, start: Any = None, end: Any = None) -> dict[str, Any]:
        """기간(현지 날짜, 포함, 62일까지) 그날 일정. 시각은 현지 "HH:MM"(두뇌가 받는 결과)."""
        if self.events is None:
            return _err(MSG_NO_EVENTS)
        try:
            lo = _date_of(start, "start는 YYYY-MM-DD 형식으로 알려 주세요.")
            hi = _date_of(end, "end는 YYYY-MM-DD 형식으로 알려 주세요.")
        except EventInvalid as e:
            return _err(e.message)
        try:
            check_range(lo, hi)
        except ValueError as e:
            return _err(MSG_RANGE if str(e) == "range_too_long" else MSG_RANGE_ORDER)
        items = []
        for o in self.events.occurrences(lo, hi):
            items.append({
                "id": o.event_id, "date": o.date.isoformat(), "all_day": o.all_day,
                "time": f"{local(o.start, self.tz):%H:%M}" if o.start else None,
                "end_time": f"{local(o.end, self.tz):%H:%M}" if o.end else None,
                # `ui_events`에 그대로 넘길 수 있게 UTC ISO(`Z`)도 싣는다
                "start": api_time(o.start) if o.start else None, "end": api_time(o.end) if o.end else None,
                "title": o.title, "area": o.area.value if o.area is not None else None, "repeat": o.repeat,
                "remind_min": o.remind_min, "origin": o.origin,
            })
        log.info("events_listed", extra={"count": len(items)})
        return {"items": items}

    @_tool
    def create_event(
        self, ctx: RunContext, title: Any = None, date: Any = None, time: Any = None, all_day: Any = None,
        duration_min: Any = None, repeat: Any = None, weekdays: Any = None, repeat_until: Any = None,
        remind_min: Any = _KEEP, area: Any = None, note: Any = None,
    ) -> dict[str, Any]:
        """일정 만들기. `remind_min`을 빼면 10분 전(하루 종일이면 그날 09:00, 0). 매주인데 `weekdays`를 빼면 첫 날의 요일.
        두뇌가 만들면 `origin = 'chat'`. 회차 차례에서는 확인 토큰만 만든다(5.5). 되돌릴 수 있다."""
        if self.events is None:
            return _err(MSG_NO_EVENTS)
        raw = {
            "title": title, "date": date, "time": time, "all_day": False if all_day is None else all_day,
            "duration_min": duration_min, "repeat": "none" if repeat is None else repeat,
            "weekdays": weekdays, "repeat_until": repeat_until, "area": area, "note": note,
            "remind_min": (DEFAULT_ALL_DAY_REMIND if all_day is True else DEFAULT_REMIND)
            if remind_min is _KEEP else remind_min,
        }
        if raw["repeat"] == "weekly" and weekdays is None:
            raw["weekdays"] = _weekday_of(date)
        try:
            fields, args = _normalize(raw)
        except EventInvalid as e:
            return self._invalid(e)
        if self.events.count_live() >= EVENTS_MAX:
            return {"error": MSG_TOO_MANY, "code": TOO_MANY_EVENTS}
        if self._confirm_first(ctx):  # 회차 차례(A1): 비서가 먼저 꺼낸 일정은 확인 뒤에(ui_confirm)
            when = when_label(args)
            return self._request_confirm(
                ctx, "create_event", args, confirm_event_create_summary(args["title"], when),
                f"일정 추가: {args['title']}",
            )
        origin = "chat" if ctx.actor == "secretary" or ctx.risk == "confirm" else "user"
        with transaction(self.events.conn):
            e = self.events.create({**fields, "origin": origin}, self.clock.now())
            self._event_change(ctx, "event_created", e, {"event_id": e.id})
        log.info("event_created", extra={"event_id": e.id, "origin": origin})
        return event_result(e)

    @_tool
    def update_event(self, ctx: RunContext, id: Any = None, **fields: Any) -> dict[str, Any]:
        """바꿀 칸만. 두뇌가 날짜·시각·하루 종일·길이·반복·알림을 바꾸면 확인(5.5). 바뀌는 것이 없으면 `already`."""
        if self.events is None:
            return _err(MSG_NO_EVENTS)
        unknown = set(fields) - set(EDITABLE)
        if unknown:
            return _err(f"바꿀 수 없는 항목이 있어요: {', '.join(sorted(unknown))}")
        if not fields:
            return _err(MSG_NOTHING)
        e = self._event(id)
        if isinstance(e, str):
            return _err(e)
        current = event_args(e)
        try:
            new_fields, new_args = _normalize(_merged(current, fields))
        except EventInvalid as err:
            return self._invalid(err)
        changed = {k for k in EDITABLE if new_args[k] != current[k]}
        if not changed:
            return {**event_result(e), "already": True}
        timing = {_API_TO_FIELD.get(k, k) for k in changed} & TIMING_FIELDS
        if timing and self._by_brain(ctx):
            args = {"id": e.id, **{k: new_args[k] for k in EDITABLE if k in fields or k in changed}}
            return self._confirm(
                ctx, "update_event", args,
                confirm_event_update_summary(e.title, when_label(new_args), new_args, current),
                f"일정 변경: {e.title}",
            )
        before = {k: current[k] for k in changed}
        update: EventFields = {}
        for k in changed:
            f = _API_TO_FIELD.get(k, k)
            update[f] = new_fields[f]  # type: ignore[literal-required]
        with transaction(self.events.conn):
            got = self.events.update(e.id, update, self.clock.now())
            self._event_change(ctx, "event_updated", got, {"event_id": e.id, "before": before})
        log.info("event_updated", extra={"event_id": e.id, "timing": bool(timing)})
        return event_result(got)

    @_tool
    def delete_event(self, ctx: RunContext, id: Any = None, scope: Any = None, date: Any = None) -> dict[str, Any]:
        """`one`: 이번만 건너뛰기(`date` 필요), `following`: 그날부터 반복 끝내기(`date` 필요, 첫 날이면 지우기와 같다),
        `all`: 모두 지우기. 한 번짜리 일정은 scope와 상관없이 지운다. 두뇌가 부르면 언제나 확인(5.5)."""
        if self.events is None:
            return _err(MSG_NO_EVENTS)
        if scope not in ("one", "following", "all"):
            return _err(MSG_SCOPE)
        e = self._event(id)
        if isinstance(e, str):
            return _err(e)
        effective = "all" if e.repeat == "none" else scope
        day: _date | None = None
        if effective in ("one", "following"):
            if date is None:
                return _err(MSG_SCOPE_DATE)
            try:
                day = _date_of(date)
            except EventInvalid as err:
                return _err(err.message)
            if effective == "one" and not self.events.has_occurrence(e, day):
                return _err(MSG_NOT_OCCURRENCE)
            if effective == "following" and day <= e.start_date:
                effective = "all"  # 첫 날부터 끝내기 = 지우기(5.2)
        if effective == "one" and day is not None and day in self.events.skipped_dates(e.id):
            return {"id": e.id, "scope": "one", "date": day.isoformat(), "already": True}
        if effective == "following" and day is not None and e.repeat_until is not None and e.repeat_until < day:
            return {"id": e.id, "scope": "following", "date": day.isoformat(), "already": True}
        if self._by_brain(ctx):
            args: dict[str, Any] = {"id": e.id, "scope": scope}
            if date is not None:
                args["date"] = day.isoformat() if day is not None else date
            return self._confirm(
                ctx, "delete_event", args, confirm_event_delete_summary(effective, e.title, day),
                f"일정 지우기: {e.title}",
            )
        now = self.clock.now()
        with transaction(self.events.conn):
            if effective == "one":
                assert day is not None
                self.events.skip(e.id, day)
                self._event_change(ctx, "event_skipped", e, {"event_id": e.id, "date": day.isoformat()},
                                   target=event_day_target(e.id, day), day=day)
            elif effective == "following":
                assert day is not None
                prev = e.repeat_until.isoformat() if e.repeat_until else None
                got = self.events.end_repeat(e.id, day, now)
                assert got is not None
                self._event_change(ctx, "event_repeat_ended", got, {"event_id": e.id, "repeat_until": prev}, day=day)
            else:
                self.events.delete(e.id, now)
                self._event_change(ctx, "event_deleted", e, {"event_id": e.id})
        log.info("event_deleted", extra={"event_id": e.id, "scope": effective})
        out: dict[str, Any] = {"id": e.id, "scope": effective}
        if day is not None and effective != "all":
            out["date"] = day.isoformat()
        return out

    # --- 즉시 갈래 동작(두뇌 도구 목록에 없다) ---

    @_tool
    def dismiss_missed_reminder(self, ctx: RunContext, event_id: Any = None, date: Any = None) -> dict[str, Any]:
        """오늘 화면의 "놓친 알림"·"알림을 못 보냈어요" 줄을 닫는다(`event_reminders.dismissed_at`). 활동은 없다."""
        if self.events is None:
            return _err(MSG_NO_EVENTS)
        try:
            day = _date_of(date)
        except EventInvalid as e:
            return _err(e.message)
        if not _is_int(event_id):
            return _err(MSG_REMINDER_NOT_FOUND)
        conn = self.events.conn
        row = conn.execute(
            "SELECT dismissed_at FROM event_reminders WHERE event_id = ? AND occurrence_date = ? "
            "AND outcome IN ('missed', 'failed', 'skipped')", (event_id, day.isoformat()),
        ).fetchone()
        if row is None:
            return _err(MSG_REMINDER_NOT_FOUND)
        if row[0] is not None:
            return {"event_id": event_id, "date": day.isoformat(), "already": True}
        with transaction(conn):
            conn.execute(
                "UPDATE event_reminders SET dismissed_at = ? WHERE event_id = ? AND occurrence_date = ?",
                (to_iso(self.clock.now()), event_id, day.isoformat()),
            )
        log.info("missed_reminder_dismissed", extra={"event_id": event_id})
        return {"event_id": event_id, "date": day.isoformat(), "dismissed": True}


# --- 되돌리기 ---


def _fields_from_args(before: dict[str, Any]) -> EventFields:
    """활동 `undo_json.before`(API 칸 모양) → 017 칸."""
    out: EventFields = {}
    for k, v in before.items():
        f = _API_TO_FIELD.get(k, k)
        if v is None:
            out[f] = None  # type: ignore[literal-required]
        elif f in ("start_date", "repeat_until"):
            out[f] = _date.fromisoformat(v)  # type: ignore[literal-required]
        elif f == "start_time":
            out[f] = _time.fromisoformat(v)  # type: ignore[literal-required]
        elif f == "weekdays":
            out[f] = weekdays_mask(v)  # type: ignore[literal-required]
        elif f == "area":
            out[f] = Area(v)  # type: ignore[literal-required]
        else:
            out[f] = v  # type: ignore[literal-required]
    return out


def _undo_event_created(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.events is not None
    if tools.events.get(undo["event_id"]) is None:
        return SUPERSEDED
    tools.events.delete(undo["event_id"], tools.clock.now())
    return None


def _undo_event_updated(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """바뀐 칸만 이전 값으로(시각이 돌아가면 앞으로의 알림 행도 다시 지운다)."""
    assert tools.events is not None
    if tools.events.get(undo["event_id"]) is None:
        return SUPERSEDED
    tools.events.update(undo["event_id"], _fields_from_args(undo["before"]), tools.clock.now())
    return None


def _undo_event_skipped(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.events is not None
    if tools.events.get(undo["event_id"]) is None:
        return SUPERSEDED
    tools.events.unskip(undo["event_id"], _date.fromisoformat(undo["date"]))
    return None


def _undo_event_repeat_ended(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.events is not None
    if tools.events.get(undo["event_id"]) is None:
        return SUPERSEDED
    prev = undo["repeat_until"]
    tools.events.update(
        undo["event_id"], {"repeat_until": _date.fromisoformat(prev) if prev else None}, tools.clock.now()
    )
    return None


def _undo_event_deleted(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """되살린다(300개 상한은 지킨다)."""
    events = tools.events
    assert events is not None
    if events.count_live() >= EVENTS_MAX:
        raise UndoRefused(TOO_MANY_EVENTS, MSG_TOO_MANY)
    return None if events.restore(undo["event_id"]) else SUPERSEDED


for _kind, _handler in (
    ("event_created", _undo_event_created),
    ("event_updated", _undo_event_updated),
    ("event_skipped", _undo_event_skipped),
    ("event_repeat_ended", _undo_event_repeat_ended),
    ("event_deleted", _undo_event_deleted),
):
    register_undo(_kind, _handler)


_UI_EVENT_KEYS = ("event_id", "date", "start", "end", "all_day", "title", "area", "remind_min", "repeat", "origin")


def ui_event_items(items: Any) -> Any:
    """`ui_events` props의 `items`: `list_events` 항목을 그대로 받는다(`id` → `event_id`, `time`·`end_time` 등
    카탈로그에 없는 칸은 뺀다). 목록이 아니면 그대로 둬 스키마 검사가 알린다."""
    if not isinstance(items, list):
        return items
    out = []
    for it in items:
        if isinstance(it, dict):
            it = {**it, "event_id": it.get("event_id", it.get("id"))}
            it = {k: it[k] for k in _UI_EVENT_KEYS if k in it}
        out.append(it)
    return out


def today_missed_reminders(events: EventsRepo | None, d: _date, boundary: _time) -> list[dict[str, Any]]:
    """오늘(논리적 날짜) 그날 일정 가운데 `missed`·`failed`·`skipped`이고 닫지 않은 알림(`/today.missed_reminders`, 5.3·5.6).
    새벽 일정은 `today_events`와 같은 날에 든다."""
    if events is None:
        return []
    occ = events.on_logical_date(d, boundary)
    got = events.open_unsent_reminders([(o.event_id, o.date) for o in occ])
    return [
        {"event_id": o.event_id, "date": o.date.isoformat(), "start": o.start, "title": o.title,
         "outcome": got[(o.event_id, o.date)]}
        for o in occ if (o.event_id, o.date) in got
    ]


def today_events(events: EventsRepo | None, d: _date, boundary: _time) -> list[Occurrence]:
    """논리적 날짜 `d`의 그날 일정(오늘 화면 `/today.events`, 앞머리). 저장소가 없으면 빈 목록."""
    return events.on_logical_date(d, boundary) if events is not None else []


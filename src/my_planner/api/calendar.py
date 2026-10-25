"""아이폰 캘린더 구독 주소 (SP9 스펙 5.7, 9.7): `GET /calendar.ics?key=`, `GET`·`POST /settings/calendar`.

- `.ics`는 손으로 쓴다(새 의존성 없음): CRLF, 75바이트 접기, `, ; \\`와 줄바꿈 이스케이프. 일정마다 `VEVENT` 하나,
  반복은 `RRULE`, 건너뛴 날은 `EXDATE`. 제목만 넣는다: `note`, 영역, `VALARM`은 넣지 않는다(기기 밖으로 나가는 사본이고
  알림은 앱이 한다).
- 캘린더 키는 API 토큰과 다른 32바이트 무작위 값이다. 아이폰 캘린더는 머리글을 못 보내서 주소에 들어간다. 이 경로만
  `auth` 미들웨어의 Bearer 검사에서 빠지고(`server.auth`), 여기서 `hmac.compare_digest`로 비교한다. 틀리면 401이고
  `AuthLimiter`에 센다. 키는 `app_state.calendar_key`에 평문으로 둔다(설정 화면이 주소를 다시 보여 줘야 해서, 5.7).
  응답에 `Cache-Control: no-store`. 키는 로그, 오류 문구에 쓰지 않는다.
"""

from __future__ import annotations

import hmac
import logging
import re
import secrets
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from aiohttp import web
from pydantic import ValidationError

from my_planner.api.actions import BAD_BODY, read_json_object
from my_planner.api.models import (
    CalendarPutBody,
    CalendarSettings,
    dump,
    error_response,
)
from my_planner.store.repos.events import WEEKDAY_NAMES, Event, EventsRepo, weekday_bit
from my_planner.store.repos.state import CALENDAR_KEY_KEY, StateRepo
from my_planner.tools.actions import ActionRequest

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

log = logging.getLogger(__name__)

CALENDAR_PATH = "/api/v1/calendar.ics"
CALENDAR_KEY_BYTES = 32
FOLD_OCTETS = 75
PRODID = "-//my-planner//schedule//KO"
_BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# 매달 29~31일은 그 달 마지막 날로 옮긴다(5.1): 후보 날짜 중 마지막(BYSETPOS=-1)
_MONTH_END = {29: "28,29", 30: "28,29,30", 31: "28,29,30,31"}
UNAUTHORIZED = "인증이 필요해요."


# --- .ics 쓰기 ---


def _escape(text: str) -> str:
    """TEXT 값(RFC 5545 3.3.11): `\\ ; ,`와 줄바꿈, 그 밖의 제어 문자는 공백."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub(" ", text)  # 줄바꿈·탭 말고 제어 문자는 RFC TEXT에 못 쓴다: 엄격한 파서는 VEVENT를 버린다
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """75바이트(줄 끝 CRLF 빼고)를 넘으면 접는다: 잇는 줄은 공백 하나로 시작하고 그 공백도 센다. 글자 한가운데서 자르지 않는다."""
    out: list[str] = []
    cur, size, limit = "", 0, FOLD_OCTETS
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(cur)
            cur, size, limit = " ", 1, FOLD_OCTETS
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def _local(d: date, t: time) -> str:
    return f"{d:%Y%m%d}T{t:%H%M%S}"


def _vtimezone(tz: str) -> list[str]:
    """고정 오프셋 한 덩어리. 서머타임이 없는 시간대(Asia/Seoul)를 위한 것이라 기준일(2026-01-01)의 오프셋을 쓴다."""
    off = datetime(2026, 1, 1, tzinfo=ZoneInfo(tz)).utcoffset() or timedelta(0)
    sign = "+" if off >= timedelta(0) else "-"
    mins = abs(int(off.total_seconds())) // 60
    o = f"{sign}{mins // 60:02d}{mins % 60:02d}"
    name = datetime(2026, 1, 1, tzinfo=ZoneInfo(tz)).tzname() or tz
    return [
        "BEGIN:VTIMEZONE", f"TZID:{tz}", "BEGIN:STANDARD", "DTSTART:19700101T000000",
        f"TZOFFSETFROM:{o}", f"TZOFFSETTO:{o}", f"TZNAME:{name}", "END:STANDARD", "END:VTIMEZONE",
    ]


def _rrule(e: Event, tz: str) -> str | None:
    if e.repeat == "none":
        return None
    if e.repeat == "daily":
        parts = ["FREQ=DAILY"]
    elif e.repeat == "weekly":
        mask = e.weekdays or weekday_bit(e.start_date)
        parts = ["FREQ=WEEKLY", "BYDAY=" + ",".join(_BYDAY[i] for i in range(len(WEEKDAY_NAMES)) if mask & (1 << i))]
    else:
        day = e.start_date.day
        parts = ["FREQ=MONTHLY"]
        parts += [f"BYMONTHDAY={_MONTH_END[day]}", "BYSETPOS=-1"] if day in _MONTH_END else [f"BYMONTHDAY={day}"]
    if e.repeat_until is not None:
        if e.all_day:  # DTSTART가 DATE면 UNTIL도 DATE(RFC 5545 3.3.10)
            parts.append(f"UNTIL={e.repeat_until:%Y%m%d}")
        else:  # 끝 날의 끝(현지 23:59:59)을 UTC로
            end = datetime.combine(e.repeat_until, time(23, 59, 59), ZoneInfo(tz)).astimezone(UTC)
            parts.append(f"UNTIL={end:%Y%m%dT%H%M%SZ}")
    return "RRULE:" + ";".join(parts)


def _vevent(e: Event, skips: set[date], tz: str) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:event-{e.id}@my-planner", f"DTSTAMP:{e.updated_at.astimezone(UTC):%Y%m%dT%H%M%SZ}"]
    if e.all_day:
        lines.append(f"DTSTART;VALUE=DATE:{e.start_date:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{e.start_date + timedelta(days=1):%Y%m%d}")
    else:
        assert e.start_time is not None
        lines.append(f"DTSTART;TZID={tz}:{_local(e.start_date, e.start_time)}")
        if e.duration_min is not None:
            end = datetime.combine(e.start_date, e.start_time, ZoneInfo(tz)).astimezone(UTC) + timedelta(minutes=e.duration_min)
            end_local = end.astimezone(ZoneInfo(tz))
            lines.append(f"DTEND;TZID={tz}:{_local(end_local.date(), end_local.time())}")
    if (rule := _rrule(e, tz)) is not None:
        lines.append(rule)
    if skips:
        days = sorted(skips)
        if e.all_day:
            lines.append("EXDATE;VALUE=DATE:" + ",".join(f"{d:%Y%m%d}" for d in days))
        else:
            assert e.start_time is not None
            lines.append(f"EXDATE;TZID={tz}:" + ",".join(_local(d, e.start_time) for d in days))
    lines.append(f"SUMMARY:{_escape(e.title)}")
    lines.append("END:VEVENT")
    return lines


def render_ics(events: list[Event], skips: dict[int, set[date]], tz: str) -> str:
    """살아 있는 일정 → iCalendar 본문(CRLF, 75바이트 접기). 제목만: 메모·영역·알림은 넣지 않는다."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "X-WR-CALNAME:my-planner"]
    if any(not e.all_day for e in events):
        lines += _vtimezone(tz)
    for e in events:
        lines += _vevent(e, skips.get(e.id, set()), tz)
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


# --- 키와 주소 ---


def new_key() -> str:
    return secrets.token_urlsafe(CALENDAR_KEY_BYTES)


def key_ok(given: str | None, stored: str | None) -> bool:
    """저장한 키가 없거나 빈 값이면 언제나 거절. 비교는 상수 시간."""
    if not given or not stored:
        return False
    return hmac.compare_digest(given.encode("utf-8"), stored.encode("utf-8"))


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TS_NET = re.compile(r"\.ts\.net(:\d+)?$")


def subscribe_url(request: web.Request, key: str) -> str:
    """`{BE 기준 주소}/api/v1/calendar.ics?key=…`. 주소는 요청의 `Host`(`tailscale serve`가 쓴 이름)에서 가져온다. scheme은
    `X-Forwarded-Proto`, 없으면 `*.ts.net`이면 https, 그 밖에는 요청 그대로."""
    host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip() or request.host
    proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    scheme = proto or ("https" if _TS_NET.search(host) else request.scheme)
    return f"{scheme}://{host}{CALENDAR_PATH}?key={key}"


def get_calendar_settings(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    key = StateRepo(conn, deps.clock).get(CALENDAR_KEY_KEY)
    return dump(CalendarSettings, {"url": subscribe_url(request, key) if key else None})


async def post_calendar_settings(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    """`{"rotate": false}`: 키가 없으면 만들고 있으면 그대로. `{"rotate": true}`: 새 키로 바꾼다(이전 주소는 바로 끊김)."""
    body = await read_json_object(request)
    if body is None:
        return error_response(400, "invalid_request", BAD_BODY)
    try:
        req = CalendarPutBody.model_validate(body)
    except ValidationError:
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None
    res = deps.dispatcher.apply_action(ActionRequest(
        "calendar_key_rotate" if req.rotate else "calendar_key_create", {}, actor="user", channel="app", endpoint="push",
    ))
    if res.status != "applied":
        return error_response(400, "invalid_request", BAD_BODY)
    return web.json_response(dump(CalendarSettings, {"url": subscribe_url(request, res.body["result"]["key"])}))


# --- .ics ---


def _no_store(resp: web.StreamResponse) -> web.StreamResponse:
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def get_calendar_ics(request: web.Request) -> web.StreamResponse:
    from my_planner.api.server import DEPS_KEY, LIMITER_KEY

    deps = request.app[DEPS_KEY]
    limiter = request.app[LIMITER_KEY]
    assert deps.read_conn is not None
    conn = deps.read_conn()
    try:
        stored = StateRepo(conn, deps.clock).get(CALENDAR_KEY_KEY)
        if not key_ok(request.query.get("key"), stored):
            if limiter.record_failure():
                log.warning("api_auth_blocked")
            log.info("api_auth_failed", extra={"route": CALENDAR_PATH})
            return _no_store(error_response(401, "unauthorized", UNAUTHORIZED))  # 이유를 더 적지 않는다
        repo = EventsRepo(conn, deps.clock, deps.settings.timezone)
        text = render_ics(repo.live(), repo.skips(), deps.settings.timezone)
    finally:
        conn.close()
    return _no_store(web.Response(body=text.encode("utf-8"), content_type="text/calendar", charset="utf-8"))

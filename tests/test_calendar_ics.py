"""아이폰 캘린더 구독 `.ics` (SP9 스펙 5.7). 시험 날짜 2026-10-26(월)~, 매달 끝날 2027-01-31."""

from datetime import UTC, date, datetime, time

import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst
from test_events import MON, NOW, TUE, _event

from my_planner.api.calendar import render_ics
from my_planner.store.repos.events import EventsRepo

TZ = "Asia/Seoul"
START = kst(2026, 10, 24, 13, 0)


def _lines(ics: str) -> list[str]:
    """접힌 줄을 펴서 CRLF로 나눈다."""
    assert ics.endswith("\r\n")
    return ics.replace("\r\n ", "").split("\r\n")[:-1]


def _vevent(ics: str) -> list[str]:
    ls = _lines(ics)
    return ls[ls.index("BEGIN:VEVENT"): ls.index("END:VEVENT") + 1]


def _render(*events, skips=None):
    return render_ics(list(events), skips or {}, TZ)


def test_rrule_daily_weekly_monthly():
    daily = _vevent(_render(_event(repeat="daily")))
    assert "RRULE:FREQ=DAILY" in daily
    assert "DTSTART;TZID=Asia/Seoul:20261026T140000" in daily
    weekly = _vevent(_render(_event(repeat="weekly", weekdays=1 | 4 | 16)))
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR" in weekly
    only_start_day = _vevent(_render(_event(repeat="weekly", weekdays=None, start_date=TUE)))
    assert "RRULE:FREQ=WEEKLY;BYDAY=TU" in only_start_day
    monthly = _vevent(_render(_event(repeat="monthly", start_date=date(2026, 11, 15))))
    assert "RRULE:FREQ=MONTHLY;BYMONTHDAY=15" in monthly
    assert not any(l.startswith("RRULE") for l in _vevent(_render(_event())))


@pytest.mark.parametrize(
    ("day", "rule"),
    [(31, "BYMONTHDAY=28,29,30,31;BYSETPOS=-1"), (30, "BYMONTHDAY=28,29,30;BYSETPOS=-1"), (29, "BYMONTHDAY=28,29;BYSETPOS=-1"),
     (28, "BYMONTHDAY=28")],
)
def test_monthly_31_bysetpos(day, rule):
    ev = _vevent(_render(_event(repeat="monthly", start_date=date(2027, 1, day))))
    assert f"RRULE:FREQ=MONTHLY;{rule}" in ev


def test_exdate_for_skips():
    e = _event(repeat="daily")
    ev = _vevent(_render(e, skips={1: {date(2026, 10, 29), date(2026, 10, 27)}, 99: {MON}}))
    assert "EXDATE;TZID=Asia/Seoul:20261027T140000,20261029T140000" in ev
    allday = _event(id=2, all_day=True, start_time=None, remind_min=0, repeat="daily")
    ev = _vevent(_render(allday, skips={2: {TUE}}))
    assert "EXDATE;VALUE=DATE:20261027" in ev


def test_until_utc():
    ev = _vevent(_render(_event(repeat="daily", repeat_until=date(2026, 10, 30))))
    # 마지막 날 끝(23:59:59 KST) = 14:59:59Z
    assert "RRULE:FREQ=DAILY;UNTIL=20261030T145959Z" in ev
    ev = _vevent(_render(_event(all_day=True, start_time=None, remind_min=0, repeat="daily", repeat_until=date(2026, 10, 30))))
    assert "RRULE:FREQ=DAILY;UNTIL=20261030" in ev  # DTSTART가 DATE면 UNTIL도 DATE(RFC 5545 3.3.10)


def test_all_day_value_date():
    ev = _vevent(_render(_event(all_day=True, start_time=None, remind_min=0)))
    assert "DTSTART;VALUE=DATE:20261026" in ev
    assert "DTEND;VALUE=DATE:20261027" in ev
    assert not any("TZID" in l for l in ev)


def test_timed_end_from_duration():
    ev = _vevent(_render(_event(start_time=time(23, 30), duration_min=60)))
    assert "DTSTART;TZID=Asia/Seoul:20261026T233000" in ev
    assert "DTEND;TZID=Asia/Seoul:20261027T003000" in ev
    assert not any(l.startswith("DTEND") for l in _vevent(_render(_event())))


def test_tzid_and_vtimezone():
    ics = _render(_event())
    ls = _lines(ics)
    assert ls[:2] == ["BEGIN:VCALENDAR", "VERSION:2.0"]
    assert ls[-1] == "END:VCALENDAR"
    tz = ls[ls.index("BEGIN:VTIMEZONE"): ls.index("END:VTIMEZONE") + 1]
    assert "TZID:Asia/Seoul" in tz and "TZOFFSETFROM:+0900" in tz and "TZOFFSETTO:+0900" in tz
    assert ics.count("BEGIN:VTIMEZONE") == 1
    assert _render(_event(all_day=True, start_time=None, remind_min=0)).count("VTIMEZONE") == 0  # 시각 있는 일정이 없으면 생략
    assert _render(_event(), _event(id=2)).count("BEGIN:VTIMEZONE") == 1


def test_no_note_no_area_no_valarm():
    from my_planner.domain import Area

    secret = "비밀메모-9f3"
    ics = _render(_event(note=secret, area=next(iter(Area)), remind_min=10))
    assert secret not in ics
    assert "VALARM" not in ics and "CATEGORIES" not in ics and "DESCRIPTION" not in ics
    assert "SUMMARY:치과" in _vevent(ics)
    assert "UID:event-1@my-planner" in _vevent(ics)
    assert f"DTSTAMP:{NOW:%Y%m%dT%H%M%SZ}" in _vevent(ics)


def test_escape_and_fold_75_octets_crlf():
    title = "가,나;다\\라\n마" + "한" * 60  # 한글은 3바이트
    ics = _render(_event(title=title))
    assert "\n" not in ics.replace("\r\n", "")
    for raw in ics.split("\r\n"):
        assert len(raw.encode()) <= 75
    assert any(l.startswith(" ") for l in ics.split("\r\n"))  # 접힌 줄
    summary = next(l for l in _vevent(ics) if l.startswith("SUMMARY"))
    assert summary == "SUMMARY:" + "가\\,나\\;다\\\\라\\n마" + "한" * 60
    ics.encode("utf-8").decode("utf-8")  # 글자 한가운데서 자르지 않았다


def test_empty_calendar_is_valid():
    ls = _lines(_render())
    assert ls[0] == "BEGIN:VCALENDAR" and ls[-1] == "END:VCALENDAR" and "BEGIN:VEVENT" not in ls
    assert datetime(2026, 1, 1, tzinfo=UTC)  # 사용 안 함 경고 방지


# --- HTTP ---


async def _key(env) -> str:
    resp = await env.post("/settings/calendar", json={"rotate": False})
    assert resp.status == 200
    return (await resp.json())["url"].split("key=")[1]


async def test_settings_calendar_create_get_and_url_shape(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        assert await (await env.get("/settings/calendar")).json() == {"url": None}
        resp = await env.post("/settings/calendar", json={"rotate": False})
        url = (await resp.json())["url"]
        assert url.endswith("/api/v1/calendar.ics?key=" + url.split("key=")[1])
        assert url.startswith("http")
        assert len(url.split("key=")[1]) >= 43
        # 다시 눌러도(회전 아님) 같은 주소
        assert (await (await env.post("/settings/calendar", json={"rotate": False})).json())["url"] == url
        assert (await (await env.get("/settings/calendar")).json())["url"] == url


async def test_ics_served_with_key_only(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        key = await _key(env)
        EventsRepo(env.conn, env.clock, TZ).create({"title": "치과", "start_date": MON, "start_time": time(14, 0), "origin": "user"}, START)
        resp = await env.get(f"/api/v1/calendar.ics?key={key}", token=None)  # Bearer 없이
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "text/calendar; charset=utf-8"
        assert resp.headers["Cache-Control"] == "no-store"
        body = await resp.text()
        assert "SUMMARY:치과" in body and body.endswith("\r\n")


async def test_rotate_breaks_old_url(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        old = await _key(env)
        resp = await env.post("/settings/calendar", json={"rotate": True})
        new = (await resp.json())["url"].split("key=")[1]
        assert new != old
        assert (await env.get(f"/api/v1/calendar.ics?key={old}", token=None)).status == 401
        assert (await env.get(f"/api/v1/calendar.ics?key={new}", token=None)).status == 200

"""스케줄 펼치기와 저장소 (SP9 스펙 5.1, 5.2, 5.3 일부). 시험 날짜 2026-10-26(월)~2026-11-01(일), 매달 끝날 2027-01-31."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from my_planner.clock import FakeClock
from my_planner.domain import Area
from my_planner.store.repos.events import Event, EventsRepo, expand

TZ = "Asia/Seoul"
MON, TUE, WED, THU, FRI, SAT, SUN = (date(2026, 10, 26) + timedelta(days=i) for i in range(7))
NOW = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)  # 월요일 09:00 KST


def _event(**kw) -> Event:
    base = {
        "id": 1, "title": "치과", "all_day": False, "start_date": MON, "start_time": time(14, 0), "duration_min": None,
        "repeat": "none", "weekdays": None, "repeat_until": None, "remind_min": 10, "area": None, "note": "",
        "origin": "user", "from_task_id": None, "created_at": NOW, "updated_at": NOW, "deleted_at": None,
    }
    return Event(**{**base, **kw})


def _dates(occ):
    return [o.date for o in occ]


def test_daily():
    e = _event(repeat="daily", start_date=TUE)
    occ = expand(e, MON, SUN, tz=TZ, skips=set())
    assert _dates(occ) == [TUE, WED, THU, FRI, SAT, SUN]
    assert occ[0].start == datetime(2026, 10, 27, 5, 0, tzinfo=UTC)  # 14:00 KST
    assert occ[0].remind_at == datetime(2026, 10, 27, 4, 50, tzinfo=UTC)


def test_weekly_mon_wed_fri():
    e = _event(repeat="weekly", weekdays=1 | 4 | 16, start_time=time(10, 0))
    occ = expand(e, MON, SUN + timedelta(days=7), tz=TZ, skips=set())
    assert _dates(occ) == [MON, WED, FRI, MON + timedelta(7), WED + timedelta(7), FRI + timedelta(7)]


def test_monthly_31_moves_to_feb_28_2027():
    e = _event(repeat="monthly", start_date=date(2027, 1, 31))
    occ = expand(e, date(2027, 1, 1), date(2027, 3, 3), tz=TZ, skips=set())
    assert _dates(occ) == [date(2027, 1, 31), date(2027, 2, 28)]
    occ = expand(e, date(2027, 3, 1), date(2027, 4, 30), tz=TZ, skips=set())
    assert _dates(occ) == [date(2027, 3, 31), date(2027, 4, 30)]  # 다음 달은 다시 31일


def test_repeat_until_inclusive():
    e = _event(repeat="daily", repeat_until=THU)
    assert _dates(expand(e, MON, SUN, tz=TZ, skips=set())) == [MON, TUE, WED, THU]


def test_skip_removes_one_day():
    e = _event(repeat="daily")
    assert _dates(expand(e, MON, WED, tz=TZ, skips={TUE})) == [MON, WED]


def test_all_day_remind_0900():
    e = _event(all_day=True, start_time=None, remind_min=0, start_date=SAT)
    (o,) = expand(e, MON, SUN, tz=TZ, skips=set())
    assert o.all_day and o.start is None and o.end is None
    assert o.remind_at == datetime(2026, 10, 31, 0, 0, tzinfo=UTC)  # 그날 09:00 KST
    (o,) = expand(_event(all_day=True, start_time=None, remind_min=1440, start_date=SAT), MON, SUN, tz=TZ, skips=set())
    assert o.remind_at == datetime(2026, 10, 30, 0, 0, tzinfo=UTC)  # 전날 09:00
    (o,) = expand(_event(all_day=True, start_time=None, remind_min=None, start_date=SAT), MON, SUN, tz=TZ, skips=set())
    assert o.remind_at is None


def test_range_over_62_raises():
    e = _event()
    expand(e, MON, MON + timedelta(days=61), tz=TZ, skips=set())  # 62일(포함)은 된다
    with pytest.raises(ValueError):
        expand(e, MON, MON + timedelta(days=62), tz=TZ, skips=set())
    with pytest.raises(ValueError):
        expand(e, TUE, MON, tz=TZ, skips=set())


def test_duration_end_and_once_outside_range():
    e = _event(duration_min=90)
    (o,) = expand(e, MON, MON, tz=TZ, skips=set())
    assert o.end == o.start + timedelta(minutes=90)
    assert expand(e, TUE, SUN, tz=TZ, skips=set()) == []


# --- 저장소 ---


@pytest.fixture
def repo(conn):
    return EventsRepo(conn, FakeClock(NOW), TZ)


def _fields(**kw):
    base = {"title": "팀 회의", "start_date": MON, "start_time": time(10, 0), "remind_min": 10, "origin": "user"}
    base.update(kw)
    return base


def test_end_repeat_from_first_day_deletes(repo):
    e = repo.create(_fields(repeat="weekly", weekdays=1), NOW)
    assert repo.end_repeat(e.id, MON, NOW) is None
    assert repo.get(e.id) is None and repo.get(e.id, include_deleted=True) is not None
    e2 = repo.create(_fields(repeat="daily"), NOW)
    got = repo.end_repeat(e2.id, THU, NOW)
    assert got is not None and got.repeat_until == WED
    assert _dates(repo.occurrences(MON, SUN)) == [MON, TUE, WED]


def test_update_time_clears_future_reminder_rows(repo, conn):
    e = repo.create(_fields(repeat="daily", start_time=time(14, 0)), NOW)
    now = datetime(2026, 10, 27, 4, 29, tzinfo=UTC)  # 화 13:29 KST
    for d in (MON, TUE, WED):
        conn.execute(
            "INSERT INTO event_reminders (event_id, occurrence_date, remind_at, outcome, decided_at) "
            "VALUES (?, ?, ?, 'sent', ?)", (e.id, d.isoformat(), "2026-10-26T04:50:00+00:00", "2026-10-26T04:50:00+00:00"),
        )
    repo.update(e.id, {"title": "이름만"}, now)  # 시각이 아니면 그대로
    assert conn.execute("SELECT COUNT(*) FROM event_reminders").fetchone()[0] == 3
    repo.update(e.id, {"start_time": time(15, 0)}, now)
    left = [r[0] for r in conn.execute("SELECT occurrence_date FROM event_reminders ORDER BY 1")]
    assert left == [MON.isoformat()]  # 월(지난 날)만 남고 화(14:00 전)·수는 지워진다


def test_occurrences_skips_and_include_skipped(repo):
    e = repo.create(_fields(repeat="daily"), NOW)
    assert repo.skip(e.id, TUE) and not repo.skip(e.id, TUE)
    assert TUE not in _dates(repo.occurrences(MON, WED))
    got = repo.occurrences(MON, WED, include_skipped=True)
    assert [(o.date, o.skipped) for o in got] == [(MON, False), (TUE, True), (WED, False)]
    assert repo.skips() == {e.id: {TUE}}
    assert repo.unskip(e.id, TUE) and _dates(repo.occurrences(MON, WED)) == [MON, TUE, WED]


def test_occurrences_all_day_first_then_time(repo):
    repo.create(_fields(title="늦은", start_time=time(18, 0)), NOW)
    repo.create(_fields(title="카드 결제일", all_day=True, start_time=None, remind_min=0, area=Area.finance), NOW)
    repo.create(_fields(title="이른", start_time=time(8, 0)), NOW)
    assert [o.title for o in repo.occurrences(MON, MON)] == ["카드 결제일", "이른", "늦은"]
    assert repo.count_live() == 3 and len(repo.live()) == 3

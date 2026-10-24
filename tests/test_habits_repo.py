"""HabitsRepo와 습관 읽기 모양 (SP7 스펙 5.2, 5.5)."""

from datetime import UTC, date, datetime

import pytest

from my_planner.clock import FakeClock
from my_planner.domain import Area
from my_planner.store.repos.habits import Habit, HabitsRepo
from my_planner.store.views import habit_dict, habit_history, habits_view

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


@pytest.fixture
def habits(conn):
    return HabitsRepo(conn, FakeClock(NOW))


def mk(habits, title="운동", kind="daily", target=None, area=Area.health):
    return habits.add(title, area, kind, target, NOW)


def test_add_and_get(habits):
    a = mk(habits)
    b = mk(habits, "독서", "weekly", 3, Area.learning)
    assert isinstance(a, Habit) and (a.sort_order, b.sort_order) == (1, 2)
    assert (b.kind, b.target_per_week, b.status, b.area) == ("weekly", 3, "active", Area.learning)
    assert habits.get(a.id) == a and habits.get(999) is None
    assert habits.find_by_title("독서", ("active",)) == b
    assert habits.find_by_title("독서", ("paused",)) is None


def test_check_idempotent_and_uncheck_returns_checked_at(habits):
    h = mk(habits)
    d = date(2026, 10, 24)
    assert habits.check(h.id, d, NOW) is True
    assert habits.check(h.id, d, datetime(2026, 10, 24, 12, tzinfo=UTC)) is False
    assert habits.has_checks(h.id) and habits.checked_on(d) == {h.id}
    assert habits.uncheck(h.id, d) == "2026-10-24T09:00:00.000000+00:00"
    assert habits.uncheck(h.id, d) is None
    assert not habits.has_checks(h.id) and habits.checked_on(d) == set()


def test_restore_check(habits):
    h = mk(habits)
    d = date(2026, 10, 22)
    habits.check(h.id, d, NOW)
    at = habits.uncheck(h.id, d)
    habits.restore_check(h.id, d, at)
    assert habits.checked_on(d) == {h.id}
    assert habits.uncheck(h.id, d) == at


def test_list_excludes_deleted_and_orders_by_sort_order(habits):
    _, b, c = mk(habits, "가"), mk(habits, "나"), mk(habits, "다")
    habits.set_status(b.id, "paused", NOW)
    habits.soft_delete(c.id, NOW)
    assert [h.title for h in habits.list()] == ["가"]
    assert [h.title for h in habits.list(("active", "paused", "archived"))] == ["가", "나"]
    assert habits.get(c.id) is None and habits.find_by_title("다", ("active",)) is None


def test_update_and_set_status(habits):
    h = mk(habits)
    later = datetime(2026, 10, 25, tzinfo=UTC)
    u = habits.update(h.id, now=later, title="걷기", kind="weekly", target_per_week=2)
    assert (u.title, u.kind, u.target_per_week, u.updated_at) == ("걷기", "weekly", 2, later)
    assert habits.update(h.id, now=later, kind="daily", target_per_week=None).target_per_week is None
    assert habits.set_status(h.id, "archived", later).status == "archived"
    with pytest.raises(ValueError):
        habits.update(h.id, now=later, sort_order=9)


def test_soft_delete_unknown_or_deleted_raises_like_update(habits):
    """`update`·`set_status`처럼 없는·이미 지운 습관이면 `KeyError`(되돌린 추가를 두 번 하지 않게)."""
    h = mk(habits)
    habits.soft_delete(h.id, NOW)
    with pytest.raises(KeyError):
        habits.soft_delete(h.id, NOW)
    with pytest.raises(KeyError):
        habits.soft_delete(999, NOW)
    with pytest.raises(KeyError):
        habits.set_status(h.id, "active", NOW)


def test_count_active(habits):
    a, b, _ = mk(habits, "가"), mk(habits, "나"), mk(habits, "다")
    assert habits.count_active() == 3
    habits.set_status(a.id, "paused", NOW)
    habits.soft_delete(b.id, NOW)
    assert habits.count_active() == 1


def test_week_counts_monday_to_sunday(habits):
    a, b = mk(habits, "가"), mk(habits, "나")
    for d in (date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 21), date(2026, 10, 25), date(2026, 10, 26)):
        habits.check(a.id, d, NOW)
    habits.check(b.id, date(2026, 10, 20), NOW)
    assert habits.week_counts(date(2026, 10, 19)) == {a.id: 3, b.id: 1}
    assert habits.week_counts(date(2026, 10, 26)) == {a.id: 1}
    assert habits.week_counts(date(2026, 11, 2)) == {}


def test_monday_0200_is_previous_iso_week(habits):
    """월요일 02:00 체크의 논리적 날짜는 일요일 10/25다(호출 쪽 `Tools.today()`). 저장소는 받은 날짜를 센다."""
    h = mk(habits)
    habits.check(h.id, date(2026, 10, 25), datetime(2026, 10, 25, 17, 0, tzinfo=UTC))  # 10/26 02:00 KST
    assert habits.week_counts(date(2026, 10, 19)) == {h.id: 1}
    assert habits.week_counts(date(2026, 10, 26)) == {}
    assert habits.checks_between(h.id, date(2026, 10, 19), date(2026, 10, 25)) == [date(2026, 10, 25)]


def test_iso_week_53(habits):
    from my_planner.clock import period_of
    from my_planner.domain import Cadence

    h = mk(habits)
    for d in (date(2026, 12, 28), date(2027, 1, 1), date(2027, 1, 3), date(2027, 1, 4)):
        habits.check(h.id, d, NOW)
    assert period_of(Cadence.week, date(2027, 1, 1)) == "2026-W53"
    assert habits.week_counts(date(2026, 12, 28)) == {h.id: 3}
    v = habits_view(habits, date(2027, 1, 1), ("active",))
    assert v["week"] == "2026-W53" and v["items"][0]["week_count"] == 3 and v["items"][0]["checked"] is True


def test_repo_has_no_missing_days_function():
    names = [n for n in dir(HabitsRepo) if not n.startswith("_")]
    assert names
    for n in names:
        assert not any(w in n.lower() for w in ("miss", "gap", "streak", "skip")), n


def test_habits_view_shape(habits):
    a = mk(habits, "운동", "weekly", 3)
    b = mk(habits, "독서")
    habits.check(a.id, date(2026, 10, 19), NOW)
    habits.check(a.id, date(2026, 10, 24), NOW)
    assert habits_view(habits, date(2026, 10, 24), ("active",)) == {
        "date": "2026-10-24",
        "week": "2026-W43",
        "items": [
            {"id": a.id, "title": "운동", "area": "health", "kind": "weekly", "target_per_week": 3,
             "status": "active", "checked": True, "week_count": 2},
            {"id": b.id, "title": "독서", "area": "health", "kind": "daily", "target_per_week": None,
             "status": "active", "checked": False, "week_count": 0},
        ],
    }
    habits.set_status(b.id, "paused", NOW)
    assert len(habits_view(habits, date(2026, 10, 24), ("active",))["items"]) == 1
    assert len(habits_view(habits, date(2026, 10, 24), ("active", "paused"))["items"]) == 2
    assert habit_dict(habits.get(a.id), checked=False, week_count=0)["checked"] is False


def test_habit_history_weeks_4_from_monday(habits):
    h = mk(habits, "운동", "weekly", 3)
    days = [date(2026, 9, 28), date(2026, 10, 1), date(2026, 10, 12), date(2026, 10, 22), date(2026, 10, 24)]
    for d in days:
        habits.check(h.id, d, NOW)
    habits.check(h.id, date(2026, 9, 27), NOW)  # 범위 밖
    r = habit_history(habits, h, date(2026, 10, 24), 4)
    assert r["from"] == "2026-09-28" and r["to"] == "2026-10-24"
    assert r["checked_dates"] == [d.isoformat() for d in days]
    assert r["weeks"] == [  # 10/05 주는 체크가 없어 빠진다
        {"week": "2026-W40", "count": 2},
        {"week": "2026-W42", "count": 1},
        {"week": "2026-W43", "count": 2},
    ]
    assert r["habit"] == habit_dict(h, checked=True, week_count=2)

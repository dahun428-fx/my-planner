"""SP15-06: 내 속도 표 `panel/pace.py` (스펙 8장, T8). 자료는 모두 지어낸 값이다."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from my_planner.clock import FakeClock
from my_planner.panel.pace import (
    Occ,
    Pace,
    PaceInputs,
    compute_pace,
    load_pace,
    pace_text,
)
from my_planner.store.db import transaction
from my_planner.store.repos.agents import AgentsRepo
from my_planner.store.repos.events import EventsRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.panel import PanelRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.repos.workout import WorkoutRepo

TODAY = date(2026, 11, 1)  # 일요일


def _back(n: int) -> date:
    return TODAY - timedelta(days=n)


def _fixture() -> PaceInputs:
    done = (
        [(_back(i * 4), "career") for i in range(12)]          # 0~44일 전
        + [(_back(i * 10 + 1), "health") for i in range(4)]    # 1~31일 전
        + [(_back(3), None), (_back(5), None)]                 # 영역 없음: 뺀다
        + [(_back(56), "career"), (_back(60), "health")]       # 8주 밖
    )
    postponed = [(date(2026, 10, 26), "career"), (date(2026, 10, 19), "career"), (date(2026, 10, 28), "career"),
                 (_back(28), "health")]                        # 마지막은 4주 밖
    workout = {_back(i) for i in range(0, 20, 2)}              # 10날(0, 2, …, 18일 전)
    habit = {_back(i) for i in (0, 2, 21, 23, 25, 27, 29, 31)}  # 8날, 둘이 겹침
    return PaceInputs(
        done=done, postponed=postponed, workout_days=workout | habit | {_back(56)}, occurrences=[],
        conditions=[(_back(1), 3), (_back(2), 2), (_back(3), 4), (_back(4), 5), (_back(28), 1)],
        body=[(_back(1), 7000, 360), (_back(2), 7400, 420), (_back(3), None, None), (_back(40), 100, 100)],
        panel={"accepted": 2, "done": 1, "postponed": 0, "dismissed": 1},
    )


def test_compute_pace_fixture():
    p = compute_pace(_fixture(), TODAY)
    assert p.done_per_week == {"career": 1.5, "health": 0.5}
    assert p.postponed == {"career": 3}
    assert p.postponed_weekday == 0  # 월·월·수
    assert p.workout_days_per_week == 2.0  # (10 + 8 − 2) / 8
    assert (p.condition_avg, p.low_condition_days) == (3.5, 2)
    assert (p.sleep_avg_h, p.steps_avg) == (6.5, 7200)
    assert p.panel == {"accepted": 2, "done": 1, "postponed": 0, "dismissed": 1}
    assert (p.free_evenings, p.free_weekend_halves) == (10, 8)  # 일정 없음


def test_postponed_weekday_tie_takes_earlier():
    inp = PaceInputs(
        done=[], postponed=[(date(2026, 10, 30), "career"), (date(2026, 10, 28), None)], workout_days=set(),
        occurrences=[], conditions=[], body=[], panel={},
    )
    p = compute_pace(inp, TODAY)
    assert p.postponed == {"career": 1}
    assert p.postponed_weekday == 2  # 수(영역 없는 것도 요일에는 센다)·금 같으면 이른 요일


def _occ(d: date, start: time | None = None, minutes: int | None = None) -> Occ:
    return Occ(day=d, start=start, minutes=minutes, all_day=start is None)


def test_free_slots():
    occ = [
        _occ(date(2026, 11, 2), time(19, 30), 30),     # 월 저녁
        _occ(date(2026, 11, 3)),                         # 화 하루 종일
        _occ(date(2026, 11, 4), time(18, 0), 30),       # 수 18:00~18:30: 저녁과 겹치지 않는다
        _occ(date(2026, 11, 7), time(10, 0)),            # 토 오전, 길이 없음 = 60분
    ]
    inp = PaceInputs(done=[], postponed=[], workout_days=set(), occurrences=occ, conditions=[], body=[], panel={})
    p = compute_pace(inp, TODAY)
    assert (p.free_evenings, p.free_weekend_halves) == (8, 7)
    weekly = [_occ(date(2026, 11, 5), time(20, 0), 60), _occ(date(2026, 11, 12), time(20, 0), 60)]  # 매주 목
    p = compute_pace(PaceInputs(done=[], postponed=[], workout_days=set(), occurrences=occ + weekly, conditions=[],
                                body=[], panel={}), TODAY)
    assert p.free_evenings == 6
    edge = [
        _occ(date(2026, 11, 9), time(18, 0), 60),       # 18:00~19:00: 19:00에 끝나면 겹치지 않는다
        _occ(date(2026, 11, 10), time(18, 30)),          # 18:30~19:30: 겹친다
        _occ(date(2026, 11, 8), time(12, 30), 60),       # 일 12:30~13:30: 오전·오후 둘 다
        _occ(date(2026, 11, 14)),                        # 토 하루 종일: 두 칸 다
        _occ(date(2026, 11, 15), time(9, 0)),            # 다음 2주 밖(오늘+14)
    ]
    p = compute_pace(PaceInputs(done=[], postponed=[], workout_days=set(), occurrences=edge, conditions=[], body=[],
                                panel={}), TODAY)
    assert (p.free_evenings, p.free_weekend_halves) == (9, 4)


FIXTURE_TEXT = """## 내 속도 표
- 한 주에 끝낸 할 일(지난 8주 평균): 커리어 1.5 · 건강 0.5
- 미룬 할 일(지난 4주): 커리어 3 · 가장 많이 미룬 요일 월
- 운동한 날(지난 8주 주 평균): 2.0
- 빈 저녁·주말(다음 2주): 평일 저녁 10 · 주말 반나절 8
- 컨디션(지난 4주): 평균 3.5 · 3 이하 날 2
- 잠·걸음(지난 4주 평균): 잠 6.5시간 · 걸음 7200
- 패널 제안(지난 4주): 받음 2 · 끝냄 1 · 미룸 0 · 버림 1"""

EMPTY_TEXT = """## 내 속도 표
- 한 주에 끝낸 할 일(지난 8주 평균): 기록 없음
- 미룬 할 일(지난 4주): 기록 없음
- 운동한 날(지난 8주 주 평균): 기록 없음
- 빈 저녁·주말(다음 2주): 평일 저녁 0 · 주말 반나절 0
- 컨디션(지난 4주): 기록 없음
- 잠·걸음(지난 4주 평균): 기록 없음
- 패널 제안(지난 4주): 기록 없음"""


def test_pace_text_shape():
    text = pace_text(compute_pace(_fixture(), TODAY))
    assert text == FIXTURE_TEXT
    empty = Pace(
        done_per_week={}, postponed={}, postponed_weekday=None, workout_days_per_week=0.0, free_evenings=0,
        free_weekend_halves=0, condition_avg=None, low_condition_days=0, sleep_avg_h=None, steps_avg=None, panel={},
    )
    assert pace_text(empty) == EMPTY_TEXT
    half = Pace(
        done_per_week={}, postponed={}, postponed_weekday=None, workout_days_per_week=0.0, free_evenings=0,
        free_weekend_halves=3, condition_avg=None, low_condition_days=0, sleep_avg_h=None, steps_avg=6800,
        panel={"accepted": 0, "done": 0, "postponed": 0, "dismissed": 0},
    )
    lines = pace_text(half).splitlines()
    assert lines[4] == "- 빈 저녁·주말(다음 2주): 평일 저녁 0 · 주말 반나절 3"
    assert lines[6] == "- 잠·걸음(지난 4주 평균): 잠 기록 없음 · 걸음 6800"
    assert lines[7] == "- 패널 제안(지난 4주): 기록 없음"
    for t in (text, pace_text(empty), pace_text(half)):
        assert "%" not in t


def test_load_pace_reads_db(conn):
    # 2026-11-01(일) 13:00 KST
    clock = FakeClock(datetime(2026, 11, 1, 4, 0, tzinfo=UTC))
    tasks = TasksRepo(conn, clock)
    t = tasks.create("가짜 할 일", ["career"])
    tasks.set_status(t.id, "done")
    with transaction(conn):
        AgentsRepo(conn, clock).add_event("task_postponed", "task:9", "health", "app", date(2026, 10, 26),
                                          to=("manager",), now=clock.now())
        WorkoutRepo(conn, clock).add_log(date(2026, 10, 31), "가짜 운동", None, None, None, [], clock.now())
        habits = HabitsRepo(conn, clock)
        walk = habits.add("가짜 걷기", "health", "daily", None, clock.now())
        read = habits.add("가짜 읽기", "learning", "daily", None, clock.now())
        for h, d in ((walk, date(2026, 10, 31)), (walk, date(2026, 10, 29)), (read, date(2026, 10, 28))):
            habits.check(h.id, d, clock.now())
    EventsRepo(conn, clock, "Asia/Seoul").create({
        "title": "가짜 반복 일정", "start_date": date(2026, 10, 1), "start_time": time(20, 0), "repeat": "weekly",
        "weekdays": 8, "origin": "user",  # 매주 목
    }, clock.now())
    panel = PanelRepo(conn, clock)
    with transaction(conn):
        for state, at in (("done", clock.now()), ("dismissed", clock.now()), ("done", clock.now() - timedelta(days=40))):
            sid = panel.add_suggestion(
                conversation_id=None, kind="task", title="가짜 제안", area="career", size_min=30, per_week=None,
                due_hint=None, experts=["career"], evidence=[], week="2026-W44", now=at,
            )
            panel.set_state(sid, state, now=at)
    p = load_pace(conn, clock, TODAY, tz="Asia/Seoul", boundary=time(4, 0))
    assert p.done_per_week == {"career": 0.1}  # 1 / 8
    assert p.postponed == {"health": 1} and p.postponed_weekday == 0
    assert p.workout_days_per_week == 0.2  # 운동 10-31 ∪ 건강 습관 10-31·10-29(배움 습관은 뺀다)
    assert p.free_evenings == 8  # 목 둘이 빠진다
    assert p.panel == {"accepted": 1, "done": 1, "postponed": 0, "dismissed": 1}  # 40일 전 것은 밖

"""상태창 규칙과 스냅샷 (SP3-4 스펙 9장, 6.3.6). 내용은 모두 꾸며 낸 것이다."""

from datetime import UTC, date, datetime, time

import pytest
from curve_sql import area_default, area_scores, milestone, recovery, title, xp
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import Area, Cadence, TaskStatus
from my_planner.status.snapshot import status_snapshot
from my_planner.status.xp import (
    AREA_LABELS,
    DEFAULT_RECOVERY_QUESTS,
    level_for,
    progress,
    title_name,
    xp_threshold,
)
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import TasksRepo

NOW = kst(2026, 10, 24, 13, 0)  # 논리적 날짜 2026-10-24, 분기 2026-Q4


def test_level_table():
    assert [xp_threshold(n) for n in (1, 2, 5, 10, 20, 30)] == [0, 150, 900, 3150, 11400, 24650]
    assert progress(1380) == (6, 130, 400)
    assert progress(0) == (1, 0, 150)
    assert progress(149) == (1, 149, 150) and progress(150) == (2, 0, 200)
    for n in (2, 5, 10, 30, 200):
        assert level_for(xp_threshold(n)) == n and level_for(xp_threshold(n) - 1) == n - 1


def snap(conn, *, include_sensitive=False, now=NOW):
    clock = FakeClock(now)
    return status_snapshot(
        now=now, tz="Asia/Seoul", boundary=time(4, 0), status=StatusRepo(conn, clock), curve=CurveRepo(conn, clock),
        tasks=TasksRepo(conn, clock), conditions=ConditionsRepo(conn, clock), include_sensitive=include_sensitive,
    )


def stat(body, area):
    return next(s for s in body["stats"] if s["area"] == area)


def test_stats_latest_quarter_falls_back_to_previous_with_period(conn):
    area_scores(conn, "2026-Q3", career=6, health=6, finance=5)
    area_scores(conn, "2026-Q4", career=7, health=6)  # finance는 이번 분기에 없다
    body = snap(conn)
    assert [s["area"] for s in body["stats"]] == [a.value for a in Area]
    assert [s["label"] for s in body["stats"]] == list(AREA_LABELS.values())
    c = stat(body, "career")
    assert (c["score"], c["period"], c["prev_score"], c["prev_period"]) == (7, "2026-Q4", 6, "2026-Q3")
    f = stat(body, "finance")
    assert (f["score"], f["period"], f["prev_score"], f["prev_period"], f["debuff"]) == (5, "2026-Q3", None, None, False)
    assert stat(body, "learning")["score"] is None and stat(body, "learning")["period"] is None


def test_debuff_only_when_both_quarters_and_lower(conn):
    area_scores(conn, "2026-Q3", career=7, health=6, learning=5, finance=4)
    area_scores(conn, "2026-Q4", career=6, health=6, learning=8, relationships=3)
    body = snap(conn)
    assert {s["area"] for s in body["stats"] if s["debuff"]} == {"career"}  # 같거나 오르면 없다, 앞 분기 없으면 없다
    assert stat(body, "relationships")["debuff"] is False and stat(body, "finance")["debuff"] is False
    assert all(s["recovery_quest"] is None for s in body["stats"] if not s["debuff"])


def test_recovery_quest_priority(conn):
    area_scores(conn, "2026-Q3", career=7, health=6, finance=6)
    area_scores(conn, "2026-Q4", career=5, health=4, finance=3)
    recovery(conn, "2026-Q4", "career", "저녁에 한 줄 일기 쓰기")
    area_default(conn, "career", "시드 기본 퀘스트")
    area_default(conn, "health", "시드 건강 퀘스트")
    body = snap(conn)
    assert stat(body, "career")["recovery_quest"] == "저녁에 한 줄 일기 쓰기"  # 1. 점수 행
    assert stat(body, "health")["recovery_quest"] == "시드 건강 퀘스트"  # 2. 영역 기본
    assert stat(body, "finance")["recovery_quest"] == DEFAULT_RECOVERY_QUESTS["finance"] == "이번 주 지출 한 번 훑어보기"


def test_no_area_scores_stats_null_no_debuff(conn):
    body = snap(conn)
    assert len(body["stats"]) == 6
    for s in body["stats"]:
        assert (s["score"], s["period"], s["prev_score"], s["prev_period"], s["debuff"], s["recovery_quest"]) == (
            None, None, None, None, False, None,
        )


def test_hp_today_condition_or_null(conn):
    assert snap(conn)["hp"] == {"date": "2026-10-24", "score": None}
    ConditionsRepo(conn, FakeClock(NOW)).upsert(date(2026, 10, 24), 4, None)
    ConditionsRepo(conn, FakeClock(NOW)).upsert(date(2026, 10, 23), 1, None)
    assert snap(conn)["hp"] == {"date": "2026-10-24", "score": 4}
    # 새벽 3시는 아직 전날이다
    assert snap(conn, now=kst(2026, 10, 25, 3, 0))["hp"] == {"date": "2026-10-24", "score": 4}


def mk(tasks, title_, *, parent=None, planned=None, status=TaskStatus.open):
    return tasks.create(title_, [Area.career], status, planned, None, parent, "")


def test_main_and_daily_quests(conn):
    tasks = TasksRepo(conn, FakeClock(NOW))
    a, b = mk(tasks, "꾸민 큰 목표 하나"), mk(tasks, "꾸민 큰 목표 둘")
    tasks.set_priorities(Cadence.quarter, "2026-Q4", [b.id, a.id])
    tasks.set_priorities(Cadence.quarter, "2026-Q3", [mk(tasks, "지난 분기 목표").id])
    s1 = mk(tasks, "첫 걸음 오늘", parent=a.id, planned=date(2026, 10, 24))
    mk(tasks, "첫 걸음 끝남", parent=a.id, status=TaskStatus.done)
    mk(tasks, "첫 걸음 날짜 없음", parent=a.id)
    mk(tasks, "첫 걸음 내일", parent=b.id, planned=date(2026, 10, 25))
    mk(tasks, "그냥 오늘 할 일", planned=date(2026, 10, 24))  # 첫 걸음이 아니다
    body = snap(conn)
    assert [(q["title"], q["rank"], q["period"]) for q in body["main_quests"]] == [
        ("꾸민 큰 목표 둘", 1, "2026-Q4"), ("꾸민 큰 목표 하나", 2, "2026-Q4"),
    ]
    assert body["main_quests"][1]["first_steps"] == {"open": 2, "done": 1}
    assert body["main_quests"][0]["first_steps"] == {"open": 1, "done": 0}
    # 오늘 첫 걸음이 있으면 그것만
    assert body["daily_quests"] == [
        {"task_id": s1.id, "title": "첫 걸음 오늘", "parent_id": a.id, "parent_title": "꾸민 큰 목표 하나",
         "planned_for": "2026-10-24"}
    ]
    # 오늘 것이 없으면 메인 퀘스트마다 날짜 없는 다음 첫 걸음 하나
    tasks.set_status(s1.id, TaskStatus.done)
    mk(tasks, "둘째 날짜 없음", parent=a.id)
    body = snap(conn)
    assert [(q["title"], q["parent_title"], q["planned_for"]) for q in body["daily_quests"]] == [
        ("첫 걸음 날짜 없음", "꾸민 큰 목표 하나", None)
    ]


def test_titles_template_label_override_and_sensitive_excluded(conn):
    hi = milestone(conn, "꾸민 고점", "2022-05", kind="high")
    tp = milestone(conn, "꾸민 전환점", "2023-02-10", kind="turning_point", title_label="내가 붙인 이름")
    sens = milestone(conn, "꾸민 민감 고점", "2021", kind="high", sensitive=1)
    for i, m in enumerate((hi, tp, sens)):
        title(conn, m, f"2026-10-0{i + 1}T00:00:00.000000+00:00")
    body = snap(conn)
    assert body["titles"] == [
        {"milestone_id": hi, "title": "「꾸민 고점」의 순간", "kind": "high", "date": "2022-05",
         "granted_at": datetime(2026, 10, 1, tzinfo=UTC)},
        {"milestone_id": tp, "title": "내가 붙인 이름", "kind": "turning_point", "date": "2023-02-10",
         "granted_at": datetime(2026, 10, 2, tzinfo=UTC)},
    ]
    assert [t["milestone_id"] for t in snap(conn, include_sensitive=True)["titles"]] == [hi, tp, sens]
    assert title_name("turning_point", "꾸민 전환점", None) == "「꾸민 전환점」을 지나온 사람"
    with pytest.raises(ValueError):
        title_name("low", "꾸민 저점", None)


def test_recent_xp_and_totals(conn):
    for i in range(7):
        xp(conn, f"task:{i}", 10, f"2026-10-0{i + 1}T00:00:00.000000+00:00", label=f"라벨{i}")
    body = snap(conn)
    assert (body["level"], body["xp_total"], body["xp_into_level"], body["xp_for_next"]) == (1, 70, 70, 150)
    assert [x["label"] for x in body["recent_xp"]] == ["라벨6", "라벨5", "라벨4", "라벨3", "라벨2"]


def test_partial_quarter_keeps_other_area_debuff(conn):
    area_scores(conn, "2026-Q2", health=7)
    area_scores(conn, "2026-Q3", health=4)
    area_scores(conn, "2026-Q4", career=6)  # 이번 분기에는 커리어만 기록
    body = snap(conn)
    h = stat(body, "health")
    assert (h["score"], h["period"], h["prev_score"], h["prev_period"], h["debuff"]) == (
        4, "2026-Q3", 7, "2026-Q2", True,
    )
    assert h["recovery_quest"] == DEFAULT_RECOVERY_QUESTS["health"]
    assert stat(body, "career")["debuff"] is False


def test_non_adjacent_quarters_give_no_debuff(conn):
    area_scores(conn, "2025-Q1", health=8)
    area_scores(conn, "2026-Q3", health=3)
    h = stat(snap(conn), "health")
    assert (h["score"], h["period"], h["prev_score"], h["prev_period"], h["debuff"]) == (3, "2026-Q3", None, None, False)
    area_scores(conn, "2025-Q4", career=5)
    area_scores(conn, "2026-Q1", career=2)  # 해를 넘어도 바로 앞 분기다
    c = stat(snap(conn), "career")
    assert (c["debuff"], c["prev_period"]) == (True, "2025-Q4")


def test_area_with_only_older_scores_still_shows_stat(conn):
    area_scores(conn, "2025-Q2", learning=6)
    area_scores(conn, "2026-Q4", career=7)
    body = snap(conn)
    ln = stat(body, "learning")
    assert (ln["score"], ln["period"], ln["debuff"]) == (6, "2025-Q2", False)


def test_main_quest_rank_is_priorities_rank(conn):
    tasks = TasksRepo(conn, FakeClock(NOW))
    a, b = mk(tasks, "목표 하나"), mk(tasks, "목표 둘")
    tasks.set_priorities(Cadence.quarter, "2026-Q4", [a.id, b.id])
    tasks.set_status(a.id, TaskStatus.done)
    assert [(q["title"], q["rank"]) for q in snap(conn)["main_quests"]] == [("목표 둘", 2)]

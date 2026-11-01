"""하락 이유 나누기와 분기 스냅숏 (SP13-04)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from my_planner.clock import FakeClock, local
from my_planner.standing.bench import load_bench
from my_planner.standing.drift import Drift, debuff, marks, split
from my_planner.standing.score import AREAS, area_positions, score_all
from my_planner.standing.service import (
    area_drifts,
    catch_up_snapshots,
    current,
    snapshot_if_first,
    with_derived,
    write_snapshot,
)
from my_planner.store.db import transaction
from my_planner.store.repos.standing import StandingRepo
from my_planner.store.repos.workout import WorkoutRepo

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
BENCH = load_bench(TODAY)


def _sample() -> list[dict]:
    return json.loads((FIX / "standing_sample.json").read_text(encoding="utf-8"))["measures"]


def _load(conn, clock, drop=(), measured_on=None):
    repo = StandingRepo(conn, clock)
    with transaction(conn):
        for m in _sample():
            if m["metric"] in drop:
                continue
            on = measured_on or m["measured_on"]
            repo.add(m["metric"], m["value"], date.fromisoformat(on), "import", None, "mid", clock.now())
    return repo


def _vals(**over):
    base = {m["metric"]: m["value"] for m in _sample() if m["metric"] != "cert"}
    base.update(over)
    return base


def _bench_dir(tmp_path, p50):
    text = (Path(__file__).parents[1] / "src/my_planner/standing/benchmarks/2026.toml").read_text(encoding="utf-8")
    head, tail = text.split("[income]", 1)
    tail = tail.replace("[5000, 50]", f"[{p50}, 50]", 2)
    text = (head + "[income]" + tail).replace('version = "2026.1"', 'version = "2027"')
    text = text.replace('effective_from = "2026-11-01"', 'effective_from = "2027-01-01"')
    d = tmp_path / "bench"
    d.mkdir()
    (d / "2027.toml").write_text(text, encoding="utf-8")
    return d


def _bench27(tmp_path):
    b = load_bench(date(2027, 6, 1), _bench_dir(tmp_path, 6000))
    assert b.version == "2027"
    return b


def _pos(values, bench, today, area):
    return area_positions(score_all(values, bench, "national", today))[area]


def test_bench_only_change_is_world(tmp_path):
    b27 = _bench27(tmp_path)
    v = _vals()
    d = split(v, BENCH, TODAY, v, b27, date(2027, 6, 1), "finance")
    assert d is not None
    assert d.me == 0
    assert d.world < 0
    assert d.delta == d.world


def test_input_only_change_is_me():
    d = split(_vals(), BENCH, TODAY, _vals(salary_krw=45_000_000), BENCH, TODAY, "finance")
    assert d is not None
    assert d.world == 0
    assert d.me == d.delta < 0


def test_both_sum(tmp_path):
    b27 = _bench27(tmp_path)
    day = date(2027, 6, 1)
    old, new = _vals(), _vals(salary_krw=45_000_000)
    for area in ("finance", "career"):
        d = split(old, BENCH, TODAY, new, b27, day, area)
        only_world = split(old, BENCH, TODAY, old, b27, day, area)
        assert d is not None and only_world is not None
        assert abs(d.world - only_world.world) < 1e-9
        assert abs(d.me - (_pos(new, b27, day, area) - _pos(old, b27, day, area))) < 1e-9
        assert abs(d.delta - (d.world + d.me)) < 1e-9


def test_age_band_move_is_world():
    v = _vals(shuttle_run_laps=46)
    d = split(v, BENCH, date(2027, 6, 1), v, BENCH, date(2028, 6, 1), "health")
    assert d is not None
    assert abs(d.world - 0.6 * 0.20 * 15) < 1e-7
    assert d.me == 0


def test_marks_thresholds():
    assert marks(Drift(-4.9, 0, -4.9)) == []
    assert marks(Drift(-5, 0, -5)) == [{"kind": "me", "delta": -5}]
    assert debuff(Drift(-5, 0, -5)) is True
    assert marks(Drift(-6, -6, 0)) == [{"kind": "world", "delta": -6}]
    assert debuff(Drift(-6, -6, 0)) is False
    assert debuff(None) is False
    assert marks(Drift(2, -6, 8)) == [{"kind": "me", "delta": 8}, {"kind": "world", "delta": -6}]


def test_innate_not_in_area_drift():
    # 키는 몸 계측(FFMI)에도 쓰이므로, 몸무게·체지방이 없는 자료에서 키만 바꾼다
    v = {"profile_birth_year": 1992, "profile_sex": "m", "height_cm": 176, "shuttle_run_laps": 46}
    h = split(v, BENCH, TODAY, {**v, "height_cm": 185}, BENCH, TODAY, "health")
    assert h is not None and h.delta == 0
    for area in AREAS:
        d = split(v, BENCH, TODAY, {**v, "height_cm": 185}, BENCH, TODAY, area)
        assert d is None or (d.delta == 0 and d.me == 0 and d.world == 0)


def test_snapshot_if_first_once(conn):
    clock = FakeClock(NOW)
    _load(conn, clock)
    with transaction(conn):
        assert snapshot_if_first(conn, clock, TODAY) == "2026-Q4"
    n = len(StandingRepo(conn, clock).snapshots_for("2026-Q4"))
    assert 0 < n <= 18
    with transaction(conn):
        assert snapshot_if_first(conn, clock, TODAY) is None
    assert len(StandingRepo(conn, clock).snapshots_for("2026-Q4")) == n


def test_catch_up_previous_quarter(conn):
    clock = FakeClock(datetime(2026, 10, 2, 0, 0, tzinfo=UTC))
    repo = _load(conn, clock, measured_on="2026-09-15")
    with transaction(conn):
        assert catch_up_snapshots(conn, clock, date(2026, 10, 2)) > 0
    rows = repo.snapshots_for("2026-Q3")
    assert rows
    assert local(rows[0].taken_at, "Asia/Seoul").date() == date(2026, 9, 30)
    with transaction(conn):
        assert catch_up_snapshots(conn, clock, date(2026, 10, 2)) == 0


def test_drift_survives_deleted_snapshot_measure(conn):
    clock = FakeClock(NOW)
    repo = _load(conn, clock)
    with transaction(conn):
        snapshot_if_first(conn, clock, TODAY)
    sal = repo.latest()["salary_krw"]
    with transaction(conn):
        repo.delete(sal.id, NOW)
    now = current(conn, clock, TODAY)
    drifts = area_drifts(conn, clock, TODAY, now)
    assert drifts["career"] is not None and drifts["career"].me == 0
    assert drifts["finance"] is not None and drifts["finance"].me == 0


def test_filling_blank_is_not_my_drop(conn):
    clock = FakeClock(NOW)
    repo = _load(conn, clock, drop=("monthly_saving_krw", "monthly_net_income_krw"))
    with transaction(conn):
        snapshot_if_first(conn, clock, TODAY)
        repo.add("savings_rate_pct", 5, TODAY, "import", None, "mid", NOW)
    drifts = area_drifts(conn, clock, TODAY, current(conn, clock, TODAY))
    d = drifts["finance"]
    assert d is not None and d.me == 0
    assert debuff(d) is False


def test_catch_up_replaces_mid_quarter_first(conn):
    clock = FakeClock(datetime(2026, 8, 10, 3, 0, tzinfo=UTC))
    repo = _load(conn, clock, measured_on="2026-08-01")
    with transaction(conn):
        assert snapshot_if_first(conn, clock, date(2026, 8, 10)) == "2026-Q3"
    clock.set(datetime(2026, 10, 2, 0, 0, tzinfo=UTC))
    with transaction(conn):
        repo.add("salary_krw", 70_000_000, date(2026, 9, 15), "import", None, "mid", clock.now())
        repo.add("salary_krw", 99_000_000, date(2026, 10, 1), "import", None, "mid", clock.now())
        assert catch_up_snapshots(conn, clock, date(2026, 10, 2)) > 0
    rows = repo.snapshots_for("2026-Q3")
    assert local(rows[0].taken_at, "Asia/Seoul").date() == date(2026, 9, 30)
    assert rows[0].inputs["values"]["salary_krw"] == 70_000_000  # 10월 값(9.9천만)은 들어가지 않는다
    assert rows[0].inputs["source"] == "catch_up"
    with transaction(conn):
        assert write_snapshot(conn, clock, "2026-Q3", as_of=date(2026, 9, 30)) > 0
    assert repo.snapshots_for("2026-Q3")[0].inputs["source"] == "review"


def test_derived_exercise_from_workout_logs(conn):
    clock = FakeClock(NOW)
    w = WorkoutRepo(conn, clock)
    with transaction(conn):
        for i in range(8):
            w.add_log(date(2026, 10, 5 + i * 3), "달리기", None, None, None, [], NOW)
    out = with_derived({"exercise_days_week": 0.5}, w, TODAY)
    assert out["exercise_days_week"] == 2.0
    assert with_derived({"exercise_days_week": 0.5}, None, TODAY)["exercise_days_week"] == 0.5


def test_review_snapshot_not_replaced_by_catch_up(conn):
    clock = FakeClock(datetime(2026, 8, 10, 3, 0, tzinfo=UTC))
    repo = _load(conn, clock, measured_on="2026-08-01")
    with transaction(conn):
        assert write_snapshot(conn, clock, "2026-Q3") > 0
    assert repo.snapshots_for("2026-Q3")[0].inputs["source"] == "review"
    clock.set(datetime(2026, 10, 2, 0, 0, tzinfo=UTC))
    with transaction(conn):
        assert catch_up_snapshots(conn, clock, date(2026, 10, 2)) == 0


def test_derived_exercise_windows(conn):
    clock = FakeClock(NOW)
    w = WorkoutRepo(conn, clock)
    with transaction(conn):
        w.add_log(date(2026, 9, 22), "달리기", None, None, None, [], NOW)  # 40일 전
        for i in range(8):
            w.add_log(date(2026, 10, 5 + i * 3), "달리기", None, None, None, [], NOW)
    assert with_derived({"exercise_days_week": 0.5}, w, TODAY)["exercise_days_week"] == 2.0


def test_derived_exercise_old_logs_only_is_zero(conn):
    clock = FakeClock(NOW)
    w = WorkoutRepo(conn, clock)
    with transaction(conn):
        w.add_log(date(2026, 9, 25), "달리기", None, None, None, [], NOW)  # 37일 전
        w.add_log(date(2026, 9, 8), "달리기", None, None, None, [], NOW)  # 54일 전
    assert with_derived({"exercise_days_week": 0.5}, w, TODAY)["exercise_days_week"] == 0.0

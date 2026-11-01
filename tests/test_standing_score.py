"""9축 점수와 시장 점수 (SP13-03)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from my_planner.clock import FakeClock
from my_planner.standing.bench import interp, load_bench
from my_planner.standing.markets import market_scores
from my_planner.standing.score import (
    AXES,
    AxisScore,
    age_band,
    area_positions,
    peer_key,
    round_half_up,
    score_all,
    values_from,
)
from my_planner.store.db import transaction
from my_planner.store.repos.standing import StandingRepo

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
BENCH = load_bench(TODAY)


def _sample() -> list[dict]:
    return json.loads((FIX / "standing_sample.json").read_text(encoding="utf-8"))["measures"]


def _values(conn, drop=(), extra=()):
    """고정 자료를 저장소에 넣었다가 읽는다(테스트마다 한 번만 부른다). 변형은 drop·extra로."""
    repo = StandingRepo(conn, FakeClock(NOW))
    rows = [m for m in _sample() if m["metric"] not in drop]
    rows += [{"metric": k, "value": v, "measured_on": d} for k, v, d in extra]
    with transaction(conn):
        for m in rows:
            repo.add(m["metric"], m["value"], date.fromisoformat(m["measured_on"]), "import", None, "mid", NOW)
    return values_from(repo.latest())[0]


def _without(values, *keys):
    return {k: v for k, v in values.items() if k not in keys}


def test_sample_matches_expected(conn):
    values = _values(conn)
    exp = json.loads((FIX / "standing_sample_expected.json").read_text(encoding="utf-8"))
    assert exp["today"] == TODAY.isoformat()
    for cohort in ("national", "peer"):
        scores = score_all(values, BENCH, cohort, TODAY)
        assert list(scores) == [a for a in AXES if a in scores]
        for axis, want in exp[cohort].items():
            if axis == "markets":
                continue
            assert abs(scores[axis].score - want) <= 1, (cohort, axis, scores[axis].score, want)
        mk = market_scores(scores, BENCH)
        for name, want in exp[cohort]["markets"].items():
            got = mk[name].score
            assert got is not None and abs(got - want) <= 1, (cohort, name, got, want)
            assert mk[name].excluded == ()


def test_values_from_ids_and_certs(conn):
    repo = StandingRepo(conn, FakeClock(NOW))
    with transaction(conn):
        a = repo.add("height_cm", 176, date(2026, 10, 1), "manual", None, "mid", NOW)
        repo.add("cert", "toeic:825", date(2026, 9, 1), "manual", None, "mid", NOW)
        repo.add("profile_sex", "m", date(2026, 10, 1), "manual", None, "mid", NOW)
    values, ids = values_from(repo.latest())
    assert values["height_cm"] == 176.0 and values["profile_sex"] == "m"
    assert values["cert"] == ["toeic:825"]
    assert ids["height_cm"] == a and "cert" not in ids


def test_age_band_and_peer_key():
    assert age_band({}, TODAY) is None
    assert age_band({"profile_birth_year": 1992}, TODAY) == "30_34"  # 33
    assert age_band({"profile_birth_year": 1991}, TODAY) == "30_34"  # 34
    assert age_band({"profile_birth_year": 1990}, TODAY) == "35_39"  # 35
    assert age_band({"profile_birth_year": 1960}, TODAY) == "35_39"
    assert age_band({"profile_birth_year": 2005}, TODAY) == "30_34"
    assert peer_key({"profile_region": "capital", "profile_job_family": "ai_ml"}) == "ai_ml"
    assert peer_key({"profile_region": "other", "profile_job_family": "ai_ml"}) is None
    assert peer_key({"profile_region": "capital", "profile_job_family": "other"}) is None
    assert round_half_up(2.5) == 3 and round_half_up(2.49) == 2


def test_height_180_is_83():
    s = score_all({"height_cm": 180}, BENCH, "national", TODAY)
    assert s["height"].score == 83
    assert "height_cm" in s["height"].inputs


def test_waist_below_75_full():
    base = {"profile_birth_year": 1992, "waist_cm": 74}
    s74 = score_all(base, BENCH, "national", TODAY)["looks"]
    s75 = score_all({**base, "waist_cm": 75}, BENCH, "national", TODAY)["looks"]
    # 몸 = 0.30*100 + 0.70*50 = 65 -> 0.7*65 + 0.15*50 + 0.15*50
    assert s74.raw == pytest.approx(60.5)
    assert s75.raw < s74.raw


def test_saving_missing_assumes_25(conn):
    values = _values(conn, drop=("monthly_saving_krw", "monthly_net_income_krw"))
    m = score_all(values, BENCH, "national", TODAY)["money"]
    assert m.assumed == ("saving",)
    inc = interp(62_000_000 / 10_000, BENCH.points("income", "national", "30_34"))
    nw = interp(180_000_000 / 10_000, BENCH.points("networth", "national"))
    assert m.score == round_half_up(0.40 * inc + 0.45 * nw + 0.15 * 25)
    assert m.low <= m.score - 5 and m.high >= m.score + 5


def test_relations_missing_support_is_45_low(conn):
    values = _values(conn, drop=("support_people", "monthly_meetups", "lonely_often"), extra=[("dating_status", "single", "2026-10-02")])
    r = score_all(values, BENCH, "national", TODAY)["relations"]
    assert r.score == 45 and r.low <= 35 and r.high >= 55 and r.reliability == "low"


def test_career_missing_recruiter_widens_high(conn):
    base = _values(conn)
    full = score_all(base, BENCH, "national", TODAY)["career"]
    values = _without(base, "recruiter_contacts_6m", "offer_ratio", "outside_activity_count")
    c = score_all(values, BENCH, "national", TODAY)["career"]
    assert c.score < full.score
    present = {**values, "recruiter_contacts_6m": 3, "outside_activity_count": 2, "offer_ratio": 1.1}
    best = score_all(present, BENCH, "national", TODAY)["career"].score
    assert c.high >= best and c.high > c.score + 5


def test_checkup_flag_fills_and_lowers_reliability(conn):
    base = _values(conn)
    plain = score_all(base, BENCH, "national", TODAY)["health"]
    values = {**_without(base, "bp_sys", "bp_dia", "fasting_glucose", "ldl", "alt"), "checkup_flag": "normal"}
    h = score_all(values, BENCH, "national", TODAY)["health"]
    assert h.assumed == ()
    assert "checkup_flag" in h.inputs
    order = ("high", "mid", "low")
    assert order.index(h.reliability) == order.index(plain.reliability) + 1
    # 혈압·혈당·LDL·ALT 모두 100: 샘플은 LDL 142(55)였으므로 점수가 오른다
    assert h.raw > plain.raw


def test_profile_missing_scores_only_innate(conn):
    values = _values(conn, drop=("profile_birth_year",))
    s = score_all(values, BENCH, "national", TODAY)
    assert s.keys() == {"height", "education", "family"}
    assert set(area_positions(s).values()) == {None}


def test_female_gets_only_education_family(conn):
    values = {**_values(conn), "profile_sex": "f"}
    assert score_all(values, BENCH, "national", TODAY).keys() == {"education", "family"}


def test_peer_needs_capital_and_dev(conn):
    values = {**_values(conn), "profile_region": "other"}
    assert score_all(values, BENCH, "peer", TODAY) == {}
    assert "career" in score_all(values, BENCH, "national", TODAY)


def test_cert_same_key_latest_only(conn):
    repo = StandingRepo(conn, FakeClock(NOW))
    with transaction(conn):
        repo.add("cert", "toeic:825", date(2026, 9, 1), "manual", None, "mid", NOW)
        repo.add("cert", "toeic:900", date(2026, 10, 1), "manual", None, "mid", NOW)
    values, _ = values_from(repo.latest())
    s = score_all({**values, "profile_birth_year": 1992}, BENCH, "national", TODAY)["intellect"]
    assert s.score == round_half_up(interp(900, BENCH.points("intellect", "toeic"))) == 90
    assert s.assumed == ()


def test_no_cert_is_50_assumed():
    s = score_all({"profile_birth_year": 1992}, BENCH, "national", TODAY)["intellect"]
    assert s.score == 50 and s.assumed == ("cert",) and s.low == 0 and s.high == 100


def test_markets_reweight_missing_axes():
    values = {"height_cm": 180, "education_tier": "top", "family_net_worth_krw": 250_000_000}
    scores = score_all(values, BENCH, "national", TODAY)
    assert set(scores) == {"height", "education", "family"}
    mk = market_scores(scores, BENCH)
    h, e, f = (scores[a].score for a in ("height", "education", "family"))
    assert mk["marriage"].score == round_half_up((h * 10 + f * 10 + e * 9) / 29)
    assert set(mk["marriage"].excluded) == {"career", "money", "looks", "health", "relations", "intellect"}
    assert market_scores({}, BENCH)["career"].score is None


def test_health_area_weighted():
    def mk(axis, v):
        return AxisScore(axis, v, float(v), v - 5, v + 5, "mid", True, (), (), ())

    both = area_positions({"health": mk("health", 80), "looks": mk("looks", 60)})
    assert both["health"] == pytest.approx(72.0)
    assert area_positions({"looks": mk("looks", 60)})["health"] == pytest.approx(60.0)
    assert both["quality_of_life"] is None and both["career"] is None
    assert area_positions({"intellect": mk("intellect", 90)})["learning"] == 90.0

"""9축 점수 계산 (SP13-03). 축마다 작은 함수 하나. 하위 항목 점수는 실수, 축 점수에서만 반올림한다."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from my_planner.standing.bench import Bench, interp
from my_planner.store.repos.standing import Measure

Axis = Literal["career", "money", "health", "looks", "relations", "intellect", "height", "education", "family"]
Cohort = Literal["national", "peer"]
Reliability = Literal["high", "mid", "low"]

AXES: tuple[Axis, ...] = (
    "career", "money", "health", "looks", "relations", "intellect", "height", "education", "family",
)  # fmt: skip
INNATE: tuple[Axis, ...] = ("height", "education", "family")
AXIS_AREA: dict[str, str] = {
    "career": "career",
    "money": "finance",
    "health": "health",
    "looks": "health",
    "relations": "relationships",
    "intellect": "learning",
}
AXIS_LABELS: dict[Axis, str] = {
    "career": "직업",
    "money": "경제력",
    "health": "건강",
    "looks": "외모",
    "relations": "관계",
    "intellect": "자격·학습 실적",
    "height": "키",
    "education": "학벌",
    "family": "집안",
}
AREAS: tuple[str, ...] = ("career", "finance", "health", "relationships", "learning", "quality_of_life")
HEALTH_AREA_WEIGHTS = (60, 40)  # (건강, 외모)
ERR_BASE = 5
ERR_ESTIMATE = 8

Values = Mapping[str, float | str | list[str]]
_REL: tuple[Reliability, ...] = ("high", "mid", "low")


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _clamp(x: int) -> int:
    return max(0, min(100, x))


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


@dataclass(frozen=True)
class AxisScore:
    axis: Axis
    score: int
    raw: float
    low: int
    high: int
    reliability: Reliability
    estimate: bool
    inputs: tuple[str, ...]
    missing: tuple[str, ...]
    assumed: tuple[str, ...]


def values_from(latest: dict[str, Measure | list[Measure]]) -> tuple[Values, dict[str, int]]:
    """(값, 측정값 id). 목록 지표(`cert`)의 id는 `"cert:<':' 앞 키>"`마다 하나."""
    values: dict[str, float | str | list[str]] = {}
    ids: dict[str, int] = {}
    for metric, m in latest.items():
        if isinstance(m, list):
            values[metric] = [x.value_text for x in m if x.value_text]
            ids.update({f"{metric}:{x.value_text.split(':')[0]}": x.id for x in m if x.value_text})
            continue
        values[metric] = m.value_num if m.value_num is not None else (m.value_text or "")
        ids[metric] = m.id
    return values, ids


def _birth_year(values: Values) -> float | None:
    y = values.get("profile_birth_year")
    return float(y) if isinstance(y, int | float) and not isinstance(y, bool) else None


def age_band(values: Values, today: date) -> str | None:
    year = _birth_year(values)
    if year is None:
        return None
    age = today.year - year - 1  # 생일을 모르므로 만 나이를 낮게
    return "30_34" if age <= 34 else "35_39"


def peer_key(values: Values) -> str | None:
    job = values.get("profile_job_family")
    if values.get("profile_region") == "capital" and job in ("ai_ml", "dev_general"):
        return str(job)
    return None


class _R:
    """값을 읽으면서 쓴 지표(있음)와 빈 지표(없음)를 적는다."""

    def __init__(self, values: Values) -> None:
        self._v = values
        self.used: list[str] = []
        self.missing: list[str] = []

    def _note(self, key: str, ok: bool) -> None:
        bucket = self.used if ok else self.missing
        if key not in bucket:
            bucket.append(key)

    def num(self, key: str, note: bool = True) -> float | None:
        """note=False는 대체 경로용: 쓰였을 때 `use`, 하위 항목이 빈 채로 끝났을 때 `lack`을 부른다."""
        v = self._v.get(key)
        ok = isinstance(v, int | float) and not isinstance(v, bool)
        if note:
            self._note(key, ok)
        return float(v) if ok else None  # type: ignore[arg-type]

    def use(self, *keys: str) -> None:
        for k in keys:
            self._note(k, True)

    def lack(self, *keys: str) -> None:
        for k in keys:
            self._note(k, False)

    def txt(self, key: str, note: bool = True) -> str | None:
        v = self._v.get(key)
        ok = isinstance(v, str) and v != ""
        if note:
            self._note(key, ok)
        return v if ok else None  # type: ignore[return-value]

    def certs(self) -> list[str]:
        v = self._v.get("cert")
        found = [c for c in v if isinstance(c, str)] if isinstance(v, list) else []
        self._note("cert", bool(found))
        return found


@dataclass(frozen=True)
class _Ctx:
    cohort: Cohort
    band: str
    peer: str | None


@dataclass(frozen=True)
class _Calc:
    raw: float
    r: _R
    tables: tuple[str, ...]
    assumed: tuple[str, ...] = ()
    lower: int = 0  # 신뢰도를 내리는 단계
    force_low: bool = False
    widen: tuple[int, int] | None = None  # (low, high)
    estimate: bool = False  # 표 표시와 별개로, 추정 경로를 탔을 때


_Fn = Callable[[Values, Bench, _Ctx, "float | None"], "_Calc | None"]


def _at_least(x: float, pairs: Sequence[Sequence[float]], below: float) -> float:
    for lo, s in pairs:
        if x >= lo:
            return s
    return below


def _below_upper(x: float, pairs: Sequence[Sequence[float]], top: float) -> float:
    for up, s in pairs:
        if x < up:
            return s
    return top


def _grade(x: float, cuts: Sequence[float], risk: float | None, scores: Sequence[float]) -> float:
    for cut, s in zip(cuts, scores, strict=False):
        if x >= cut:
            return s
    if risk is None:
        return scores[3]
    return scores[3] if x > risk else scores[4]


def _income_pct(r: _R, b: Bench, c: _Ctx) -> float | None:
    salary = r.num("salary_krw")
    if salary is None:
        return None
    path = ("income", "national", c.band) if c.cohort == "national" else ("income", "peer", c.peer or "")
    return interp(salary / 10_000, b.points(*path))


# ---------------------------------------------------------------- 타고난 축


def _height(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    h = r.num("height_cm")
    if h is None:
        return None
    t = b.table("height")
    return _Calc(_phi((h - t["mean"]) / t["sd"]) * 100, r, ("height",))


def _education(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    tier = r.txt("education_tier")
    t = b.table("education")
    if tier is None or tier not in t["tiers"]:
        return None
    bonus = t["double_major"] if r.txt("double_major") == "yes" else 0
    return _Calc(t["tiers"][tier] + bonus, r, ("education",))


def _family(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    nw = r.num("family_net_worth_krw")
    if nw is None:
        return None
    t = b.table("family")
    x = interp(nw / 10_000, b.points("family", "points"))
    if r.txt("family_parent_60plus") == "yes":
        x += t["parent_60plus"]
    support = r.txt("family_support")
    if support is not None:
        x += t["support"].get(support, 0)
    return _Calc(x, r, ("family",))


# ---------------------------------------------------------------- 외모


def _body_parts(r: _R, t: Mapping[str, Any]) -> dict[str, float]:
    height = r.num("height_cm")
    hm = height / 100 if height else None
    weight = r.num("weight_kg")
    fat = r.num("body_fat_pct")
    ffm = r.num("fat_free_mass_kg", note=False)
    if ffm is None and weight is not None and fat is not None:
        ffm = weight * (1 - fat / 100)
    elif ffm is not None:
        r.use("fat_free_mass_kg")
    if ffm is None:
        r.lack("fat_free_mass_kg")
    parts: dict[str, float] = {}
    waist = r.num("waist_cm")
    if waist is not None:
        w = t["waist"]
        parts["waist"] = 100 if waist < w["full_below"] else 100 - _phi((waist - w["mean"]) / w["sd"]) * 100
    if fat is not None:
        parts["body_fat"] = _below_upper(fat, t["body_fat_bands"], t["body_fat_top"])
    if ffm is not None and hm:
        f = t["ffmi"]
        parts["ffmi"] = _phi((ffm / hm**2 - f["mean"]) / f["sd"]) * 100
    if weight is not None and hm:
        parts["bmi"] = _below_upper(weight / hm**2, t["bmi_bands"], t["bmi_top"])
    return parts


def _looks(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    t = b.table("looks")
    parts = _body_parts(r, t)
    if not parts:
        return None
    default = 50.0 if fill is None else fill
    assumed = [k for k in t["body_weights"] if k not in parts]
    body = sum(w * parts.get(k, default) for k, w in t["body_weights"].items()) / 100
    face = r.num("face_rating")
    grooming = r.num("grooming_rating")
    if face is None:
        assumed.append("face")
    if grooming is None:
        assumed.append("grooming")
    raw = (
        t["body_share"] * body + t["face"] * (default if face is None else face) + t["grooming"] * (default if grooming is None else grooming)
    ) / 100
    return _Calc(raw, r, ("looks",), tuple(assumed), lower=1 if face is not None else 0)


# ---------------------------------------------------------------- 건강


def _health(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    t = b.table("health")
    nfa = t["nfa"][c.band]
    gs = t["grade_scores"]
    sub: dict[str, float] = {}

    estimate = False
    laps = r.num("shuttle_run_laps", note=False)
    run = r.num("run_6k_min", note=False)
    if laps is not None:
        sub["cardio"] = _grade(laps, nfa["shuttle"], nfa["shuttle_risk"], gs)
        r.use("shuttle_run_laps")
    elif run is not None:
        sub["cardio"] = next((s for up, s in t["run_6k"] if run <= up), 10)
        r.use("run_6k_min")
        estimate = True
    else:
        r.lack("shuttle_run_laps", "run_6k_min")
    grip = r.num("grip_rel_pct", note=False)
    lift_keys = ("squat_1rm_kg", "bench_1rm_kg", "deadlift_1rm_kg")
    if grip is not None:
        sub["strength"] = _grade(grip, nfa["grip"], nfa["grip_risk"], gs)
        r.use("grip_rel_pct")
    else:
        lifts = [r.num(k, note=False) for k in lift_keys]
        weight = r.num("weight_kg")
        if None not in lifts and weight:
            sub["strength"] = _at_least(sum(lifts) / weight, t["lift_ratio"], 10)  # type: ignore[arg-type]
            r.use(*lift_keys)
        else:
            r.lack("grip_rel_pct", *lift_keys)
    situp = r.num("situp_per_min")
    if situp is not None:
        sub["endurance"] = _grade(situp, nfa["situp"], None, gs)

    sys_, dia = r.num("bp_sys"), r.num("bp_dia")
    if sys_ is not None and dia is not None:
        sub["bp"] = 10 if (sys_ >= 140 or dia >= 90) else 45 if (sys_ >= 130 or dia >= 80) else 75 if sys_ >= 120 else 100
    glucose, ldl, alt = r.num("fasting_glucose"), r.num("ldl"), r.num("alt")
    if glucose is not None:
        sub["glucose"] = 100 if glucose < 100 else 35 if glucose < 126 else 5
    if ldl is not None:
        sub["ldl"] = 100 if ldl < 130 else 55 if ldl < 160 else 15
    if alt is not None:
        sub["alt"] = 100 if alt <= 30 else 70 if alt <= 40 else 30 if alt <= 80 else 5

    lower = 0
    flag = r.txt("checkup_flag", note=False)
    for k in ("bp", "glucose", "ldl", "alt"):
        if k in sub:
            continue
        if flag in t["checkup_fill"]:
            sub[k] = t["checkup_fill"][flag]
            lower = 1
            r.use("checkup_flag")
        else:
            r.lack("checkup_flag")

    smoking, drinking = r.txt("smoking"), r.txt("drinking")
    if smoking in t["smoking"]:
        sub["smoking"] = t["smoking"][smoking]
    if drinking in t["drinking"]:
        sub["drinking"] = t["drinking"][drinking]
    days = r.num("exercise_days_week")
    if days is not None:
        sub["exercise"] = _at_least(days, t["exercise"], 15)

    if not sub:
        return None
    default = 50.0 if fill is None else fill
    assumed = tuple(k for k in t["weights"] if k not in sub)
    raw = sum(w * sub.get(k, default) for k, w in t["weights"].items()) / 100
    return _Calc(raw, r, ("health",), assumed, lower=lower, estimate=estimate)


# ---------------------------------------------------------------- 직업·경제력


def _career(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    t = b.table("career")
    inc = _income_pct(r, b, c)
    tier = r.num("company_tier")
    if inc is None or tier is None:
        return None
    y = t["years"]
    years = min(float(y["cap"]), min(r.num("years_exp") or 0, y["cap_years"]) * y["per_year"] + (r.num("level_points") or 0))
    recruiter = _at_least(r.num("recruiter_contacts_6m") or 0, t["recruiter"], 0)
    offer = _at_least(r.num("offer_ratio") or 0, t["offer"], 0)
    outside = t["outside_per"] * (r.num("outside_activity_count") or 0)
    raw_points = tier + (r.num("role_points") or 0) + years + outside + recruiter + offer
    pct = interp(raw_points, b.points("career", "raw_pct", c.cohort))
    w = t["weights"]
    return _Calc((w["rubric"] * pct + w["income"] * inc) / 100, r, ("career", "income"))


def _money(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    inc = _income_pct(r, b, c)
    worth = r.num("net_worth_krw")
    if inc is None or worth is None:
        return None
    nw = 5.0 if worth <= 0 else interp(worth / 10_000, b.points("networth", c.cohort))
    rate = r.num("savings_rate_pct", note=False)
    if rate is not None:
        r.use("savings_rate_pct")
    else:
        saved, net = r.num("monthly_saving_krw"), r.num("monthly_net_income_krw")
        if saved is not None and net:
            rate = saved / net * 100
        else:
            r.lack("savings_rate_pct")
    assumed: tuple[str, ...] = ()
    if rate is None:
        sav = float(b.table("saving")["missing"]) if fill is None else fill
        assumed = ("saving",)
    else:
        sav = interp(rate, b.points("saving", "points"))
    w = b.table("money", "weights")
    raw = (w["income"] * inc + w["networth"] * nw + w["saving"] * sav) / 100
    return _Calc(raw, r, ("money", "income", "networth", "saving"), assumed)


# ---------------------------------------------------------------- 관계·자격


def _relations(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    t = b.table("relations")
    people = r.num("support_people")
    widen = None
    if people is None:
        m = t["missing_support"]
        x = float(m["score"])
        widen = (m["low"], m["high"])
    else:
        x = _at_least(people, t["support"], t["support_none"]) + _at_least(r.num("monthly_meetups") or 0, t["meetups"], 0)
    status = r.txt("dating_status")
    if status is not None:
        x += t["dating"].get(status, 0)
    if r.txt("lonely_often") == "yes":
        x += t["lonely_yes"]
    return _Calc(max(0.0, min(100.0, x)), r, ("relations",), force_low=people is None, widen=widen)


def _intellect(v: Values, b: Bench, c: _Ctx, fill: float | None) -> _Calc | None:
    r = _R(v)
    t = b.table("intellect")
    certs = r.certs()
    if not certs:
        return _Calc(float(t["none"]) if fill is None else fill, r, ("intellect",), ("cert",))
    pts = b.points("intellect", "toeic")
    vals = [
        interp(float(cert.split(":")[1]), pts) if cert.startswith("toeic:") else t["base"].get(cert, t["other"])
        for cert in certs
    ]
    return _Calc(min(t["cap"], max(vals) + t["extra_each"] * (len(vals) - 1)), r, ("intellect",))


_FNS: dict[Axis, _Fn] = {
    "career": _career,
    "money": _money,
    "health": _health,
    "looks": _looks,
    "relations": _relations,
    "intellect": _intellect,
    "height": _height,
    "education": _education,
    "family": _family,
}


def _score_of(calc: _Calc) -> int:
    return _clamp(round_half_up(calc.raw))


def _score_axis(axis: Axis, values: Values, bench: Bench, ctx: _Ctx) -> AxisScore | None:
    fn = _FNS[axis]
    calc = fn(values, bench, ctx, None)
    if calc is None:
        return None
    estimate = calc.estimate or any(bench.estimate(t) for t in calc.tables)
    score = _score_of(calc)
    err = ERR_ESTIMATE if estimate else ERR_BASE
    low, high = _clamp(score - err), _clamp(score + err)
    if calc.assumed:
        for fill in (0.0, 100.0):
            alt = fn(values, bench, ctx, fill)
            if alt is not None:
                low, high = min(low, _score_of(alt)), max(high, _score_of(alt))
    if calc.widen:
        low, high = min(low, calc.widen[0]), max(high, calc.widen[1])
    if axis == "career":
        present = dict(values)
        for key, val in bench.table("career", "if_present").items():
            present.setdefault(key, val)
        alt = fn(present, bench, ctx, None)
        if alt is not None:
            high = max(high, _score_of(alt))
    n = len(calc.assumed)
    level = 2 if n >= 2 else 1 if (n == 1 or estimate) else 0
    level = 2 if calc.force_low else min(2, level + calc.lower)
    return AxisScore(
        axis=axis,
        score=score,
        raw=calc.raw,
        low=low,
        high=high,
        reliability=_REL[level],
        estimate=estimate,
        inputs=tuple(calc.r.used),
        missing=tuple(calc.r.missing),
        assumed=calc.assumed,
    )


def score_all(values: Values, bench: Bench, cohort: Cohort, today: date) -> dict[Axis, AxisScore]:
    pk = peer_key(values)
    if cohort == "peer" and pk is None:
        return {}
    band = age_band(values, today)
    if values.get("profile_sex") == "f":  # 지금 기준표는 남성 표뿐
        axes: tuple[Axis, ...] = ("education", "family")
    elif band is None:
        axes = INNATE
    else:
        axes = AXES
    ctx = _Ctx(cohort, band or "30_34", pk)
    out: dict[Axis, AxisScore] = {}
    for axis in AXES:
        if axis in axes and (s := _score_axis(axis, values, bench, ctx)) is not None:
            out[axis] = s
    return out


def area_positions(scores: Mapping[Axis, AxisScore]) -> dict[str, float | None]:
    out: dict[str, float | None] = {a: None for a in AREAS}
    for axis, area in AXIS_AREA.items():
        if area != "health" and axis in scores:
            out[area] = scores[axis].raw  # type: ignore[index]
    hw, lw = HEALTH_AREA_WEIGHTS
    health, looks = scores.get("health"), scores.get("looks")
    if health and looks:
        out["health"] = (hw * health.raw + lw * looks.raw) / (hw + lw)
    elif health or looks:
        out["health"] = (health or looks).raw  # type: ignore[union-attr]
    return out

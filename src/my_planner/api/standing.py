"""`GET /standing`, `GET /standing/measures`, `/status`의 위치 더하기 (SP13 스펙 10, 12장).

- 점수는 읽을 때마다 계산한다(`standing.service.current`). 읽기 전용 연결만 쓴다(`read_handler`).
- 대시보드 기기(`devices.client = 'dashboard'`)는 `/standing*`에 403, `/status`에는 `standing`·`innate` 키가 없다.
  API 토큰과 `client = 'app'` 기기는 통과한다(API 토큰에는 기기 종류가 없다, 스펙 v1.3 ⑮).
- 측정값은 로그에 남기지 않는다(스펙 12장). 이 파일은 로그를 쓰지 않는다.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner.api.models import ApiError, Standing, StandingMeasures, dump
from my_planner.clock import Clock, logical_date, to_iso
from my_planner.standing.drift import debuff, marks
from my_planner.standing.metrics import METRICS
from my_planner.standing.score import (
    AREAS,
    AXES,
    AXIS_AREA,
    AXIS_LABELS,
    INNATE,
    AxisScore,
    Values,
    round_half_up,
)
from my_planner.standing.service import area_drifts, current
from my_planner.status.xp import DEFAULT_RECOVERY_QUESTS
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.standing import Measure, StandingRepo

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

FORBIDDEN_MESSAGE = "이 화면에서는 볼 수 없어요."
HINT_QOL = "삶의 질은 객관적 기준표가 없어요. 만족 점수와 생활 지표(잠, 걸음, 쉬는 저녁)로 봐요."
HINT_BIRTH_YEAR = "태어난 해를 넣으면 생겨요."
HINT_FEMALE = "지금 기준표는 남성 표만 있어요."
# 축 점수가 생기는 데 먼저 있어야 하는 지표(앞에서부터). 영역 안내는 그 영역 축들의 첫 빈 지표를 이름으로 든다
AXIS_NEEDS: dict[str, tuple[str, ...]] = {
    "career": ("salary_krw", "company_tier"),
    "money": ("salary_krw", "net_worth_krw"),
    "health": ("shuttle_run_laps", "grip_rel_pct", "bp_sys"),
    "looks": ("waist_cm", "body_fat_pct", "weight_kg"),
    "relations": ("support_people",),
    "intellect": ("cert",),
}
_REL_ORDER = ("high", "mid", "low")
_LATIN_BATCHIM = frozenset("LMNRlmnr")  # 엘·엠·엔·알
_DIGIT_BATCHIM = frozenset("013678")  # 영·일·삼·육·칠·팔


def dashboard_device(request: web.Request) -> bool:
    """기기 토큰으로 왔고 그 기기의 `client == 'dashboard'`면 True. API 토큰은 False."""
    from my_planner.api.server import DEPS_KEY, DEVICE_ID_KEY

    device_id = request.get(DEVICE_ID_KEY)
    return device_id is not None and request.app[DEPS_KEY].devices.client(device_id) == "dashboard"


def with_object_particle(label: str) -> str:
    """목적격 조사 `을/를`을 받침으로 붙인다. 끝의 괄호 설명은 건너뛰고 앞 낱말을 본다(`ALT(간 수치)` → ALT)."""
    word = label
    while word.endswith(")") and "(" in word:
        word = word[: word.rindex("(")].rstrip()
    last = word[-1] if word else ""
    if "가" <= last <= "힣":
        batchim = (ord(last) - 0xAC00) % 28 != 0
    else:
        batchim = last in _LATIN_BATCHIM or last in _DIGIT_BATCHIM
    return f"{label}{'을' if batchim else '를'}"


def _clamp(x: float) -> int:
    return max(0, min(100, round_half_up(x)))


def _measured_dates(latest: dict[str, Measure | list[Measure]]) -> dict[str, date]:
    out: dict[str, date] = {}
    for metric, m in latest.items():
        if isinstance(m, list):
            if m:
                out[metric] = min(x.measured_on for x in m)
        else:
            out[metric] = m.measured_on
    return out


def _axis_out(s: AxisScore | None, dates: dict[str, date]) -> dict[str, Any] | None:
    if s is None:
        return None
    used = [dates[k] for k in s.inputs if k in dates]
    return {
        "score": s.score, "low": s.low, "high": s.high, "reliability": s.reliability, "estimate": s.estimate,
        "inputs": list(s.inputs), "missing": list(s.missing), "assumed": list(s.assumed),
        "measured_on": min(used).isoformat() if used else None,
    }


def _area_axes(area: str) -> list[str]:
    return [axis for axis, a in AXIS_AREA.items() if a == area]


def _hint(area: str, values: Values, profile_missing: bool) -> str:
    if area == "quality_of_life":
        return HINT_QOL
    if values.get("profile_sex") == "f":
        return HINT_FEMALE
    if profile_missing:
        return HINT_BIRTH_YEAR
    needs = [k for axis in _area_axes(area) for k in AXIS_NEEDS[axis]]
    metric = next((k for k in needs if k not in values), needs[0])
    return f"{with_object_particle(METRICS[metric].label)} 넣으면 생겨요."


def standing_body(conn: sqlite3.Connection, clock: Clock, today: date) -> dict[str, Any]:
    """`GET /standing` 본문(검증 전). `/status`도 `areas`·`innate`를 여기서 가져간다."""
    now = current(conn, clock, today)
    drifts = area_drifts(conn, clock, today, now)
    repo = StandingRepo(conn, clock)
    dates = _measured_dates(repo.latest())
    national, peer = now.scores["national"], now.scores["peer"]
    curve = CurveRepo(conn, clock)

    axes = [
        {
            "axis": axis, "label": AXIS_LABELS[axis], "area": AXIS_AREA.get(axis), "innate": axis in INNATE,
            "national": _axis_out(national.get(axis), dates), "peer": _axis_out(peer.get(axis), dates),
        }
        for axis in AXES
    ]
    areas: dict[str, dict[str, Any]] = {}
    for area in AREAS:
        pos, peer_pos = now.areas["national"][area], now.areas["peer"][area]
        rels = [national[a].reliability for a in _area_axes(area) if a in national]  # type: ignore[index]
        d = drifts.get(area)
        down = debuff(d)
        areas[area] = {
            "score": _clamp(pos) if pos is not None else None,
            "peer_score": _clamp(peer_pos) if peer_pos is not None else None,
            "reliability": max(rels, key=_REL_ORDER.index) if rels else None,
            "drift": marks(d) if d is not None else [],
            "debuff": down,
            "recovery_quest": (curve.area_default(area) or DEFAULT_RECOVERY_QUESTS[area]) if down else None,
            "hint": None if pos is not None else _hint(area, now.values, now.profile_missing),
        }
    innate = [
        {"axis": axis, "label": AXIS_LABELS[axis], "score": national[axis].score if axis in national else None}
        for axis in INNATE
    ]
    markets = {
        name: {
            "national": now.markets["national"][name].score,
            "peer": now.markets["peer"][name].score,
            "excluded": list(now.markets["national"][name].excluded),
        }
        for name in ("marriage", "career")
    }
    return {
        "profile_missing": now.profile_missing,
        "bench": {"version": now.bench.version, "effective_from": now.bench.effective_from.isoformat()},
        "axes": axes,
        "areas": areas,
        "innate": innate,
        "markets": markets,
        "measures_count": len(repo.active()),
    }


def _today(deps: ApiDeps) -> date:
    return logical_date(deps.clock.now(), deps.settings.timezone, deps.settings.day_boundary)


def _forbid_dashboard(request: web.Request) -> None:
    if dashboard_device(request):
        raise ApiError(403, "forbidden", FORBIDDEN_MESSAGE)


def get_standing(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    _forbid_dashboard(request)
    return dump(Standing, standing_body(conn, deps.clock, _today(deps)))


def get_standing_measures(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    _forbid_dashboard(request)
    rows = []
    for m in StandingRepo(conn, deps.clock).active():
        d = METRICS.get(m.metric)
        rows.append({
            "id": m.id, "metric": m.metric, "label": d.label if d else m.metric,
            "value_num": m.value_num, "value_text": m.value_text, "unit": d.unit if d else None,
            "measured_on": m.measured_on.isoformat(), "source_kind": m.source_kind, "reliability": m.reliability,
            "created_at": to_iso(m.created_at),
        })
    return dump(StandingMeasures, {"measures": rows})


def status_standing(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any] | None:
    """`/status`에 더할 `{"areas", "innate"}`. 대시보드 기기면 None(키를 넣지 않는다)."""
    if dashboard_device(request):
        return None
    body = standing_body(conn, deps.clock, _today(deps))
    return {"areas": body["areas"], "innate": body["innate"]}

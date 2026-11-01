"""인생 리포트와 "전체 진단"(SP15 스펙 6.2, 8장, 10장).

- 전체 진단 상한(계획 Task 12): 하루 1회, 같은 ISO 주 2회, 사용자 몫 안의 남은 두뇌 호출. 진단한 날은 `app_state`의
  `FULL_DAYS_KEY`(ISO 날짜 JSON 목록, 지난 14일만)에 둔다. 리포트를 저장한 진단만 센다: `mark_full_diagnosis`는 리포트
  저장(`tools.panel.save_life_report`)이 그 트랜잭션 안에서 부른다.
- 리포트 검사(계획 Task 13): 두뇌가 넘긴 칸(`LifeReport`)을 검사하고 서버 칸(`scores` 사본, 추정 표시, 맺음말)을 더한다.
- 분기 회고 뒤 칩(10장, D3): 비서 앱 답에 "전체 진단 해 볼까요?" 칩을 한 분기 한 번 붙인다(자동 실행은 없다).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    model_validator,
)

from my_planner.clock import period_of, to_iso
from my_planner.panel.budget import week_key
from my_planner.panel.evidence import PANEL_EXTRA_BANNED
from my_planner.standing.score import AXES
from my_planner.store.repos.panel import PanelRepo
from my_planner.store.repos.state import StateRepo
from my_planner.tools.ui import banned_words

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.domain import RunContext

FULL_DAYS_KEY = "panel_full_diagnosis_days"
FULL_PER_DAY = 1
FULL_PER_WEEK = 2
# 사용자 몫(`MOMENTS_RESERVE_CALLS`, 하루 마지막 10회 창) 안에서 이보다 적게 남았으면 시작하지 않는다(스펙 6.2)
FULL_MIN_CALLS_LEFT = 3
FULL_KEEP_DAYS = 14

FullBlock = Literal["day", "week", "calls"]
FULL_BLOCK_REPLIES: dict[FullBlock, str] = {
    "day": "전체 진단은 오늘 이미 했어요. 내일 다시 할 수 있어요.",
    "week": "전체 진단은 이번 주에 두 번 했어요. 다음 주에 다시 할 수 있어요.",
    "calls": "오늘은 두뇌 호출이 얼마 없어 전체 진단을 시작하지 않았어요. 내일 해 볼까요?",
}
# 전체 진단 두뇌 호출이 오류(시간 초과 포함)로 끝났다. 다시 부르지 않는다(디스패처)
FULL_FAILED_REPLY = "전체 진단이 중간에 멈췄어요. 횟수에는 세지 않았어요. 잠시 뒤 다시 눌러 주세요."


def full_diagnosis_days(state: StateRepo) -> list[date]:
    """기록된 진단 날짜(오래된 것부터, 겹침 없음). 없거나 깨진 값은 빈 목록."""
    try:
        raw = json.loads(state.get(FULL_DAYS_KEY) or "[]")
    except ValueError:
        return []
    days: set[date] = set()
    for v in raw if isinstance(raw, list) else []:
        try:
            days.add(date.fromisoformat(v))
        except (TypeError, ValueError):
            continue
    return sorted(days)


def full_diagnosis_block(state: StateRepo, today: date, calls_left: int) -> FullBlock | None:
    """전체 진단을 막는 이유. `today`는 논리적 날짜, `calls_left`는 사용자 몫 창 안에서 남은 두뇌 호출 수."""
    days = full_diagnosis_days(state)
    if sum(d == today for d in days) >= FULL_PER_DAY:
        return "day"
    week = today.isocalendar()[:2]
    if sum(d.isocalendar()[:2] == week for d in days) >= FULL_PER_WEEK:
        return "week"
    if calls_left < FULL_MIN_CALLS_LEFT:
        return "calls"
    return None


def mark_full_diagnosis(state: StateRepo, today: date) -> None:
    """오늘을 진단한 날로 적는다. 지난 `FULL_KEEP_DAYS`일(오늘 포함)만 남긴다."""
    since = today - timedelta(days=FULL_KEEP_DAYS - 1)
    days = sorted({d for d in full_diagnosis_days(state) if d >= since} | {today})
    state.set(FULL_DAYS_KEY, json.dumps([d.isoformat() for d in days]))


# --- 인생 리포트 (10장, 계획 Task 13) ---

PSYCH_CLOSING = "이 숫자는 이번 분기 조건의 측정값이지 나 자신이 아니다."
REPORT_VERSION = 1
ROADMAP_MAX_DAYS = 90
REPORT_EXPERTS: tuple[str, ...] = ("career", "finance", "health", "image", "relationship", "psych")  # `panel.experts.EXPERTS`
LEVER_AXES: tuple[str, ...] = tuple(a for a in AXES if a not in ("height", "education", "family"))  # 타고난 셋 뺌

MSG_REPORT_SHAPE = "report가 리포트 모양이 아니에요."
MSG_REPORT_FIELD = "리포트 {loc} 칸이 맞지 않아요. {hint}"
MSG_REPORT_BANNED = "리포트에 쓰지 않는 말이 있어요: {word}"
MSG_REPORT_THIS_WEEK = "this_week에는 이번 주에 낸 패널 제안 id만 넣어요."
_HINTS: dict[str, str] = {
    "summary": "summary는 line(120자 한 줄)과 paths(80자 한 줄 정확히 3개)예요.",
    "levers": (
        f"levers는 1~12개, 각각 action(60자), axis({', '.join(LEVER_AXES)} 가운데 하나), "
        "strength(weak, mid, strong)예요."
    ),
    "experts": (
        f"experts는 전문가 {len(REPORT_EXPERTS)}명({', '.join(REPORT_EXPERTS)})이 하나씩, 각각 line(120자), "
        "prescriptions(120자 3~4줄), avoid(120자 1~3줄)예요."
    ),
    "scenario": "scenario는 do와 dont(각 400자)예요.",
    "roadmap": f"roadmap은 1~6개, 각각 track(40자), kpi(80자), start·end(YYYY-MM-DD, end는 start부터 {ROADMAP_MAX_DAYS}일 안)예요.",
    "this_week": "this_week는 이번 주 패널 제안 id 0~5개예요.",
    "questions": "questions는 120자 한 줄 0~5개예요.",
}


Line40 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Line60 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Line80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Line120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Line400 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportSummary(_Strict):
    line: Line120
    paths: list[Line80] = Field(min_length=3, max_length=3)


class ReportLever(_Strict):
    action: Line60
    axis: Literal["career", "money", "health", "looks", "relations", "intellect"]
    strength: Literal["weak", "mid", "strong"]


class ReportExpert(_Strict):
    expert: Literal["career", "finance", "health", "image", "relationship", "psych"]
    line: Line120
    prescriptions: list[Line120] = Field(min_length=3, max_length=4)
    avoid: list[Line120] = Field(min_length=1, max_length=3)


class ReportScenario(_Strict):
    do: Line400
    dont: Line400


class ReportTrack(_Strict):
    track: Line40
    kpi: Line80
    start: date
    end: date

    @model_validator(mode="after")
    def _span(self) -> ReportTrack:
        if not self.start <= self.end <= self.start + timedelta(days=ROADMAP_MAX_DAYS):
            raise ValueError("span")
        return self


class LifeReport(_Strict):
    """두뇌가 넘기는 칸(10장). 서버 칸(`scores`, `closing`, `version`, `scenario.estimate`)은 받지 않는다."""

    summary: ReportSummary
    levers: list[ReportLever] = Field(min_length=1, max_length=12)
    experts: list[ReportExpert] = Field(min_length=len(REPORT_EXPERTS), max_length=len(REPORT_EXPERTS))
    scenario: ReportScenario
    roadmap: list[ReportTrack] = Field(min_length=1, max_length=6)
    this_week: list[Annotated[StrictInt, Field(ge=1)]] = Field(max_length=5)
    questions: list[Line120] = Field(max_length=5)

    @model_validator(mode="after")
    def _one_each(self) -> LifeReport:
        if {e.expert for e in self.experts} != set(REPORT_EXPERTS):
            raise ValueError("experts")
        if len(set(self.this_week)) != len(self.this_week):
            raise ValueError("this_week")
        return self


def _first_error(e: ValidationError) -> str:
    """pydantic 첫 오류를 한국어 한 줄로. 값은 넣지 않는다(칸 이름과 번호만)."""
    err = e.errors()[0]
    loc = [str(p) for p in err["loc"]]
    if not loc:  # 모델 검사(`_one_each`)는 그 칸 이름을 오류 글에 실었다
        msg = str(err.get("msg", ""))
        loc = [next((k for k in _HINTS if k in msg), "")]
    top = loc[0]
    if top not in _HINTS:
        return MSG_REPORT_SHAPE
    return MSG_REPORT_FIELD.format(loc=".".join(loc), hint=_HINTS[top])


def _texts(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [t for x in v.values() for t in _texts(x)]
    if isinstance(v, list):
        return [t for x in v for t in _texts(x)]
    return []


def report_scores(conn: sqlite3.Connection, clock: Clock, today: date) -> dict[str, dict[str, Any]]:
    """축마다 `{national, peer, reliability, estimate}`(저장 시점 값의 사본). 신뢰도·추정은 전국 점수, 없으면 또래."""
    from my_planner.standing.service import current

    now = current(conn, clock, today)
    out: dict[str, dict[str, Any]] = {}
    for axis in AXES:
        nat, peer = now.scores["national"].get(axis), now.scores["peer"].get(axis)
        ref = nat if nat is not None else peer
        out[axis] = {
            "national": nat.score if nat is not None else None,
            "peer": peer.score if peer is not None else None,
            "reliability": ref.reliability if ref is not None else None,
            "estimate": ref.estimate if ref is not None else False,
        }
    return out


def build_report(conn: sqlite3.Connection, clock: Clock, today: date, raw: Any) -> dict[str, Any] | str:
    """검사하고 저장할 JSON을 돌려준다. 실패면 첫 오류 한 줄(한국어)."""
    if not isinstance(raw, dict):
        return MSG_REPORT_SHAPE
    try:
        rep = LifeReport.model_validate(raw)
    except ValidationError as e:
        return _first_error(e)
    body = rep.model_dump(mode="json")
    for t in _texts(body):
        for word in (*banned_words(), *PANEL_EXTRA_BANNED):
            if word in t:
                return MSG_REPORT_BANNED.format(word=word)
    week = week_key(today)
    repo = PanelRepo(conn, clock)
    for sid in rep.this_week:
        s = repo.suggestion(sid)
        if s is None or s.week != week:
            return MSG_REPORT_THIS_WEEK
    return {
        "version": REPORT_VERSION,
        "summary": body["summary"],
        "scores": report_scores(conn, clock, today),
        "levers": body["levers"],
        "experts": body["experts"],
        "scenario": {**body["scenario"], "estimate": True},
        "roadmap": body["roadmap"],
        "this_week": body["this_week"],
        "questions": body["questions"],
        "closing": PSYCH_CLOSING,
    }


# --- 분기 회고 뒤 "전체 진단" 칩 (10장, D3) ---

FULL_CHIP_KEY = "panel_full_chip:{period}"


def _prev_quarter(period: str) -> str:
    year, q = int(period[:4]), int(period[-1])
    return f"{year - 1}-Q4" if q == 1 else f"{year}-Q{q - 1}"


def full_chip_due(
    conn: sqlite3.Connection, state: StateRepo, ctx: RunContext, conversation_started_at: datetime, *, today: date
) -> str | None:
    """칩을 붙일 분기, 아니면 None. 비서 앱 대화이고, 이 호출의 사건이나 이 대화가 열린 뒤 활동(되돌리지 않은 것)에
    영역 점수 기록이 있고, 그 분기가 지금·직전 분기이고, 그 분기에 아직 붙인 적이 없을 때. 최근 기록부터 본다."""
    if ctx.agent != "secretary" or ctx.channel != "app":
        return None
    now = period_of("quarter", today)
    allowed = {now, _prev_quarter(now)}
    periods = [e.data.get("period") for e in reversed(ctx.events) if e.kind == "area_scores_recorded" and e.data]
    periods += [
        str(r[0]).removeprefix("areas:") for r in conn.execute(
            "SELECT target FROM activity WHERE kind = 'area_scores_recorded' AND undone_at IS NULL AND at >= ? "
            "AND target LIKE 'areas:%' ORDER BY at DESC, id DESC",
            (to_iso(conversation_started_at),),
        )
    ]
    for p in periods:
        if p in allowed and state.get(FULL_CHIP_KEY.format(period=p)) is None:
            return p
    return None

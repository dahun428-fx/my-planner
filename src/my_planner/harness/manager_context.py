"""라이프 매니저의 새 두뇌 세션 앞머리 (SP15 스펙 5.3, 계획 Task 10). 모두 DB에서 읽는다(ADR 0014).

블록 순서: 지금, 상태, 내 속도 표, 주간 제안, 결정, 내가 한 말, 예측, 다른 상대. 빈 블록은 제목 + `- 없음`.
다른 상대의 대화는 제목과 요약만 넣는다(원문 없음). 이어진 세션에는 메시지마다 `budget_block`(주간 제안)만 붙는다.

이 글에는 측정값 숫자(축 점수, 예측 값)와 내가 한 말이 들어간다. 그래서 이 모듈은 로그를 남기지 않는다(스펙 13장).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from my_planner.clock import Clock, local, logical_date
from my_planner.domain import Agent
from my_planner.panel.budget import remaining
from my_planner.panel.pace import load_pace, pace_text
from my_planner.standing import service as standing_service
from my_planner.standing.score import AREAS, AXES, AXIS_LABELS, INNATE
from my_planner.status.xp import AREA_LABELS
from my_planner.store.migrations.hooks import SEED_DECISION_KEY
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.curve import CurveRepo
from my_planner.store.repos.panel import PanelRepo, Prediction, Suggestion
from my_planner.store.repos.state import StateRepo

NONE_LINE = "- 없음"
WEEKDAY = "월화수목금토일"
STATEMENTS_MAX = 30
PREDICTIONS_LOOKED = 5  # `recent_predictions(5)`
OTHERS_PER_AGENT = 3
OTHERS_DAYS = 7
OTHER_SUMMARY_MAX = 120
OPEN_SUGGESTION_STATES = ("proposed", "accepted")
OTHER_AGENTS: tuple[tuple[Agent, str], ...] = (("secretary", "비서"), ("mate", "운동메이트"))


def _num(v: float) -> str:
    """3.0 → `3`, -1.5 → `-1.5`. 뺄셈의 부동소수 꼬리(0.30000000000000004)는 둘째 자리에서 자른다."""
    v = round(float(v), 2)
    return str(int(v)) if v.is_integer() else str(v)


def _area(area: str | None) -> str:
    return AREA_LABELS.get(area, area) if area is not None else "-"


def _block(title: str, lines: list[str]) -> str:
    return "\n".join([title, *(lines or [NONE_LINE])])


def _now_block(now: datetime, tz: str) -> str:
    t = local(now, tz)
    return f"## 지금\n{t:%Y-%m-%d} ({WEEKDAY[t.weekday()]}) {t:%H:%M}"


def _status_block(conn: sqlite3.Connection, clock: Clock, today: date) -> str:
    national = standing_service.current(conn, clock, today).scores["national"]
    lines: list[str] = []
    blanks: list[str] = []
    for axis in AXES:
        if axis in INNATE:
            continue
        s = national.get(axis)
        if s is None:
            blanks.append(AXIS_LABELS[axis])
        else:
            lines.append(f"- {AXIS_LABELS[axis]} {s.score} (신뢰도 {s.reliability})")
    lines.append(f"- 빈칸: {', '.join(blanks) if blanks else '없음'}")
    curve = CurveRepo(conn, clock)
    periods = curve.latest_area_periods(1)
    if periods:
        by_area = {a.area: a.score for a in curve.area_scores(periods[0])}
        parts = [f"{AREA_LABELS[a]} {by_area[a]}" for a in AREAS if a in by_area]
        lines.append(f"- 영역 만족({periods[0]}): {' · '.join(parts)}")
    return _block("## 상태", lines)


def budget_block(conn: sqlite3.Connection, clock: Clock, today: date) -> str:
    """`## 주간 제안`: 이번 주 더 낼 수 있는 수와 열린 제안(받기 전·받은 것, 최신 먼저). `today`는 논리적 날짜."""
    repo = PanelRepo(conn, clock)
    left = remaining(repo, StateRepo(conn, clock), today)
    open_: list[Suggestion] = [s for state in OPEN_SUGGESTION_STATES for s in repo.suggestions(state=state)]
    open_.sort(key=lambda s: (s.created_at, s.id), reverse=True)
    lines = [f"- 이번 주 더 낼 수 있는 수: {left}"]
    lines += [f"- 열린 제안: suggestion:{s.id} {s.title} · {_area(s.area)} · {s.state}" for s in open_]
    if not open_:
        lines.append("- 열린 제안: 없음")
    return _block("## 주간 제안", lines)


def _decisions_block(repo: PanelRepo) -> str:
    """오래된 것부터(`created_at`, `id`). 3장 결정(`career_first`)은 늘 맨 위다(T17, 1장 10 충돌 순서)."""
    rows = repo.active_statements(["decision"])
    rows.sort(key=lambda s: s.key != SEED_DECISION_KEY)  # 안정 정렬: 나머지는 오래된 순서 그대로
    return _block("## 결정", [f"- decision:{s.key} {s.text}" for s in rows])


def _statements_block(repo: PanelRepo) -> str:
    rows = repo.active_statements(["fact", "preference"])[::-1][:STATEMENTS_MAX]
    return _block("## 내가 한 말", [f"- statement:{s.id} {_area(s.area)} {s.text}" for s in rows])


def _prediction_line(p: Prediction) -> str | None:
    head = f"- {p.metric} 예측 {_num(p.predicted)} · 기한 {p.due.isoformat()}"
    if p.actual is not None:
        return f"{head} · 실제 {_num(p.actual)} · 차이 {_num(p.actual - p.predicted)}"
    if p.checked_at is None:
        return f"{head} · 측정 필요"
    return None  # 창이 닫혀 값 없이 맞춰 본 예측(Task 14)은 더 묻지 않는다


def _predictions_block(repo: PanelRepo, today: date) -> str:
    lines = [
        line for p in repo.recent_predictions(PREDICTIONS_LOOKED)
        if p.due < today and (line := _prediction_line(p)) is not None
    ]
    return _block("## 예측", lines)


def _others_block(conn: sqlite3.Connection, clock: Clock, now: datetime, tz: str, boundary: time) -> str:
    """비서·운동메이트 앱 대화 가운데 지난 7일에 말이 있었던 최근 3개씩. 제목과 요약만(원문 없음, ADR 0014)."""
    convs = ConversationsRepo(conn, clock)
    since = now - timedelta(days=OTHERS_DAYS)
    lines: list[str] = []
    for agent, label in OTHER_AGENTS:
        for c in convs.recent(channel="app", agent=agent, since=since, limit=OTHERS_PER_AGENT):
            if not c.title and not c.summary:
                continue  # 아직 요약하지 않은 대화: 넣을 글이 없다
            day = logical_date(c.last_message_at, tz, boundary)
            line = f"- {label} {day.month}/{day.day} {c.title or '제목 없음'}"
            if c.summary:
                line += f": {c.summary[:OTHER_SUMMARY_MAX]}"
            lines.append(line)
    return _block("## 다른 상대", lines)


def build_manager_preamble(
    conn: sqlite3.Connection, clock: Clock, *, now: datetime, tz: str, boundary: time
) -> str:
    """스펙 5.3 앞머리(새 세션에만). 읽기만 한다. `tz`·`boundary`는 설정의 시간대·하루 경계."""
    today = logical_date(now, tz, boundary)
    panel = PanelRepo(conn, clock)
    return "\n\n".join([
        _now_block(now, tz),
        _status_block(conn, clock, today),
        pace_text(load_pace(conn, clock, today, tz=tz, boundary=boundary)),
        budget_block(conn, clock, today),
        _decisions_block(panel),
        _statements_block(panel),
        _predictions_block(panel, today),
        _others_block(conn, clock, now, tz, boundary),
    ])

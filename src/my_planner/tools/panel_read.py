"""라이프 매니저·전문가 읽기 도구 (SP15 스펙 6.1). `Tools`가 이 mixin을 상속한다.

모두 읽기만 하고 로그를 남기지 않는다(제목·말·측정값이 들어 있다). 결과는 id(패널 근거 참조 `ref`)·날짜·값이다.
전문가마다 받는 도구는 `mcp_adapter.EXPERT_TOOLS`가 정한다: 영역을 좁힌 도구(`read_measures_career` 같은)는
그 영역 밖을 돌려주지 않는다. 일정 모양(`read_schedule_shape`)은 제목·메모를 싣지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from my_planner.clock import from_iso, local, logical_date, to_iso
from my_planner.domain import RunContext
from my_planner.panel.budget import week_key, weeks_before
from my_planner.standing.bench import load_bench
from my_planner.standing.metrics import metric_area
from my_planner.tools._base import _err, _tool
from my_planner.tools.standing import latest_measure_rows

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.body import BodyRepo
    from my_planner.store.repos.conditions import ConditionsRepo
    from my_planner.store.repos.curve import CurveRepo
    from my_planner.store.repos.events import EventsRepo
    from my_planner.store.repos.moments import MomentsRepo
    from my_planner.store.repos.panel import PanelRepo
    from my_planner.store.repos.photos import PhotosRepo
    from my_planner.store.repos.standing import StandingRepo
    from my_planner.store.repos.tasks import TasksRepo

CONDITION_DAYS_DEFAULT, CONDITION_DAYS_MAX = 28, 56
BODY_DAYS_DEFAULT, BODY_DAYS_MAX = 28, 56
MOMENT_DAYS_DEFAULT, MOMENT_DAYS_MAX = 90, 180
SCHEDULE_DAYS_DEFAULT, SCHEDULE_DAYS_MAX = 14, 28
RESULT_WEEKS_DEFAULT, RESULT_WEEKS_MAX = 8, 12
TASK_ENDED_DAYS = 56  # 영역별 할 일: 열린 것 + 이 기간에 끝내거나 버린 것
TASK_LIMIT = 50

# 외모 지표(SP15 6.1 이미지 컨설턴트, 계획 Task 7 그대로)
LOOKS_METRICS: frozenset[str] = frozenset({
    "weight_kg", "body_fat_pct", "fat_free_mass_kg", "skeletal_muscle_kg", "waist_cm", "face_rating",
    "grooming_rating", "height_cm",
})
_BENCH_META = frozenset({"version", "effective_from"})
_BENCH_FIELDS = ("source", "year", "estimate")


def _days_error(lo: int, hi: int) -> str:
    return f"days는 {lo}~{hi} 사이 정수예요."


def _int_in(v: Any, default: int, hi: int) -> int | None:
    n = default if v is None else v
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= hi:
        return None
    return n


class PanelReadTools:
    """`read_*`, `list_statements`, `read_benchmark`, `list_chat_photos`(SP15 6.1)."""

    if TYPE_CHECKING:
        clock: Clock
        tz: Any
        boundary: time
        tasks: TasksRepo
        conditions: ConditionsRepo | None
        body: BodyRepo | None
        moments: MomentsRepo | None
        curve: CurveRepo | None
        events: EventsRepo | None
        photos: PhotosRepo | None
        standing: StandingRepo | None
        panel: PanelRepo | None

        def today(self) -> date: ...

    # --- 기록 ---

    @_tool
    def read_conditions(self, ctx: RunContext, days: Any = CONDITION_DAYS_DEFAULT) -> dict[str, Any]:
        """오늘 포함 `days`일의 컨디션 점수(메모 없음), 오래된 날부터."""
        n = _int_in(days, CONDITION_DAYS_DEFAULT, CONDITION_DAYS_MAX)
        if n is None:
            return _err(_days_error(1, CONDITION_DAYS_MAX))
        if self.conditions is None:
            return {"items": []}
        today = self.today()
        rows = self.conditions.between(today - timedelta(days=n - 1), today)
        return {"items": [{"date": c.date.isoformat(), "score": c.score} for c in rows]}

    @_tool
    def read_body_days(self, ctx: RunContext, days: Any = BODY_DAYS_DEFAULT) -> dict[str, Any]:
        """오늘 포함 `days`일의 걸음·잠, 오래된 날부터."""
        n = _int_in(days, BODY_DAYS_DEFAULT, BODY_DAYS_MAX)
        if n is None:
            return _err(_days_error(1, BODY_DAYS_MAX))
        if self.body is None:
            return {"items": []}
        today = self.today()
        rows = self.body.between(today - timedelta(days=n - 1), today)
        return {"items": [
            {"date": d.date.isoformat(), "steps": d.steps, "sleep_minutes": d.sleep_minutes} for d in rows
        ]}

    @_tool
    def read_moments(self, ctx: RunContext, days: Any = MOMENT_DAYS_DEFAULT) -> dict[str, Any]:
        """오늘 포함 `days`일의 이룬 순간(숨긴 것 뺌), 최근 날부터."""
        n = _int_in(days, MOMENT_DAYS_DEFAULT, MOMENT_DAYS_MAX)
        if n is None:
            return _err(_days_error(1, MOMENT_DAYS_MAX))
        if self.moments is None:
            return {"items": []}
        today = self.today()
        rows = self.moments.between(today - timedelta(days=n - 1), today, include_hidden=False)
        return {"items": [
            {"id": m.id, "date": m.date.isoformat(), "text": m.text, "area": m.area} for m in rows
        ]}

    @_tool
    def read_reviews(self, ctx: RunContext) -> dict[str, Any]:
        """분기 회고의 영역 점수, 최근 분기부터."""
        if self.curve is None:
            return {"items": []}
        rows = self.curve.conn.execute(
            "SELECT period, area, score, note FROM curve_area_scores ORDER BY period DESC, area"
        ).fetchall()
        return {"items": [
            {"ref": f"review:{r['period']}:{r['area']}", "period": r["period"], "area": r["area"],
             "score": r["score"], "note": r["note"]}
            for r in rows
        ]}

    # --- 측정값 ---

    @_tool
    def read_measures_all(self, ctx: RunContext) -> dict[str, Any]:
        return {"measures": latest_measure_rows(self.standing, lambda m: not m.startswith("profile_"))}

    @_tool
    def read_measures_career(self, ctx: RunContext) -> dict[str, Any]:
        return {"measures": latest_measure_rows(self.standing, lambda m: metric_area(m) == "career")}

    @_tool
    def read_measures_finance(self, ctx: RunContext) -> dict[str, Any]:
        return {"measures": latest_measure_rows(
            self.standing, lambda m: metric_area(m) == "finance" or m == "salary_krw"
        )}

    @_tool
    def read_measures_looks(self, ctx: RunContext) -> dict[str, Any]:
        return {"measures": latest_measure_rows(self.standing, LOOKS_METRICS.__contains__)}

    @_tool
    def read_measures_relationships(self, ctx: RunContext) -> dict[str, Any]:
        return {"measures": latest_measure_rows(self.standing, lambda m: metric_area(m) == "relationships")}

    # --- 영역별 할 일 ---

    def _tasks_in_area(self, area: str) -> dict[str, Any]:
        """그 영역의 열린 할 일 + 지난 56일(오늘 포함)에 끝내거나 버린 것, `TASK_LIMIT`개까지.

        열린 것이 먼저(하려는 날순), 끝난 것은 최근 것부터. 버린 때는 마지막 `dropped` 사건 시각이다."""
        start = self.today() - timedelta(days=TASK_ENDED_DAYS - 1)
        since = to_iso(datetime.combine(start, self.boundary, tzinfo=self.tz))
        rows = self.tasks.conn.execute(
            "SELECT * FROM (SELECT t.id, t.title, t.status, t.planned_for, "
            "CASE t.status WHEN 'done' THEN t.completed_at WHEN 'dropped' THEN "
            "(SELECT MAX(e.at) FROM task_events e WHERE e.task_id = t.id AND e.kind = 'dropped') END AS ended_at "
            "FROM tasks t WHERE t.deleted_at IS NULL AND t.status IN ('open', 'done', 'dropped') "
            "AND EXISTS (SELECT 1 FROM task_areas a WHERE a.task_id = t.id AND a.area = ?)) "
            "WHERE status = 'open' OR ended_at >= ? "
            "ORDER BY status <> 'open', planned_for IS NULL, CASE WHEN status = 'open' THEN planned_for END, "
            "ended_at DESC, id LIMIT ?",
            (area, since, TASK_LIMIT),
        ).fetchall()
        return {"items": [
            {
                "ref": f"task:{r['id']}", "title": r["title"], "status": r["status"], "planned_for": r["planned_for"],
                "completed_on": (
                    logical_date(from_iso(r["ended_at"]), self.tz, self.boundary).isoformat()
                    if r["ended_at"] is not None and r["status"] != "open" else None
                ),
            }
            for r in rows
        ]}

    @_tool
    def read_tasks_career(self, ctx: RunContext) -> dict[str, Any]:
        return self._tasks_in_area("career")

    @_tool
    def read_tasks_finance(self, ctx: RunContext) -> dict[str, Any]:
        return self._tasks_in_area("finance")

    @_tool
    def read_tasks_relationships(self, ctx: RunContext) -> dict[str, Any]:
        return self._tasks_in_area("relationships")

    # --- 일정 모양 ---

    @_tool
    def read_schedule_shape(self, ctx: RunContext, days: Any = SCHEDULE_DAYS_DEFAULT) -> dict[str, Any]:
        """오늘부터 `days`일의 일정 시각·길이·영역(제목·메모 없음). 시각은 현지 "HH:MM"."""
        n = _int_in(days, SCHEDULE_DAYS_DEFAULT, SCHEDULE_DAYS_MAX)
        if n is None:
            return _err(_days_error(1, SCHEDULE_DAYS_MAX))
        if self.events is None:
            return {"items": []}
        today = self.today()
        items = []
        for o in self.events.occurrences(today, today + timedelta(days=n - 1)):
            items.append({
                "ref": f"event:{o.event_id}", "date": o.date.isoformat(),
                "start": f"{local(o.start, self.tz):%H:%M}" if o.start is not None else None,
                "minutes": int((o.end - o.start).total_seconds() // 60) if o.start and o.end else None,
                "all_day": o.all_day, "area": o.area.value if o.area is not None else None,
            })
        return {"items": items}

    # --- 내가 한 말, 패널 결과 ---

    @_tool
    def list_statements(self, ctx: RunContext) -> dict[str, Any]:
        """지우지 않은 내가 한 말, 오래된 것부터. 결정은 `decision:<key>`, 그 밖은 `statement:<id>`."""
        if self.panel is None:
            return {"items": []}
        return {"items": [
            {
                "ref": f"decision:{s.key}" if s.kind == "decision" and s.key else f"statement:{s.id}",
                "kind": s.kind, "area": s.area, "text": s.text,
            }
            for s in self.panel.active_statements()
        ]}

    @_tool
    def read_panel_results(self, ctx: RunContext, weeks: Any = RESULT_WEEKS_DEFAULT) -> dict[str, Any]:
        """이번 주 포함 `weeks`주(논리적 날짜의 ISO 주)의 패널 제안과 그 결과, 오래된 것부터."""
        n = _int_in(weeks, RESULT_WEEKS_DEFAULT, RESULT_WEEKS_MAX)
        if n is None:
            return _err(f"weeks는 1~{RESULT_WEEKS_MAX} 사이 정수예요.")
        if self.panel is None:
            return {"items": []}
        week = week_key(self.today())
        return {"items": [
            {"ref": f"suggestion:{s.id}", "title": s.title, "area": s.area, "state": s.state,
             "dismiss_reason": s.dismiss_reason, "week": s.week}
            for s in self.panel.in_weeks([*weeks_before(week, n - 1), week])
        ]}

    # --- 외부 기준 ---

    @_tool
    def read_benchmark(self, ctx: RunContext, key: Any = None) -> dict[str, Any]:
        """오늘 기준표의 맨 위 표 하나. `key`가 없으면 키 목록."""
        raw = load_bench(self.today()).raw
        keys = [k for k, v in raw.items() if k not in _BENCH_META and isinstance(v, Mapping)]
        if key is None:
            return {"keys": keys}
        if not isinstance(key, str) or key not in keys:
            return _err(f"기준표에 없는 키예요. 키: {', '.join(keys)}")
        node = raw[key]
        return {
            "ref": f"bench:{key}", "source": node.get("source"), "year": node.get("year"),
            "estimate": bool(node.get("estimate")),
            "table": {k: v for k, v in node.items() if k not in _BENCH_FIELDS},
        }

    # --- 사진 ---

    @_tool
    def list_chat_photos(self, ctx: RunContext) -> dict[str, Any]:
        """이 대화(`ctx.conversation_id`)의 메시지에 붙은 사진의 번호·날짜·읽은 글(이미지 바이트 없음)."""
        if self.photos is None or ctx.conversation_id is None:
            return {"items": []}
        by_message = self.photos.for_conversation(self.tasks.conn, ctx.conversation_id)
        return {"items": [
            {"photo_id": p.id, "date": logical_date(p.created_at, self.tz, self.boundary).isoformat(),
             "read_text": p.read_text}
            for photos in by_message.values() for p in photos
        ]}

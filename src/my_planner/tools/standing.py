"""측정값 도구 (SP13 스펙 6.3~6.5, 10장 X14). `Tools`가 이 mixin을 상속한다.

- 두뇌 도구 `propose_measures`는 줄마다 `validate`하고 확인 카드(`ui_measure_confirm`, 하네스 조각)만 낸다. 쓰지 않는다.
- `/actions save_measures`(카드의 "저장")는 다시 검사하고 한 트랜잭션에 줄들, 첫 기준선 스냅숏, X14를 쓴다.
  카드 누름이 확인이므로 활동 `risk = low`이고 되돌릴 수 있다.
- `/actions delete_measure`: `deleted_at`. 되돌리기는 `restore`.
- 값은 활동 `summary`·`undo_json`·로그에 넣지 않는다(6.5, 12장): 지표 이름·개수·id만.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from my_planner.clock import local, period_of
from my_planner.domain import RunContext, ToolEvent
from my_planner.standing.metrics import METRICS, validate
from my_planner.standing.score import AREAS, round_half_up
from my_planner.status.xp import AREA_LABELS, LABEL_STANDING, XP_STANDING
from my_planner.store.db import transaction
from my_planner.tools._base import _err, _tool
from my_planner.tools.activity import SUPERSEDED, measure_target, register_undo

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.standing import StandingRepo
    from my_planner.tools.core import Tools

log = logging.getLogger(__name__)

MEASURES_PER_SAVE_MAX = 30
SOURCE_KINDS = ("photo", "pdf", "manual")
_PHOTO_REF = re.compile(r"photo:[1-9][0-9]{0,17}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ROW_KEYS = frozenset({"metric", "value", "measured_on", "label", "unit"})  # 카드가 돌려보내는 `label`·`unit`은 읽지 않는다

MSG_NO_STANDING = "측정값을 다룰 수 없어요."
MSG_ROWS = f"rows는 1~{MEASURES_PER_SAVE_MAX}줄의 배열이에요."
MSG_SOURCE_KIND = "source_kind는 photo, pdf, manual 중 하나예요."
MSG_SOURCE_REF = "source_ref는 photo:<번호> 또는 null이에요."
MSG_ROW_SHAPE = "줄은 metric, value, measured_on 칸으로 보내 주세요."
MSG_DATE = "측정일은 YYYY-MM-DD 형식이에요."
MSG_NO_MEASURE = "없는 측정값이에요."
SAVED_SUMMARY = "측정값 {n}개 저장"
DELETED_SUMMARY = "측정값 지움"


def measures_saved_line(n: int, moved: tuple[str, int, int] | None) -> str:
    """`save_measures` 확인 문구. `moved`는 (영역 라벨, 이전 위치, 새 위치): 가장 많이 바뀐 영역 하나."""
    line = "✓ " + SAVED_SUMMARY.format(n=n)
    return f"{line} · {moved[0]} 위치 {moved[1]}→{moved[2]}" if moved is not None else line


def _measured_on(v: Any) -> date | None:
    if not isinstance(v, str) or not _ISO_DATE.fullmatch(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


Row = tuple[str, float | str, date]


class StandingTools:
    """`propose_measures`(두뇌), `save_measures`·`delete_measure`·`standing_daily`(`/actions`)."""

    standing: StandingRepo | None

    if TYPE_CHECKING:
        status: Any
        clock: Clock
        tz: Any

        def today(self) -> date: ...
        def _record(self, ctx: RunContext, kind: str, target: str | None, summary: str | None,
                    undo: dict[str, Any] | None, *, targets: list[str] | None = None) -> None: ...

    # --- 검사 ---

    def _calendar_today(self) -> date:
        """`validate`의 오늘: 논리적 날짜가 아니라 달력상 현지 날짜(그날 결과지가 거절되지 않게)."""
        return local(self.clock.now(), self.tz).date()

    def _check_source(self, source_kind: Any, source_ref: Any) -> str | None:
        if source_kind not in SOURCE_KINDS:
            return MSG_SOURCE_KIND
        if source_ref is not None and (not isinstance(source_ref, str) or not _PHOTO_REF.fullmatch(source_ref)):
            return MSG_SOURCE_REF
        return None

    def _check_rows(self, rows: Any) -> tuple[list[Row], list[dict[str, Any]]] | str:
        """(맞는 줄, 줄 오류 `{"index", "message"}`). 모양이 틀리면 오류 문구. 문구에는 값을 넣지 않는다."""
        if not isinstance(rows, list) or not 1 <= len(rows) <= MEASURES_PER_SAVE_MAX:
            return MSG_ROWS
        today = self._calendar_today()
        good: list[Row] = []
        errors: list[dict[str, Any]] = []
        for i, raw in enumerate(rows):
            if not isinstance(raw, dict) or set(raw) - _ROW_KEYS or not {"metric", "value", "measured_on"} <= set(raw):
                errors.append({"index": i, "message": MSG_ROW_SHAPE})
                continue
            on = _measured_on(raw["measured_on"])
            if on is None:
                errors.append({"index": i, "message": MSG_DATE})
                continue
            metric, value = raw["metric"], raw["value"]
            err = validate(metric, value, on, today) if isinstance(metric, str) else "모르는 측정값이에요."
            if err is not None:
                errors.append({"index": i, "message": err})
                continue
            good.append((metric, value, on))
        return good, errors

    # --- 두뇌 도구 ---

    @_tool
    def propose_measures(
        self, ctx: RunContext, rows: Any = None, source_kind: Any = None, source_ref: Any = None
    ) -> dict[str, Any]:
        """확인 카드(`ui_measure_confirm`)를 낸다. 하나라도 틀리면 카드 없이 줄 오류. 쓰지 않는다."""
        if self.standing is None:
            return _err(MSG_NO_STANDING)
        bad = self._check_source(source_kind, source_ref)
        if bad is not None:
            return _err(bad)
        checked = self._check_rows(rows)
        if isinstance(checked, str):
            return _err(checked)
        good, errors = checked
        if errors:
            return {"ok": False, "errors": errors}
        card = [
            {"metric": m, "label": METRICS[m].label, "value": v, "unit": METRICS[m].unit, "measured_on": on.isoformat()}
            for m, v, on in good
        ]
        ctx.events.append(ToolEvent(
            "measures_proposed", None, {"rows": card, "source_kind": source_kind, "source_ref": source_ref}
        ))
        log.info("measures_proposed", extra={"rows": len(card), "metrics": sorted({m for m, _, _ in good})})
        return {"ok": True, "card": True}

    # --- /actions ---

    def _areas_now(self) -> dict[str, float | None]:
        from my_planner.standing.service import current

        assert self.standing is not None
        return current(self.standing.conn, self.clock, self.today()).areas["national"]

    @staticmethod
    def _most_moved(before: dict[str, float | None], after: dict[str, float | None]) -> tuple[str, int, int] | None:
        best: tuple[str, int, int] | None = None
        for area in AREAS:
            b, a = before.get(area), after.get(area)
            if b is None or a is None:
                continue
            rb, ra = round_half_up(b), round_half_up(a)
            if rb != ra and (best is None or abs(ra - rb) > abs(best[2] - best[1])):
                best = (AREA_LABELS[area], rb, ra)
        return best

    @_tool
    def save_measures(
        self, ctx: RunContext, rows: Any = None, source_kind: Any = None, source_ref: Any = None
    ) -> dict[str, Any]:
        """카드의 "저장"(6.5). 줄들 + 첫 기준선 스냅숏 + X14를 한 트랜잭션에. 활동 `risk = low`, 되돌리기."""
        from my_planner.standing.service import snapshot_if_first

        if self.standing is None:
            return _err(MSG_NO_STANDING)
        bad = self._check_source(source_kind, source_ref)
        if bad is not None:
            return _err(bad)
        checked = self._check_rows(rows)
        if isinstance(checked, str):
            return _err(checked)
        good, errors = checked
        if errors:
            first = errors[0]
            return _err(f"{first['index'] + 1}번째 줄: {first['message']}")
        repo = self.standing
        now = self.clock.now()
        today = self.today()
        with transaction(repo.conn):
            before = self._areas_now()
            ids = [
                repo.add(m, v, on, source_kind, source_ref, "low" if m == "face_rating" else "mid", now)
                for m, v, on in good
            ]
            baseline = snapshot_if_first(repo.conn, self.clock, today)
            if self.status is not None:
                self.status.grant(
                    at=now, logical_date=today, source_kind="standing",
                    source_ref=f"standing:{period_of('quarter', today)}", amount=XP_STANDING, label=LABEL_STANDING,
                    gain=ctx.xp,
                )
            undo: dict[str, Any] = {"measure_ids": ids}
            if baseline is not None:
                undo["baseline_period"] = baseline
            self._record(
                ctx, "measures_saved", None, SAVED_SUMMARY.format(n=len(ids)), undo,
                targets=[measure_target(i) for i in ids],
            )
            line = measures_saved_line(len(ids), self._most_moved(before, self._areas_now()))
        ctx.events.append(ToolEvent("measures_saved", None, {"line": line}))
        log.info("measures_saved", extra={"rows": len(ids), "metrics": sorted({m for m, _, _ in good})})
        return {"ids": ids, "baseline_period": baseline}

    @_tool
    def delete_measure(self, ctx: RunContext, id: Any = None) -> dict[str, Any]:
        """지우기는 표시만(`deleted_at`). 되돌리기 24시간. 경험치는 그대로."""
        if self.standing is None:
            return _err(MSG_NO_STANDING)
        if not isinstance(id, int) or isinstance(id, bool):
            return _err(MSG_NO_MEASURE)
        repo = self.standing
        with transaction(repo.conn):
            if not repo.delete(id, self.clock.now()):
                return _err(MSG_NO_MEASURE)
            self._record(ctx, "measure_deleted", measure_target(id), DELETED_SUMMARY, {"measure_id": id})
        log.info("measure_deleted", extra={"measure_id": id})
        return {"id": id, "deleted": True}

    def standing_daily(self, ctx: RunContext) -> dict[str, Any]:
        """하루 한 번 작업(내부 동작): 지난 분기 스냅숏을 분기 끝 값으로 채운다. 활동은 없다."""
        from my_planner.standing.service import catch_up_snapshots

        if self.standing is None:
            return {"snapshot_rows": 0}
        with transaction(self.standing.conn):
            n = catch_up_snapshots(self.standing.conn, self.clock, self.today())
        return {"snapshot_rows": n}


# --- 되돌리기 (6.5). 경험치는 그대로(U6) ---


def _undo_measures_saved(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    """그 줄들에 `deleted_at`. 그 저장이 첫 기준선을 썼으면 그 분기 스냅숏도 지운다(다음 저장이 다시 쓴다)."""
    assert tools.standing is not None
    now = tools.clock.now()
    gone = [i for i in undo["measure_ids"] if not tools.standing.delete(i, now)]
    if len(gone) == len(undo["measure_ids"]):
        return SUPERSEDED
    if undo.get("baseline_period"):
        tools.standing.delete_snapshots(undo["baseline_period"])
    return None


def _undo_measure_deleted(tools: Tools, undo: dict[str, Any], ctx: RunContext) -> str | None:
    assert tools.standing is not None
    return None if tools.standing.restore(undo["measure_id"]) else SUPERSEDED


for _kind, _handler in (
    ("measures_saved", _undo_measures_saved),
    ("measure_deleted", _undo_measure_deleted),
):
    register_undo(_kind, _handler)

"""owner_statements, panel_suggestions, panel_predictions, life_reports 표 (SP15 스펙 5.4, 7.1, 9.1, 10).

내가 한 말(`owner_statements`)은 지우지 않고 `retired_at`만 채운다. 쓰기는 모두 부르는 쪽 `transaction` 안에서 한다.
이 모듈은 로그를 남기지 않는다(제목·근거 글·말·리포트·측정값이 들어 있다).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from my_planner.clock import Clock, from_iso, to_iso

_KEEP: Any = object()  # `set_state`에서 칸을 그대로 둔다


@dataclass(frozen=True)
class Statement:
    id: int
    kind: str
    area: str | None
    key: str | None
    text: str
    source_ref: str | None
    created_at: datetime
    retired_at: datetime | None


@dataclass(frozen=True)
class Suggestion:
    id: int
    conversation_id: int | None
    kind: str
    title: str
    area: str
    size_min: int
    per_week: int | None
    due_hint: date | None
    experts: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]
    week: str
    state: str
    result_ref: str | None
    dismiss_reason: str | None
    created_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True)
class Prediction:
    id: int
    metric: str
    predicted: float
    due: date
    made_at: datetime
    actual: float | None
    checked_at: datetime | None
    conversation_id: int | None


_ST_COLS = "id, kind, area, key, text, source_ref, created_at, retired_at"
_SG_COLS = (
    "id, conversation_id, kind, title, area, size_min, per_week, due_hint, experts, evidence_json, week, state, "
    "result_ref, dismiss_reason, created_at, decided_at"
)
_PR_COLS = "id, metric, predicted, due, made_at, actual, checked_at, conversation_id"


def _dt(s: str | None) -> datetime | None:
    return from_iso(s) if s is not None else None


def _statement(r: sqlite3.Row) -> Statement:
    return Statement(
        id=r["id"], kind=r["kind"], area=r["area"], key=r["key"], text=r["text"], source_ref=r["source_ref"],
        created_at=from_iso(r["created_at"]), retired_at=_dt(r["retired_at"]),
    )


def _suggestion(r: sqlite3.Row) -> Suggestion:
    return Suggestion(
        id=r["id"], conversation_id=r["conversation_id"], kind=r["kind"], title=r["title"], area=r["area"],
        size_min=r["size_min"], per_week=r["per_week"],
        due_hint=date.fromisoformat(r["due_hint"]) if r["due_hint"] is not None else None,
        experts=tuple(x for x in r["experts"].split(",") if x), evidence=tuple(json.loads(r["evidence_json"])),
        week=r["week"], state=r["state"], result_ref=r["result_ref"], dismiss_reason=r["dismiss_reason"],
        created_at=from_iso(r["created_at"]), decided_at=_dt(r["decided_at"]),
    )


def _prediction(r: sqlite3.Row) -> Prediction:
    return Prediction(
        id=r["id"], metric=r["metric"], predicted=r["predicted"], due=date.fromisoformat(r["due"]),
        made_at=from_iso(r["made_at"]), actual=r["actual"], checked_at=_dt(r["checked_at"]),
        conversation_id=r["conversation_id"],
    )


def _qs(n: int) -> str:
    return ",".join("?" * n)


class PanelRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self.clock = clock

    # --- 내가 한 말 (5.4) ---

    def add_statement(
        self, kind: str, area: str | None, text: str, *, key: str | None = None, source_ref: str | None = None,
        now: datetime,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO owner_statements (kind, area, key, text, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, area, key, text, source_ref, to_iso(now)),
        )
        return int(cur.lastrowid or 0)

    def statement(self, statement_id: int) -> Statement | None:
        r = self.conn.execute(f"SELECT {_ST_COLS} FROM owner_statements WHERE id = ?", (statement_id,)).fetchone()
        return _statement(r) if r is not None else None

    def active_statements(self, kinds: Iterable[str] | None = None) -> list[Statement]:
        """지우지 않은 말, 오래된 것부터(`created_at`, `id`). `kinds`를 주면 그 종류만."""
        sql = f"SELECT {_ST_COLS} FROM owner_statements WHERE retired_at IS NULL"
        args: list[str] = []
        if kinds is not None:
            args = list(kinds)
            sql += f" AND kind IN ({_qs(len(args))})"
        sql += " ORDER BY created_at, id"
        return [_statement(r) for r in self.conn.execute(sql, args)]

    def decision(self, key: str) -> Statement | None:
        """키가 `key`인 활성 결정(지운 결정은 `None`)."""
        r = self.conn.execute(
            f"SELECT {_ST_COLS} FROM owner_statements WHERE kind = 'decision' AND key = ? AND retired_at IS NULL",
            (key,),
        ).fetchone()
        return _statement(r) if r is not None else None

    def find_active(self, kind: str, area: str | None, text: str) -> Statement | None:
        """같은 종류·영역·글의 활성 말(같은 말을 두 번 저장하지 않게)."""
        r = self.conn.execute(
            f"SELECT {_ST_COLS} FROM owner_statements WHERE kind = ? AND area IS ? AND text = ? "
            "AND retired_at IS NULL ORDER BY id LIMIT 1",
            (kind, area, text),
        ).fetchone()
        return _statement(r) if r is not None else None

    def retire(self, statement_id: int, now: datetime) -> bool:
        """지운다(`retired_at`). 없거나 이미 지운 말이면 `False`."""
        cur = self.conn.execute(
            "UPDATE owner_statements SET retired_at = ? WHERE id = ? AND retired_at IS NULL",
            (to_iso(now), statement_id),
        )
        return cur.rowcount > 0

    def unretire(self, statement_id: int) -> bool:
        """지운 말을 되살린다. 없거나 지우지 않은 말이면 `False`."""
        cur = self.conn.execute(
            "UPDATE owner_statements SET retired_at = NULL WHERE id = ? AND retired_at IS NOT NULL", (statement_id,)
        )
        return cur.rowcount > 0

    # --- 패널 제안 (7.1) ---

    def add_suggestion(
        self, *, conversation_id: int | None, kind: str, title: str, area: str, size_min: int, per_week: int | None,
        due_hint: date | None, experts: Iterable[str], evidence: Iterable[dict[str, str]], week: str, now: datetime,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO panel_suggestions (conversation_id, kind, title, area, size_min, per_week, due_hint, experts, "
            "evidence_json, week, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?)",
            (
                conversation_id, kind, title, area, size_min, per_week,
                due_hint.isoformat() if due_hint is not None else None, ",".join(experts),
                json.dumps(list(evidence), ensure_ascii=False), week, to_iso(now),
            ),
        )
        return int(cur.lastrowid or 0)

    def suggestion(self, suggestion_id: int) -> Suggestion | None:
        r = self.conn.execute(f"SELECT {_SG_COLS} FROM panel_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return _suggestion(r) if r is not None else None

    def suggestions(self, *, state: str | None = None, since: datetime | None = None) -> list[Suggestion]:
        """최신 먼저. `since`는 만든 시각이 그 시각 이후인 것(논리적 날짜 창은 부르는 쪽이 그 날 04:00 현지로 넘긴다)."""
        sql = f"SELECT {_SG_COLS} FROM panel_suggestions WHERE 1 = 1"
        args: list[str] = []
        if state is not None:
            sql += " AND state = ?"
            args.append(state)
        if since is not None:
            sql += " AND created_at >= ?"
            args.append(to_iso(since))
        sql += " ORDER BY created_at DESC, id DESC"
        return [_suggestion(r) for r in self.conn.execute(sql, args)]

    def count_in_week(self, week: str) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM panel_suggestions WHERE week = ?", (week,)).fetchone()[0])

    def first_week(self) -> str | None:
        """처음 제안이 나온 주(`YYYY-Www`는 문자열 순서가 시간 순서다). 없으면 `None`."""
        return self.conn.execute("SELECT MIN(week) FROM panel_suggestions").fetchone()[0]

    def in_weeks(self, weeks: Iterable[str]) -> list[Suggestion]:
        ws = list(weeks)
        if not ws:
            return []
        return [
            _suggestion(r) for r in self.conn.execute(
                f"SELECT {_SG_COLS} FROM panel_suggestions WHERE week IN ({_qs(len(ws))}) ORDER BY created_at, id", ws
            )
        ]

    def latest_in_area(self, area: str, *, exclude_id: int | None = None) -> Suggestion | None:
        r = self.conn.execute(
            f"SELECT {_SG_COLS} FROM panel_suggestions WHERE area = ? AND id IS NOT ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (area, exclude_id),
        ).fetchone()
        return _suggestion(r) if r is not None else None

    def dismissed(self, area: str, reason: str, since: datetime) -> list[Suggestion]:
        """그 영역에서 그 이유로 버린 제안 가운데 `since` 이후에 정한 것(최신 먼저)."""
        return [
            _suggestion(r) for r in self.conn.execute(
                f"SELECT {_SG_COLS} FROM panel_suggestions WHERE area = ? AND state = 'dismissed' "
                "AND dismiss_reason = ? AND decided_at >= ? ORDER BY decided_at DESC, id DESC",
                (area, reason, to_iso(since)),
            )
        ]

    def set_state(
        self, suggestion_id: int, state: str, *, now: datetime, result_ref: str | None = _KEEP,
        dismiss_reason: str | None = _KEEP, decided: bool = True, only_from: str | None = None,
    ) -> bool:
        """상태를 바꾼다. 주지 않은 `result_ref`·`dismiss_reason`은 그대로 둔다. `decided`면 `decided_at = now`.

        `only_from`을 주면 지금 상태가 그것일 때만 바꾼다(받기·버리기를 두 번 눌러도 한 번만, 바꿨으면 `True`).
        """
        sets = ["state = ?"]
        args: list[Any] = [state]
        if result_ref is not _KEEP:
            sets.append("result_ref = ?")
            args.append(result_ref)
        if dismiss_reason is not _KEEP:
            sets.append("dismiss_reason = ?")
            args.append(dismiss_reason)
        if decided:
            sets.append("decided_at = ?")
            args.append(to_iso(now))
        where = "id = ?"
        args.append(suggestion_id)
        if only_from is not None:
            where += " AND state = ?"
            args.append(only_from)
        cur = self.conn.execute(f"UPDATE panel_suggestions SET {', '.join(sets)} WHERE {where}", args)
        return cur.rowcount > 0

    def reopen(self, suggestion_id: int, *, only_from: str) -> bool:
        """받기·버리기 되돌리기: `proposed`로, `result_ref`·`dismiss_reason`·`decided_at`은 NULL로."""
        cur = self.conn.execute(
            "UPDATE panel_suggestions SET state = 'proposed', result_ref = NULL, dismiss_reason = NULL, "
            "decided_at = NULL WHERE id = ? AND state = ?",
            (suggestion_id, only_from),
        )
        return cur.rowcount > 0

    def count_dismissed(self, area: str, reason: str) -> int:
        """그 영역에서 그 이유로 버린 제안 수(기간 없이, 7.4 "같은 이유가 2회")."""
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM panel_suggestions WHERE area = ? AND state = 'dismissed' AND dismiss_reason = ?",
            (area, reason),
        ).fetchone()[0])

    # --- 예측 (9.1) ---

    def add_prediction(
        self, metric: str, predicted: float, due: date, *, conversation_id: int | None, now: datetime
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO panel_predictions (metric, predicted, due, made_at, conversation_id) VALUES (?, ?, ?, ?, ?)",
            (metric, predicted, due.isoformat(), to_iso(now), conversation_id),
        )
        return int(cur.lastrowid or 0)

    def count_for_conversation(self, conversation_id: int) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM panel_predictions WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0])

    def due_unchecked(self, today: date) -> list[Prediction]:
        """기한이 `today`보다 앞이고 아직 맞춰 보지 않은 예측(기한 순)."""
        return [
            _prediction(r) for r in self.conn.execute(
                f"SELECT {_PR_COLS} FROM panel_predictions WHERE due < ? AND checked_at IS NULL ORDER BY due, id",
                (today.isoformat(),),
            )
        ]

    def set_actual(self, prediction_id: int, actual: float | None, now: datetime) -> None:
        self.conn.execute(
            "UPDATE panel_predictions SET actual = ?, checked_at = ? WHERE id = ?",
            (actual, to_iso(now), prediction_id),
        )

    def recent_predictions(self, limit: int = 5) -> list[Prediction]:
        return [
            _prediction(r) for r in self.conn.execute(
                f"SELECT {_PR_COLS} FROM panel_predictions ORDER BY made_at DESC, id DESC LIMIT ?", (limit,)
            )
        ]

    # --- 인생 리포트 (10장) ---

    def add_report(self, json_text: str, now: datetime) -> int:
        cur = self.conn.execute("INSERT INTO life_reports (created_at, json) VALUES (?, ?)", (to_iso(now), json_text))
        return int(cur.lastrowid or 0)

    def reports(self) -> list[tuple[int, datetime]]:
        """(id, 만든 시각), 최신 먼저."""
        return [
            (r["id"], from_iso(r["created_at"]))
            for r in self.conn.execute("SELECT id, created_at FROM life_reports ORDER BY created_at DESC, id DESC")
        ]

    def report(self, report_id: int) -> tuple[int, datetime, str] | None:
        r = self.conn.execute("SELECT id, created_at, json FROM life_reports WHERE id = ?", (report_id,)).fetchone()
        return (r["id"], from_iso(r["created_at"]), r["json"]) if r is not None else None

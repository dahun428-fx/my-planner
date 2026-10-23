"""tasks, task_areas, task_events, priorities, tool_events_log 표 (스펙 5.5)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo

from my_planner.clock import Clock, from_iso, local, to_iso
from my_planner.domain import Area, Cadence, TaskStatus


@dataclass
class Task:
    id: int
    title: str
    status: TaskStatus
    planned_for: date | None
    scheduled_at: datetime | None
    parent_id: int | None
    note: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    deleted_at: datetime | None
    areas: list[Area] = field(default_factory=list)


_UPDATABLE = {"title", "note", "planned_for", "scheduled_at", "areas"}


class TasksRepo:
    """`tz`와 `boundary`는 완료 시각을 논리적 날짜로 바꿀 때만 쓴다."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        *,
        tz: str | tzinfo = "Asia/Seoul",
        boundary: time = time(4, 0),
    ) -> None:
        self.conn = conn
        self.clock = clock
        self.tz = tz
        self.boundary = boundary
        self._depth = 0

    # --- 트랜잭션 ---

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """바깥 트랜잭션이 있으면 거기에 합류한다. 가장 바깥에서만 커밋·롤백한다."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        finally:
            self._depth = 0

    # --- 읽기 ---

    def _areas(self, task_id: int) -> list[Area]:
        rows = self.conn.execute(
            "SELECT area FROM task_areas WHERE task_id = ? ORDER BY area", (task_id,)
        ).fetchall()
        return [Area(r["area"]) for r in rows]

    def _task(self, r: sqlite3.Row) -> Task:
        return Task(
            id=r["id"],
            title=r["title"],
            status=TaskStatus(r["status"]),
            planned_for=date.fromisoformat(r["planned_for"]) if r["planned_for"] else None,
            scheduled_at=from_iso(r["scheduled_at"]) if r["scheduled_at"] else None,
            parent_id=r["parent_id"],
            note=r["note"],
            created_at=from_iso(r["created_at"]),
            updated_at=from_iso(r["updated_at"]),
            completed_at=from_iso(r["completed_at"]) if r["completed_at"] else None,
            deleted_at=from_iso(r["deleted_at"]) if r["deleted_at"] else None,
            areas=self._areas(r["id"]),
        )

    def get(self, id: int) -> Task | None:
        """소프트 삭제한 할 일은 없는 것으로 본다."""
        r = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND deleted_at IS NULL", (id,)
        ).fetchone()
        return self._task(r) if r is not None else None

    def list(
        self,
        status: TaskStatus | str | list[TaskStatus | str] | tuple[TaskStatus | str, ...] | None = None,
        from_: date | None = None,
        to: date | None = None,
        area: Area | str | None = None,
        limit: int | None = None,
    ) -> list[Task]:
        """소프트 삭제한 것은 뺀다. `from_`·`to`(포함)는 하려는 날에, `done`은 완료한 논리적 날짜에 건다."""
        where = ["t.deleted_at IS NULL"]
        args: list[object] = []
        if status is not None:
            statuses = [status] if isinstance(status, (str, TaskStatus)) else list(status)
            where.append(f"t.status IN ({','.join('?' * len(statuses))})")
            args += [TaskStatus(s).value for s in statuses]
        done_only = isinstance(status, (str, TaskStatus)) and TaskStatus(status) == TaskStatus.done
        if done_only:
            if from_ is not None:
                where.append("t.completed_at >= ?")
                args.append(to_iso(self._day_start(from_)))
            if to is not None:
                where.append("t.completed_at < ?")
                args.append(to_iso(self._day_start(to + timedelta(days=1))))
        else:
            if from_ is not None:
                where.append("t.planned_for >= ?")
                args.append(from_.isoformat())
            if to is not None:
                where.append("t.planned_for <= ?")
                args.append(to.isoformat())
        if area is not None:
            where.append("EXISTS (SELECT 1 FROM task_areas a WHERE a.task_id = t.id AND a.area = ?)")
            args.append(Area(area).value)
        sql = (
            "SELECT t.* FROM tasks t WHERE " + " AND ".join(where) + " ORDER BY "
            + ("t.completed_at DESC, t.id" if done_only else
               "t.planned_for IS NULL, t.planned_for, t.scheduled_at IS NULL, t.scheduled_at, t.id")
        )
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [self._task(r) for r in self.conn.execute(sql, args).fetchall()]

    def dropped_from(self, id: int) -> TaskStatus | None:
        """가장 최근에 내려놓기 직전의 상태. 내려놓은 적이 없으면 None."""
        r = self.conn.execute(
            "SELECT payload_json FROM task_events WHERE task_id = ? AND kind = 'dropped' "
            "ORDER BY at DESC, id DESC LIMIT 1",
            (id,),
        ).fetchone()
        if r is None:
            return None
        before = json.loads(r["payload_json"]).get("from")
        return TaskStatus(before) if before else None

    def _day_start(self, d: date) -> datetime:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(self.tz) if isinstance(self.tz, str) else self.tz
        return datetime.combine(d, self.boundary, tzinfo=tz)

    # --- 쓰기 ---

    def _event(self, task_id: int, kind: str, payload: dict[str, object] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO task_events (task_id, kind, payload_json, at) VALUES (?, ?, ?, ?)",
            (task_id, kind, json.dumps(payload or {}, ensure_ascii=False), to_iso(self.clock.now())),
        )

    def create(
        self,
        title: str,
        areas: list[Area | str],
        status: TaskStatus | str = TaskStatus.open,
        planned_for: date | None = None,
        scheduled_at: datetime | None = None,
        parent_id: int | None = None,
        note: str = "",
    ) -> Task:
        now = to_iso(self.clock.now())
        status = TaskStatus(status)
        with self.transaction():
            cur = self.conn.execute(
                "INSERT INTO tasks (title, status, planned_for, scheduled_at, parent_id, note, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    status.value,
                    planned_for.isoformat() if planned_for else None,
                    to_iso(scheduled_at) if scheduled_at else None,
                    parent_id,
                    note,
                    now,
                    now,
                ),
            )
            task_id = cur.lastrowid
            assert task_id is not None
            self._set_areas(task_id, areas)
            self._event(task_id, "proposed" if status == TaskStatus.draft else "created")
        task = self.get(task_id)
        assert task is not None
        return task

    def _set_areas(self, task_id: int, areas: list[Area | str]) -> None:
        self.conn.execute("DELETE FROM task_areas WHERE task_id = ?", (task_id,))
        for a in dict.fromkeys(Area(x).value for x in areas):
            self.conn.execute("INSERT INTO task_areas (task_id, area) VALUES (?, ?)", (task_id, a))

    def update(self, id: int, *, event_kind: str | None = None, **fields: object) -> Task:
        """title, note, planned_for, scheduled_at, areas만 바꾼다. 하려는 날만 바꾸면 `moved`, 아니면 `updated`."""
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"바꿀 수 없는 필드: {sorted(unknown)}")
        sets: list[str] = ["updated_at = ?"]
        args: list[object] = [to_iso(self.clock.now())]
        for name in ("title", "note"):
            if name in fields:
                sets.append(f"{name} = ?")
                args.append(fields[name])
        if "planned_for" in fields:
            pf = fields["planned_for"]
            sets.append("planned_for = ?")
            args.append(pf.isoformat() if isinstance(pf, date) else None)
        if "scheduled_at" in fields:
            sa = fields["scheduled_at"]
            sets.append("scheduled_at = ?")
            args.append(to_iso(sa) if isinstance(sa, datetime) else None)
        kind = event_kind or ("moved" if set(fields) == {"planned_for"} else "updated")
        with self.transaction():
            cur = self.conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL", (*args, id)
            )
            if cur.rowcount == 0:
                raise KeyError(id)
            if "areas" in fields:
                self._set_areas(id, fields["areas"])  # type: ignore[arg-type]
            self._event(id, kind, {k: _jsonable(v) for k, v in fields.items()})
        task = self.get(id)
        assert task is not None
        return task

    def set_status(self, id: int, status: TaskStatus | str) -> Task:
        new = TaskStatus(status)
        old = self.get(id)
        if old is None:
            raise KeyError(id)
        now = self.clock.now()
        if new == TaskStatus.done:
            kind = "completed"
        elif new == TaskStatus.dropped:
            kind = "dropped"
        elif old.status == TaskStatus.draft:
            kind = "confirmed"
        elif new == TaskStatus.open:
            kind = "reopened"
        else:
            kind = "updated"
        with self.transaction():
            self.conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                (new.value, to_iso(now) if new == TaskStatus.done else None, to_iso(now), id),
            )
            if new == TaskStatus.dropped:
                self.conn.execute("DELETE FROM priorities WHERE task_id = ?", (id,))
            self._event(id, kind, {"from": old.status.value, "to": new.value})
        task = self.get(id)
        assert task is not None
        return task

    def expire_drafts(self, older_than: datetime) -> list[int]:
        """`older_than`이나 그보다 먼저 만든 초안을 조용히 `dropped`로 바꾼다(딱 3일이 된 것도 포함)."""
        rows = self.conn.execute(
            "SELECT id FROM tasks WHERE status = 'draft' AND deleted_at IS NULL AND created_at <= ? "
            "ORDER BY id",
            (to_iso(older_than),),
        ).fetchall()
        ids = [r["id"] for r in rows]
        with self.transaction():
            for i in ids:
                self.set_status(i, TaskStatus.dropped)
        return ids

    # --- 우선순위 ---

    def set_priorities(self, cadence: Cadence | str, period: str, ids: list[int]) -> None:
        """그 기간의 우선순위를 통째로 바꾼다. 순서가 순위다(1부터)."""
        c = Cadence(cadence).value
        with self.transaction():
            self.conn.execute("DELETE FROM priorities WHERE cadence = ? AND period = ?", (c, period))
            for rank, task_id in enumerate(ids, start=1):
                self.conn.execute(
                    "INSERT INTO priorities (cadence, period, rank, task_id) VALUES (?, ?, ?, ?)",
                    (c, period, rank, task_id),
                )

    def priorities(self, cadence: Cadence | str, period: str) -> list[Task]:
        rows = self.conn.execute(
            "SELECT task_id FROM priorities WHERE cadence = ? AND period = ? ORDER BY rank",
            (Cadence(cadence).value, period),
        ).fetchall()
        tasks = [self.get(r["task_id"]) for r in rows]
        return [t for t in tasks if t is not None]

    # --- 도구 호출 기록 ---

    def log_tool_event(
        self, run_id: int | None, conversation_id: int | None, task_id: int | None, kind: str
    ) -> None:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO tool_events_log (run_id, conversation_id, task_id, kind, at) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, conversation_id, task_id, kind, to_iso(self.clock.now())),
            )

    def proposed_task_ids(self, conversation_id: int) -> list[int]:
        """그 대화에서 `propose_tasks`로 제안한 할 일 번호(제안한 순서). 상태는 거르지 않는다."""
        rows = self.conn.execute(
            "SELECT task_id FROM tool_events_log "
            "WHERE conversation_id = ? AND kind = 'tasks_proposed' AND task_id IS NOT NULL "
            "GROUP BY task_id ORDER BY MIN(id)",
            (conversation_id,),
        ).fetchall()
        return [r["task_id"] for r in rows]

    def proposed_conversation_id(self, task_id: int) -> int | None:
        """그 할 일을 `propose_tasks`로 제안한 대화. 없으면 None."""
        r = self.conn.execute(
            "SELECT conversation_id FROM tool_events_log "
            "WHERE task_id = ? AND kind = 'tasks_proposed' ORDER BY id LIMIT 1",
            (task_id,),
        ).fetchone()
        return r["conversation_id"] if r is not None else None

    def local(self, dt: datetime) -> datetime:
        return local(dt, self.tz)


def _jsonable(v: object) -> object:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return [str(x) for x in v]
    return v

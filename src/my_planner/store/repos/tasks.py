"""tasks, task_areas, task_events, priorities, tool_events_log 표 (스펙 5.5)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo

from my_planner.clock import Clock, from_iso, local, period_of, to_iso
from my_planner.domain import Area, Cadence, TaskStatus
from my_planner.store.db import transaction


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

    # --- 트랜잭션 ---

    def transaction(self) -> AbstractContextManager[None]:
        """연결 단위 트랜잭션(`store.db.transaction`)에 위임한다. 바깥이 있으면 합류하고 가장 바깥에서만 커밋한다."""
        return transaction(self.conn)

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

    def restore(
        self, id: int, *, status: TaskStatus | str, completed_at: datetime | None, deleted_at: datetime | None
    ) -> None:
        """되돌리기(SP3-4 스펙 6.4.3): 상태, `completed_at`, `deleted_at`을 넘긴 값 그대로 둔다(시각을 새로 찍지 않는다).

        `task_added` 되돌리기는 `deleted_at`에 지금을, `task_reopened` 되돌리기는 이전 `done`과 `completed_at`을 넘긴다.
        이벤트: 소프트 삭제는 `updated`, `draft`로 돌리면 `proposed`(초안 만료 시계가 다시 센다), `done`은 `completed`,
        `dropped`는 `dropped`(우선순위 칸도 지운다, `set_status`와 같다), `open`은 `reopened`.
        """
        new = TaskStatus(status)
        row = self.conn.execute("SELECT status FROM tasks WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        if deleted_at is not None:
            kind = "updated"
        else:
            kind = {
                TaskStatus.draft: "proposed", TaskStatus.done: "completed", TaskStatus.dropped: "dropped",
                TaskStatus.open: "reopened",
            }[new]
        with self.transaction():
            self.conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ?, deleted_at = ?, updated_at = ? WHERE id = ?",
                (
                    new.value, to_iso(completed_at) if completed_at else None,
                    to_iso(deleted_at) if deleted_at else None, to_iso(self.clock.now()), id,
                ),
            )
            if new == TaskStatus.dropped:
                self.conn.execute("DELETE FROM priorities WHERE task_id = ?", (id,))
            payload: dict[str, object] = {"from": row["status"], "to": new.value, "undo": True}
            if deleted_at is not None:
                payload["deleted"] = True
            self._event(id, kind, payload)

    def restore_priority(self, cadence: Cadence | str, period: str, rank: int, task_id: int) -> bool:
        """지워졌던 우선순위 칸 하나를 되살린다. 그 칸이 비어 있고 그 할 일이 그 목록에 없을 때만. 되살렸으면 True."""
        c = Cadence(cadence).value
        taken = self.conn.execute(
            "SELECT 1 FROM priorities WHERE cadence = ? AND period = ? AND (rank = ? OR task_id = ?)",
            (c, period, rank, task_id),
        ).fetchone()
        if taken is not None:
            return False
        with self.transaction():
            self.conn.execute(
                "INSERT INTO priorities (cadence, period, rank, task_id) VALUES (?, ?, ?, ?)", (c, period, rank, task_id)
            )
        return True

    def expire_drafts(self, older_than: datetime) -> list[int]:
        """`proposed_at`이 `older_than`이거나 그보다 먼저인 초안을 조용히 `dropped`로 바꾼다(딱 3일이 된 것도 포함).

        `proposed_at`은 가장 최근 `proposed` 이벤트 시각, 없으면 `created_at`이다(`proposed_at()`, 스펙 6.3.8).
        `/drafts`의 `draft_live`(`store/views.py`)와 같은 기준이라 화면에 보이는 초안과 밤 정리가 어긋나지 않는다.
        """
        rows = self.conn.execute(
            "SELECT t.id FROM tasks t WHERE t.status = 'draft' AND t.deleted_at IS NULL AND COALESCE("
            "(SELECT MAX(e.at) FROM task_events e WHERE e.task_id = t.id AND e.kind = 'proposed'), t.created_at"
            ") <= ? ORDER BY t.id",
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

    def priority_rows(self, task_id: int) -> list[tuple[str, str, int]]:
        """그 할 일이 오른 우선순위 칸 (주기, 기간, 순위). 내려놓기 전 값으로 활동에 남긴다."""
        rows = self.conn.execute(
            "SELECT cadence, period, rank FROM priorities WHERE task_id = ? ORDER BY cadence, period",
            (task_id,),
        ).fetchall()
        return [(r["cadence"], r["period"], r["rank"]) for r in rows]

    def priorities(self, cadence: Cadence | str, period: str) -> list[Task]:
        rows = self.conn.execute(
            "SELECT task_id FROM priorities WHERE cadence = ? AND period = ? ORDER BY rank",
            (Cadence(cadence).value, period),
        ).fetchall()
        tasks = [self.get(r["task_id"]) for r in rows]
        return [t for t in tasks if t is not None]

    def priority_ranks(self, cadence: Cadence | str, period: str) -> list[tuple[int, Task]]:
        """`priorities()`와 같되 `priorities.rank`를 함께 준다."""
        rows = self.conn.execute(
            "SELECT rank, task_id FROM priorities WHERE cadence = ? AND period = ? ORDER BY rank",
            (Cadence(cadence).value, period),
        ).fetchall()
        got = [(r["rank"], self.get(r["task_id"])) for r in rows]
        return [(rank, t) for rank, t in got if t is not None]

    def current_priority(self, task_id: int, today: date) -> tuple[Cadence, str, int] | None:
        """그 할 일이 지금 기간(오늘, 이번 주, 이번 달, 분기, 올해)의 우선순위이면 가장 큰 주기의 (주기, 기간, 순위)."""
        periods = [(c, period_of(c, today)) for c in Cadence]
        where = " OR ".join("(cadence = ? AND period = ?)" for _ in periods)
        rows = self.conn.execute(
            f"SELECT cadence, period, rank FROM priorities WHERE task_id = ? AND ({where})",
            (task_id, *(x for cp in periods for x in (cp[0].value, cp[1]))),
        ).fetchall()
        if not rows:
            return None
        order = list(Cadence)
        best = max(rows, key=lambda r: order.index(Cadence(r["cadence"])))
        return Cadence(best["cadence"]), best["period"], best["rank"]

    def first_steps(self, task_id: int) -> tuple[int, int]:
        """그 할 일의 첫 걸음(`parent_id`가 그 할 일인 것) 수: (열림, 완료). 소프트 삭제한 것은 뺀다."""
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE parent_id = ? AND deleted_at IS NULL "
            "AND status IN ('open', 'done') GROUP BY status",
            (task_id,),
        ).fetchall()
        counts = {r["status"]: r["n"] for r in rows}
        return counts.get("open", 0), counts.get("done", 0)

    def next_undated_step(self, task_id: int) -> int | None:
        """날짜 없는 다음 첫 걸음(`open`, `planned_for` 없음)의 id. 없으면 None."""
        r = self.conn.execute(
            "SELECT id FROM tasks WHERE parent_id = ? AND deleted_at IS NULL AND status = 'open' "
            "AND planned_for IS NULL ORDER BY id LIMIT 1",
            (task_id,),
        ).fetchone()
        return r["id"] if r else None

    # --- 도구 호출 기록 ---

    def log_tool_event(
        self,
        run_id: int | None,
        conversation_id: int | None,
        task_id: int | None,
        kind: str,
        *,
        inbound_id: int | None = None,
        data: dict[str, object] | None = None,
    ) -> None:
        """`data`는 확인 문구와 초안 버튼을 다시 만들 ToolEvent 데이터다(DB에만 둔다, 로그 파일에는 없다)."""
        with self.transaction():
            self.conn.execute(
                "INSERT INTO tool_events_log (run_id, conversation_id, task_id, kind, at, inbound_id, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, conversation_id, task_id, kind, to_iso(self.clock.now()), inbound_id,
                    json.dumps(data, ensure_ascii=False) if data is not None else None,
                ),
            )

    def inbound_tool_events(self, inbound_id: int) -> list[tuple[str, int | None, dict[str, object], int | None]]:
        """그 사용자 메시지를 처리하는 동안 남은 도구 호출: (종류, 할 일 번호, 데이터, 대화 ID), 기록한 순서."""
        rows = self.conn.execute(
            "SELECT kind, task_id, data_json, conversation_id FROM tool_events_log WHERE inbound_id = ? ORDER BY id",
            (inbound_id,),
        ).fetchall()
        return [
            (r["kind"], r["task_id"], json.loads(r["data_json"]) if r["data_json"] else {}, r["conversation_id"])
            for r in rows
        ]

    def proposed_task_ids(self, conversation_id: int) -> list[int]:
        """그 대화에서 `propose_tasks`로 제안한 할 일 번호(제안한 순서). 상태는 거르지 않는다."""
        rows = self.conn.execute(
            "SELECT task_id FROM tool_events_log "
            "WHERE conversation_id = ? AND kind = 'tasks_proposed' AND task_id IS NOT NULL "
            "GROUP BY task_id ORDER BY MIN(id)",
            (conversation_id,),
        ).fetchall()
        return [r["task_id"] for r in rows]

    def proposed_task_ids_for_runs(self, run_ids: list[int]) -> list[int]:
        """그 회차들(합친 회차 포함)이 `propose_tasks`로 제안한 할 일 번호(제안한 순서). 상태는 거르지 않는다."""
        if not run_ids:
            return []
        marks = ",".join("?" * len(run_ids))
        rows = self.conn.execute(
            "SELECT task_id FROM tool_events_log "
            f"WHERE run_id IN ({marks}) AND kind = 'tasks_proposed' AND task_id IS NOT NULL "
            "GROUP BY task_id ORDER BY MIN(id)",
            run_ids,
        ).fetchall()
        return [r["task_id"] for r in rows]

    def proposed_curve_ids(
        self, kind: str, *, run_ids: list[int] | None = None, conversation_id: int | None = None
    ) -> list[int]:
        """그 회차들(또는 그 대화)이 `add_milestone`(`milestone_proposed`)·`propose_chapter`(`chapter_proposed`)로 꺼낸
        초안 번호(꺼낸 순서). 곡선 이벤트는 `task_id`가 없어 `data_json.id`로 찾는다. 상태는 거르지 않는다."""
        if run_ids is not None:
            if not run_ids:
                return []
            where, params = f"run_id IN ({','.join('?' * len(run_ids))})", list(run_ids)
        elif conversation_id is not None:
            where, params = "conversation_id = ?", [conversation_id]
        else:
            return []
        rows = self.conn.execute(
            "SELECT json_extract(data_json, '$.id') AS cid FROM tool_events_log "
            f"WHERE {where} AND kind = ? AND data_json IS NOT NULL "
            "GROUP BY cid HAVING cid IS NOT NULL ORDER BY MIN(id)",
            [*params, kind],
        ).fetchall()
        return [int(r["cid"]) for r in rows]

    def proposed_at(self, task_id: int, fallback: datetime) -> datetime:
        """가장 최근 `proposed` 이벤트 시각. 없으면 `fallback`(만든 시각)."""
        r = self.conn.execute(
            "SELECT at FROM task_events WHERE task_id = ? AND kind = 'proposed' ORDER BY at DESC, id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return from_iso(r["at"]) if r is not None else fallback

    def proposal_origin(self, task_id: int) -> tuple[int | None, int | None]:
        """그 초안을 만든 `propose_tasks` 도구 기록의 (회차, 대화). 기록이 없으면 (None, None)."""
        r = self.conn.execute(
            "SELECT run_id, conversation_id FROM tool_events_log WHERE task_id = ? AND kind = 'tasks_proposed' "
            "ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return (r["run_id"], r["conversation_id"]) if r is not None else (None, None)

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

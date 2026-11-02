"""마이그레이션 번호 뒤에 도는 Python 훅 (SP9 스펙 5.4, 11장).

`store.db.migrate`가 번호마다 `BEGIN` + 그 번호의 SQL → `HOOKS.get(번호)(conn, tz)` → `PRAGMA user_version` →
`COMMIT` 순서로 부른다. 훅은 그 트랜잭션 안에서 돌므로 `transaction()`(커밋한다)을 쓰지 않고 `conn.execute`만 쓴다.
훅이 예외를 내면 그 번호의 SQL과 훅의 쓰기가 함께 되돌려지고 `user_version`도 그대로다.

표를 새로 만들어 옮기는 번호(`REBUILD_MIGRATIONS`)는 `migrate`가 `BEGIN` 전에 `foreign_keys`를 끄고, `COMMIT` 전에
`REBUILD_FK_TABLES`의 표만 `foreign_key_check`로 본 뒤, 끝나면 원래 값으로 되돌린다(SP15 024).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from my_planner.clock import from_iso, local, to_iso

log = logging.getLogger(__name__)

EVENT_TITLE_MAX = 100  # 017 `events.title` CHECK (할 일 제목은 200자까지라 자른다)
EVENT_NOTE_MAX = 1000  # 017 `events.note` CHECK
MIGRATED_REMIND_MIN = 10  # 5.4: 옮긴 일정의 알림은 10분 전

Hook = Callable[[sqlite3.Connection, str], int]


def after_017(conn: sqlite3.Connection, tz: str) -> int:
    """시각 있는 열린 할 일을 일정으로 옮긴다(5.4). 만든 일정 수를 돌려준다(로그에는 그 수만 남긴다).

    대상: `status = 'open'`, `scheduled_at IS NOT NULL`, `deleted_at IS NULL`인 할 일(초안·끝냄·버림은 그대로).
    - 우선순위에 오른 적이 없고 열린 하위 할 일이 없으면: 일정 한 행 + 할 일 `deleted_at` + `task_events(updated,
      {"moved_to_event": id})`.
    - 우선순위에 올랐거나(어느 기간이든 `priorities` 행이 있으면) 열린 하위 할 일이 있으면: 할 일은 남기고 시각만
      지운 뒤 같은 시각의 일정을 따로 만든다(`from_task_id`로 잇는다). `task_events(updated, {"moved_to_event": id,
      "kept_as_task": true})`.
    일정: 제목(앞 100자), 첫 영역(넣은 순서), `note`(앞 1000자), 한 번짜리, `remind_min = 10`, `origin = 'migrated'`.
    UTC 시각은 `settings.timezone`의 현지 날짜·"HH:MM"으로 바꾼다(`clock.local`).
    """
    # 훅은 `migrate`가 앱 시계(`Clock`)를 갖기 전에 돈다: 지금 시각은 주입할 수 없어 실제 시계를 쓴다(시험은 시각 칸을 보지 않는다)
    now = to_iso(datetime.now(UTC))
    rows = conn.execute(
        "SELECT t.id, t.title, t.note, t.scheduled_at, "
        "EXISTS (SELECT 1 FROM priorities p WHERE p.task_id = t.id) AS prioritized, "
        "EXISTS (SELECT 1 FROM tasks c WHERE c.parent_id = t.id AND c.status = 'open' AND c.deleted_at IS NULL) "
        "AS has_children "
        "FROM tasks t WHERE t.status = 'open' AND t.scheduled_at IS NOT NULL AND t.deleted_at IS NULL ORDER BY t.id"
    ).fetchall()
    made = 0
    for r in rows:
        at = local(from_iso(r["scheduled_at"]), tz)
        area = conn.execute(
            "SELECT area FROM task_areas WHERE task_id = ? ORDER BY rowid LIMIT 1", (r["id"],)
        ).fetchone()
        event_id = conn.execute(
            "INSERT INTO events (title, all_day, start_date, start_time, repeat, remind_min, area, note, origin, "
            "from_task_id, created_at, updated_at) VALUES (?, 0, ?, ?, 'none', ?, ?, ?, 'migrated', ?, ?, ?)",
            (
                r["title"][:EVENT_TITLE_MAX], at.date().isoformat(), f"{at:%H:%M}", MIGRATED_REMIND_MIN,
                area[0] if area is not None else None, (r["note"] or "")[:EVENT_NOTE_MAX], r["id"], now, now,
            ),
        ).lastrowid
        payload: dict[str, object] = {"moved_to_event": event_id}
        if r["prioritized"] or r["has_children"]:
            conn.execute("UPDATE tasks SET scheduled_at = NULL, updated_at = ? WHERE id = ?", (now, r["id"]))
            payload["kept_as_task"] = True
        else:
            conn.execute("UPDATE tasks SET deleted_at = ?, updated_at = ? WHERE id = ?", (now, now, r["id"]))
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload_json, at) VALUES (?, 'updated', ?, ?)",
            (r["id"], json.dumps(payload), now),
        )
        made += 1
    # 내보내기 `tasks.md`는 여기서 다시 쓰지 않는다(훅에는 저장소도 경로도 없다): 다음 할 일 쓰기까지 옮긴 할 일이
    # 그 파일에 남아 있다. 일정 300개 상한(`EVENTS_MAX`)도 보지 않는다: 옮길 일을 버리지 않는다(넘으면 새로 만들 때만 막힌다)
    log.info("tasks_moved_to_events", extra={"count": made})
    return made


# SP15 3장 결정의 첫 줄(024가 넣는다). Task 10과 시험이 이 이름으로 찾는다
SEED_DECISION_KEY = "career_first"
SEED_DECISION_TEXT = "3년 방향: 커리어 먼저, 연애 병행"

_OLD_AGENT_CHECK = "CHECK (agent IN ('secretary', 'mate'))"
_NEW_AGENT_CHECK = "CHECK (agent IN ('secretary', 'mate', 'manager'))"
_AGENT_TABLES = ("conversations", "inbound_pending")


def _rebuild_agent_check(conn: sqlite3.Connection, table: str) -> int:
    """`table`을 `agent` CHECK에 'manager'를 더한 모양으로 새로 만들어 옮긴다. 옮긴 행 수를 돌려준다.

    SQLite는 CHECK를 바꿀 수 없다: `sqlite_master`의 `CREATE TABLE` 글에서 옛 CHECK(정확히 한 번)를 바꾸고 이름을
    `<표>__new`로 → 같은 칸 이름으로 옮기기 → 색인·트리거 글을 모아 둔 뒤 옛 표를 지우고 이름 바꾸기 → 색인·트리거
    다시 만들기. `foreign_keys`가 꺼진 채로 불러야 한다(`DROP TABLE`의 암묵 삭제, 다른 표의 참조).
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    if row is None:
        raise RuntimeError(f"rebuild: no table {table}")
    sql: str = row[0]
    if sql.count(_OLD_AGENT_CHECK) != 1:
        raise RuntimeError(f"rebuild: agent check not found once in {table}")
    head = re.compile(rf'^CREATE TABLE\s+"?{re.escape(table)}"?\s*\(')
    if head.match(sql) is None:
        raise RuntimeError(f"rebuild: unexpected create statement for {table}")
    new_sql = head.sub(f"CREATE TABLE {table}__new (", sql.replace(_OLD_AGENT_CHECK, _NEW_AGENT_CHECK), count=1)
    cols = ", ".join(f'"{r[1]}"' for r in conn.execute(f"PRAGMA table_info({table})"))
    extras = [
        r[0] for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL "
            "ORDER BY type = 'trigger', rowid",
            (table,),
        )
    ]
    conn.execute(new_sql)
    # 표 이름은 따옴표 없이 쓴다(이 모듈의 상수다. 쓰기 경로 감시 시험이 `INSERT INTO <이름>`을 읽는다)
    moved = conn.execute(f"INSERT INTO {table}__new ({cols}) SELECT {cols} FROM {table}").rowcount
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}__new RENAME TO {table}")
    for extra in extras:
        conn.execute(extra)
    return moved


def after_024(conn: sqlite3.Connection, tz: str) -> int:
    """`conversations`·`inbound_pending`의 `agent` CHECK에 'manager'를 더하고(SP15 5.1) 결정 첫 줄을 넣는다(5.4).

    옮긴 행 수를 돌려준다(로그에는 그 수만). `tz`는 쓰지 않는다(시각은 UTC로만 저장한다).
    """
    moved = sum(_rebuild_agent_check(conn, t) for t in _AGENT_TABLES)
    # 017 훅처럼 앱 시계가 아직 없어 실제 시계를 쓴다
    conn.execute(
        "INSERT INTO owner_statements (kind, area, key, text, source_ref, created_at) "
        "VALUES ('decision', 'career', ?, ?, NULL, ?)",
        (SEED_DECISION_KEY, SEED_DECISION_TEXT, to_iso(datetime.now(UTC))),
    )
    log.info("agent_tables_rebuilt", extra={"count": moved})
    return moved


HOOKS: dict[int, Hook] = {17: after_017, 24: after_024}
# 표를 새로 만들어 옮기는 번호: `migrate`가 그 번호 동안 `foreign_keys`를 끈다
REBUILD_MIGRATIONS: frozenset[int] = frozenset({24})
# 그 번호의 `COMMIT` 전에 `foreign_key_check`로 볼 표: 옮긴 표, 그 표를 가리키는 표, 새 표만(DB 전체를 보면
# 이 마이그레이션과 상관없는 옛 위반 한 줄에 늘 막힌다)
REBUILD_FK_TABLES: dict[int, tuple[str, ...]] = {
    24: ("conversations", "conversation_sessions", "panel_suggestions", "panel_predictions"),
}

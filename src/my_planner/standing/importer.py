"""`python -m my_planner standing import <파일> [--dry-run]` (SP13-07).

측정값 파일을 한 트랜잭션으로 가져온다: 줄들 + 첫 기준선 스냅숏 + X14. 두뇌를 거치지 않는다.
BE와 같은 잠금(`state/my-planner.lock`)을 잡는다. 못 잡으면 코드 3.
개인 정보: 출력과 로그에는 값이 없다. 틀린 줄은 순번과 지표 이름만 적는다.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from my_planner.clock import Clock, SystemClock, local, logical_date, period_of
from my_planner.config import PathsConfig
from my_planner.platform.windows import AlreadyRunning, SingleInstanceLock
from my_planner.standing.metrics import METRICS, validate
from my_planner.standing.service import BOUNDARY, TZ, snapshot_if_first
from my_planner.status.xp import LABEL_STANDING, XP_STANDING
from my_planner.store.db import migrate, open_db, open_ro, transaction
from my_planner.store.repos.standing import StandingRepo
from my_planner.store.repos.status import StatusRepo

EXIT_OK = 0
EXIT_RUNNING = 3
EXIT_INVALID = 5
EXIT_BAD_FILE = 6

LOCK_FILE = "my-planner.lock"
DB_FILE = "planner.db"
RUNNING_MESSAGE = "my-planner가 실행 중이에요. 작업 스케줄러에서 멈춘 뒤 다시 실행해 주세요."
BAD_FILE_MESSAGE = "측정값 파일을 읽을 수 없어요(없는 파일이거나 모양이 맞지 않아요). 아무것도 가져오지 않았어요."
DB_REJECTED_MESSAGE = "DB에 넣을 수 없는 줄이 있어요. 아무것도 가져오지 않았어요."
RELIABILITIES = ("high", "mid", "low")

Row = tuple[str, float | str, date, str]  # 지표, 값, 측정일, 신뢰도


def _load(file: Path | str) -> list[Any] | None:
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("measures"), list):
        return None
    return data["measures"]


def _check(raw: Any, today: date) -> Row | None:
    if not isinstance(raw, dict):
        return None
    metric, value, on, rel = raw.get("metric"), raw.get("value"), raw.get("measured_on"), raw.get("reliability", "mid")
    if not isinstance(metric, str) or not isinstance(on, str) or rel not in RELIABILITIES:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        measured_on = date.fromisoformat(on)
    except ValueError:
        return None
    if validate(metric, value, measured_on, today) is not None:
        return None
    return metric, value, measured_on, "low" if metric == "face_rating" else rel


def _is_dup(repo: StandingRepo, row: Row) -> bool:
    metric, value, on, _ = row
    text = value if METRICS[metric].kind == "multi" and isinstance(value, str) else None
    return repo.has_import(metric, on, text)


def _plan(rows: list[Row], repo: StandingRepo | None) -> tuple[list[Row], int]:
    todo: list[Row] = []
    seen: set[tuple[str, date, float | str | None]] = set()
    skipped = 0
    for row in rows:
        metric, value, on, _ = row
        key = (metric, on, value if METRICS[metric].kind == "multi" else None)
        if key in seen or (repo is not None and _is_dup(repo, row)):
            skipped += 1
            continue
        seen.add(key)
        todo.append(row)
    return todo, skipped


def run_import(
    root: Path | str,
    file: Path | str,
    *,
    dry_run: bool,
    out: TextIO | None = None,
    lock_factory: Callable[[Path], AbstractContextManager[Any]] = SingleInstanceLock,
    clock: Clock | None = None,
) -> int:
    out = out if out is not None else sys.stdout
    clock = clock or SystemClock()
    paths = PathsConfig.for_root(Path(root))

    def say(line: str) -> None:
        print(line, file=out)

    with ExitStack() as stack:
        try:
            stack.enter_context(lock_factory(paths.state_dir / LOCK_FILE))
        except AlreadyRunning:
            say(RUNNING_MESSAGE)
            return EXIT_RUNNING
        raw_rows = _load(file)
        if raw_rows is None:
            say(BAD_FILE_MESSAGE)
            return EXIT_BAD_FILE
        now = clock.now()
        calendar_today = local(now, TZ).date()
        rows: list[Row] = []
        bad = False
        for i, raw in enumerate(raw_rows):
            row = _check(raw, calendar_today)
            if row is None:
                name = raw.get("metric") if isinstance(raw, dict) else None
                say(f"invalid: {i} {name if isinstance(name, str) and name in METRICS else '?'}")
                bad = True
            else:
                rows.append(row)
        if bad:
            return EXIT_INVALID
        db_path = paths.state_dir / DB_FILE
        if dry_run:  # DB를 만들지 않는다: 있으면 읽기 전용으로 건너뛸 줄만 센다
            if db_path.exists():
                ro = open_ro(db_path)
                try:
                    todo, skipped = _plan(rows, StandingRepo(ro, clock))
                finally:
                    ro.close()
            else:
                todo, skipped = _plan(rows, None)
            say(f"imported: {len(todo)}, skipped: {skipped}")
            return EXIT_OK
        conn = open_db(db_path)
        try:
            migrate(conn)
            repo = StandingRepo(conn, clock)
            todo, skipped = _plan(rows, repo)
            today = logical_date(now, TZ, BOUNDARY)
            try:
                with transaction(conn):
                    for metric, value, on, rel in todo:
                        repo.add(metric, value, on, "import", None, rel, now)
                    snapshot_if_first(conn, clock, today)
                    StatusRepo(conn, clock).grant(
                        at=now, logical_date=today, source_kind="standing",
                        source_ref=f"standing:{period_of('quarter', today)}", amount=XP_STANDING,
                        label=LABEL_STANDING,
                    )
            except (sqlite3.Error, ValueError):
                say(DB_REJECTED_MESSAGE)
                return EXIT_BAD_FILE
            say(f"imported: {len(todo)}, skipped: {skipped}")
            return EXIT_OK
        finally:
            conn.close()
    return EXIT_BAD_FILE  # pragma: no cover

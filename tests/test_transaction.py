"""연결 단위 트랜잭션 `transaction(conn)` (SP3-4 티켓 01, 뒤 티켓의 "한 트랜잭션"이 모두 이것을 쓴다)."""

import re
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from my_planner.clock import FakeClock
from my_planner.store.db import transaction
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.state import StateRepo
from my_planner.store.repos.tasks import TasksRepo

SRC = Path(__file__).resolve().parents[1] / "src" / "my_planner"
NOW = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_nested_joins_outer_and_outer_commits_once(conn):
    commits = []
    conn.set_trace_callback(lambda sql: commits.append(sql) if sql.strip().upper() == "COMMIT" else None)
    with transaction(conn):
        conn.execute("INSERT INTO app_state (key, value) VALUES ('a', '1')")
        with transaction(conn):
            conn.execute("INSERT INTO app_state (key, value) VALUES ('b', '2')")
            assert conn.in_transaction
        assert conn.in_transaction  # 안쪽이 끝나도 커밋하지 않았다
    conn.set_trace_callback(None)
    assert not conn.in_transaction
    assert _count(conn, "app_state") == 2
    assert len(commits) == 1


def test_inner_exception_rolls_back_whole_outer(conn):
    with pytest.raises(ValueError), transaction(conn):
        conn.execute("INSERT INTO app_state (key, value) VALUES ('a', '1')")
        with transaction(conn):
            conn.execute("INSERT INTO app_state (key, value) VALUES ('b', '2')")
            raise ValueError("안쪽")
    assert _count(conn, "app_state") == 0
    assert not conn.in_transaction
    with transaction(conn):  # 깊이가 0으로 돌아왔다: 다시 바깥이 된다
        conn.execute("INSERT INTO app_state (key, value) VALUES ('c', '3')")
    assert _count(conn, "app_state") == 1


def test_depth_is_per_connection(tmp_path, conn):
    from my_planner.store.db import open_db

    other = open_db(tmp_path / "state" / "planner.db")
    try:
        with transaction(conn):
            conn.execute("INSERT INTO app_state (key, value) VALUES ('a', '1')")
        with transaction(other):  # 다른 연결은 따로 센다
            other.execute("INSERT INTO app_state (key, value) VALUES ('b', '2')")
        assert _count(other, "app_state") == 2
    finally:
        other.close()


def test_repo_write_inside_transaction_does_not_commit_outer(conn):
    clock = FakeClock(NOW)
    conditions = ConditionsRepo(conn, clock)
    state = StateRepo(conn, clock)
    with pytest.raises(RuntimeError), transaction(conn):
        conditions.upsert(date(2026, 10, 24), 4, None)
        state.incr_usage(date(2026, 10, 24), "proactive_messages")
        raise RuntimeError("뒤에서 실패")
    assert conditions.get(date(2026, 10, 24)) is None
    assert state.usage(date(2026, 10, 24)).proactive_messages == 0


def test_tasks_repo_transaction_delegates(conn):
    tasks = TasksRepo(conn, FakeClock(NOW))
    state = StateRepo(conn, FakeClock(NOW))
    with pytest.raises(RuntimeError), transaction(conn):
        with tasks.transaction():  # 저장소의 트랜잭션도 연결 단위 트랜잭션에 합류한다
            state.set("x", "1")
        raise RuntimeError
    assert state.get("x") is None


def test_no_with_conn_left_in_store():
    found = []
    for p in (SRC / "store").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"with\s+(self\.)?conn\s*:", line):
                found.append(f"{p.name}:{i}")
    assert found == []


def test_sp1_tasks_transaction_unchanged():
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_tools_tasks.py", "-q", "-p", "no:cacheprovider"],
        check=False, cwd=SRC.parents[1], capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 0 and "failed" not in out.stdout, out.stdout[-2000:]

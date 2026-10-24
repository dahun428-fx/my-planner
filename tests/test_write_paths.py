"""쓰기 경로 감시 (SP3-4 스펙 4.3 "누가 어느 표를 쓰나", 16장 "쓰기 경로", ADR 0007).

쓰기 연결의 데이터 쓰기마다(`open_db(on_write=…)`, `set_trace_callback`) 표 이름과, 호출 스택에서 **`my_planner.store`
밖의 첫 `my_planner` 프레임**의 모듈을 모은다. 시나리오는 수용 흐름 전부(`tests/test_api_e2e.py`, 티켓 01~15,
`run_seed_life` 포함)다. 시험 코드가 고정 자료를 직접 넣은 쓰기(그런 프레임이 없다)는 세지 않는다.
"""

import functools
import inspect
import re
import sys
from fnmatch import fnmatch

import be_env
import pytest
import test_api_e2e

from my_planner.store.db import is_write, open_db

TOOLS = "my_planner.tools.*"  # 도구 함수(`tools/core.py`), 즉시 갈래(`tools/actions.py`), 활동(`tools/activity.py`)
DISPATCHER = "my_planner.harness.dispatcher"
LOOP = "my_planner.loop.*"
SEED = "my_planner.curve.seed"  # 잠금을 잡은 별도 프로세스(4.3, 12장)

# 표 → 쓸 수 있는 모듈. 4.3 표의 줄마다(빠진 표는 SP1 그대로)
ALLOWED: dict[str, set[str]] = {
    # 4.3 1행: 도구 함수(두뇌 갈래 또는 즉시 갈래 `apply_action`). `curve_*`는 시드 가져오기도(12장)
    "tasks": {TOOLS},
    "task_areas": {TOOLS},
    "task_events": {TOOLS},
    "priorities": {TOOLS},
    "conditions": {TOOLS},
    "app_cards": {TOOLS},
    "tool_events_log": {TOOLS},
    "curve_chapters": {TOOLS, SEED},
    "curve_milestones": {TOOLS, SEED},
    "curve_ladder_scores": {TOOLS, SEED},
    "curve_area_scores": {TOOLS, SEED},
    "curve_area_defaults": {TOOLS, SEED},
    "curve_questions": {TOOLS, SEED},
    # 칭호(9.4): 사건을 확정하는 도구, 시드(12장)
    "status_titles": {TOOLS, SEED},
    # 4.3 2행: 변경과 같은 트랜잭션(`tools/activity.py`), 되돌리기 표시(`apply_action`, U5)
    "activity": {TOOLS},
    "activity_targets": {TOOLS},
    # 4.3 3행: 만들기는 도구 함수·`/actions`, 확인·거절·만료는 `apply_action`
    "pending_confirms": {TOOLS},
    # 4.3 4~6행: X1/X2/X4/X6/X7/X10 도구 함수, X3/X5/X8 디스패처의 `mark_answered`, X9 하루 한 번 작업(`apply_action`)
    "status_xp_ledger": {TOOLS, DISPATCHER},
    "runs": {LOOP, DISPATCHER},  # 4.3 5행 `answered_at`(`mark_answered`)과 마지막 행(SP1 운영 상태)
    # 4.3 7·8행: 구독 추가·삭제는 `apply_action`, 결과는 `harness/delivery.py`. `run_deliveries`도 delivery.py
    "push_subscriptions": {TOOLS, "my_planner.harness.delivery"},
    "run_deliveries": {"my_planner.harness.delivery"},
    # 4.3 9행: 받을 때 `api/chat.py`(`inbound_pending`만), 끝낼 때 디스패처(M5), `/actions`·`/undo`·명령은 `apply_action`.
    # 텔레그램 행은 SP1 그대로 `bot/telegram_io.py`
    "api_idempotency": {TOOLS, DISPATCHER},
    "inbound_pending": {"my_planner.api.chat", "my_planner.bot.telegram_io", DISPATCHER},
    # 4.3 10행: 앱 요청이 여는 대화는 `route_app_message`(디스패처 → 대화 라우터). 그 밖은 SP1 그대로
    "conversations": {"my_planner.harness.conversations", DISPATCHER},
    # 4.3 마지막 행: 운영 상태(SP1처럼 루프와 디스패처가 직접)
    "usage_state": {LOOP, DISPATCHER},
    "telegram_updates": {LOOP, DISPATCHER, "my_planner.bot.telegram_io"},
    "app_state": {
        LOOP, DISPATCHER, "my_planner.app",
        # 4.3 7행 `notify_primary`(`PUT /settings/notify` → `apply_action`), 9.1 X9 `last_rest_day_checked`
        # (하루 한 번 작업이 `apply_action`을 부른다)
        TOOLS,
        # 4.3 마지막 행의 운영 상태: 회고 단계 `ladder_prompted_run_id`, `review_step_stage`. 텔레그램 버튼 처리기도
        # 디스패처와 같은 `ReviewFlow`로 적는다(티켓 14)
        "my_planner.harness.review_steps",
        # 5.1: 앱 메시지의 `inbound_id`(`app_inbound_seq`)는 받을 때 `api/chat.py`가 `inbound_pending` 행과 함께 받는다
        "my_planner.api.chat",
        # 12장: `app_state.life_seed_imported_at`
        SEED,
    },
}

_TABLE = re.compile(
    r"^\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM|REPLACE\s+INTO)\s+(\w+)", re.IGNORECASE
)


class Recorder:
    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()
        self.unparsed: list[str] = []

    def __call__(self, sql: str) -> None:
        m = _TABLE.match(sql)
        if m is None:
            self.unparsed.append(sql.split(None, 1)[0])
            return
        f = sys._getframe(1)
        while f is not None:
            name = f.f_globals.get("__name__", "")
            if name.startswith("my_planner") and not name.startswith("my_planner.store"):
                self.seen.add((m.group(1), name))
                return
            f = f.f_back


def _allowed(table: str, module: str) -> bool:
    return any(fnmatch(module, pat) for pat in ALLOWED.get(table, set()))


def _scenarios():
    for name, fn in inspect.getmembers(test_api_e2e, inspect.iscoroutinefunction):
        if not name.startswith("test_"):
            continue
        marks = getattr(fn, "pytestmark", [])
        params = [m for m in marks if m.name == "parametrize"]
        if params:
            argname, values = params[0].args
            for v in values:
                yield name, fn, {argname: v}
        else:
            yield name, fn, {}


def test_is_write_matches_data_statements_only():
    assert is_write("INSERT INTO tasks VALUES (1)") and is_write("  update runs SET x = 1")
    assert is_write("DELETE FROM priorities") and is_write("REPLACE INTO app_state VALUES (1, 2)")
    assert not is_write("SELECT 1") and not is_write("BEGIN IMMEDIATE") and not is_write("SAVEPOINT tx_1")
    assert not is_write("BEGIN;\nCREATE TABLE t (x);\nINSERT INTO t VALUES (1);\nCOMMIT;")  # 마이그레이션


def test_on_write_sees_writes_with_caller_stack(tmp_path):
    got: list[str] = []
    conn = open_db(tmp_path / "w.db", on_write=got.append)
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.execute("SELECT * FROM t").fetchall()
    conn.execute("UPDATE t SET x = 2")
    conn.close()
    assert [s.split()[0] for s in got] == ["INSERT", "UPDATE"]


async def test_each_table_written_only_by_its_path(tmp_path, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(be_env, "ON_WRITE", rec)
    monkeypatch.setattr("my_planner.curve.seed.open_db", functools.partial(open_db, on_write=rec))
    ran = []
    for i, (name, fn, kw) in enumerate(_scenarios()):
        sub = tmp_path / f"s{i}"
        sub.mkdir()
        await fn(sub, **kw)
        ran.append(name)

    assert {"test_week_of_xp", "test_seed_then_curve", "test_month_end_review_ladder"} <= set(ran)
    assert rec.unparsed == []
    outside = sorted((t, m) for t, m in rec.seen if not _allowed(t, m))
    assert outside == []
    assert not any(m.startswith("my_planner.api.read") for _, m in rec.seen)  # 읽기 처리기는 쓰지 않는다
    # 감시가 실제로 보고 있다: 표마다 그 경로가 잡힌다
    assert ("status_xp_ledger", DISPATCHER) in rec.seen and ("status_xp_ledger", "my_planner.tools.core") in rec.seen
    assert ("status_xp_ledger", "my_planner.tools.actions") in rec.seen  # X9
    assert ("curve_milestones", SEED) in rec.seen and ("run_deliveries", "my_planner.harness.delivery") in rec.seen
    assert ("inbound_pending", "my_planner.api.chat") in rec.seen


@pytest.mark.parametrize("table", sorted(ALLOWED))
def test_allowed_tables_exist(conn, table):
    """`ALLOWED`의 표 이름이 실제 표다(오타로 감시가 비지 않게)."""
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()

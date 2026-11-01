"""쓰기 경로 감시 (SP3-4 스펙 4.3 "누가 어느 표를 쓰나", 16장 "쓰기 경로", ADR 0007).

쓰기 연결의 데이터 쓰기마다(`open_db(on_write=…)`, `set_trace_callback`) 표 이름과, 호출 스택에서 **`my_planner.store`
밖의 첫 `my_planner` 프레임**의 모듈을 모은다. 시나리오는 수용 흐름 전부(`tests/test_api_e2e.py`, 티켓 01~15,
`run_seed_life` 포함)다. 시험 코드가 고정 자료를 직접 넣은 쓰기(그런 프레임이 없다)는 세지 않는다.

도구 모듈(`TOOLS`)로 잡힌 쓰기는 누가 그 도구를 불렀는지도 본다(ADR 0007 "쓰기 경로는 `Dispatcher` 하나"):
스택에 두 갈래의 문(`GATES`: 즉시 갈래 `apply_action`, 두뇌 갈래 `Dispatcher._call_brain`) 하나가 있고, 가장 바깥
`my_planner` 프레임(HTTP 미들웨어 `HTTP_PLUMBING`은 건너뛴다)이 4.3의 입구(`ENTRIES`)여야 한다. 스택 어디에든
`my_planner.api.read` 프레임이 있으면 안 된다.
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

# 도구 함수(`tools/core.py`, 습관 `tools/habits.py`, 이룬 순간 `tools/moments.py`, 메모 `tools/memos.py`, 몸 기록
# `tools/body.py`, 스케줄 `tools/events.py`, 운동 `tools/workout.py`, 관찰 `tools/agents.py`), 즉시 갈래(`tools/actions.py`),
# 활동(`tools/activity.py`). 그 밖의 `tools.*`(어댑터, 문구, UI)는 쓰지 않는다
TOOLS = frozenset({
    "my_planner.tools.core", "my_planner.tools.habits", "my_planner.tools.actions", "my_planner.tools.activity",
    "my_planner.tools.moments", "my_planner.tools.memos", "my_planner.tools.body", "my_planner.tools.events",
    "my_planner.tools.standing", "my_planner.tools.workout", "my_planner.tools.agents",
})
MOMENTS_JOB = "my_planner.harness.moments"  # 하루 끝 작업의 날 행과 `moments_since`(SP8 6.2, 계획 결정 19)
DAYEND_JOB = "my_planner.harness.dayend"  # SP14 하루 끝 판단: 읽음 표시, 90일 정리, `agent_dayend_*` 상태
IMPORTER = "my_planner.standing.importer"
DISPATCHER = "my_planner.harness.dispatcher"
LOOP = "my_planner.loop.*"
SEED = "my_planner.curve.seed"  # 잠금을 잡은 별도 프로세스(4.3, 12장)
# 도구를 부를 수 있는 문: 즉시 갈래 하나와 두뇌 갈래 하나(4.3 1행)
GATES = frozenset({("my_planner.tools.actions", "apply_action"), (DISPATCHER, "Dispatcher._call_brain")})
# 도구 쓰기의 입구(가장 바깥 `my_planner` 프레임의 모듈, 4.3): 디스패처 작업 루프(두뇌 갈래), `/actions`·`/undo`,
# 푸시 구독·주 통로, 앱 명령(`/chat`), 텔레그램 버튼·명령, 하루 한 번 작업, 몸 기록(`/body`, SP8 7.2)
ENTRIES = frozenset({
    DISPATCHER, "my_planner.api.actions", "my_planner.api.push", "my_planner.api.chat", "my_planner.bot.callbacks",
    "my_planner.bot.telegram_io", "my_planner.loop.runner", "my_planner.api.body",
})
HTTP_PLUMBING = frozenset({"my_planner.api.server", "my_planner.api.cors", "my_planner.api.models"})
READ_API = "my_planner.api.read"

# 표 → 쓸 수 있는 모듈. 4.3 표의 줄마다(빠진 표는 SP1 그대로)
ALLOWED: dict[str, set[str]] = {
    # 4.3 1행: 도구 함수(두뇌 갈래 또는 즉시 갈래 `apply_action`). `curve_*`는 시드 가져오기도(12장)
    "tasks": set(TOOLS),
    "task_areas": set(TOOLS),
    "task_events": set(TOOLS),
    "priorities": set(TOOLS),
    "conditions": set(TOOLS),
    "app_cards": set(TOOLS),
    "tool_events_log": set(TOOLS),
    "habits": set(TOOLS),
    "habit_checks": set(TOOLS),
    # SP9 6.1: 메모는 도구 함수(두뇌 `create_memo`, 즉시 갈래 동작)와 하루 한 번 정리(`memos_daily`, 즉시 갈래)만
    "memos": set(TOOLS),
    # SP9 5.2: 일정은 도구 함수(두뇌 도구, 즉시 갈래 동작)만. 017 훅의 옮기기는 `migrate` 안이라 세지 않는다
    "events": set(TOOLS),
    "event_skips": set(TOOLS),
    "event_reminders": set(TOOLS),  # 앞으로의 알림 행 지우기(고치기), 놓친 알림 닫기. 알림 tick은 SP9-06
    "curve_chapters": {*TOOLS, SEED},
    "curve_milestones": {*TOOLS, SEED},
    "curve_ladder_scores": {*TOOLS, SEED},
    "curve_area_scores": {*TOOLS, SEED},
    "curve_area_defaults": {*TOOLS, SEED},
    "curve_questions": {*TOOLS, SEED},
    # 칭호(9.4): 사건을 확정하는 도구, 시드(12장)
    "status_titles": {*TOOLS, SEED},
    # SP8 6.1: 순간은 `save_moments`(두뇌 갈래)만. 날 행은 그 도구, 정리(`prune_records`, 즉시 갈래), 하루 끝 작업의
    # 고르기·판정(`harness/moments.py`)
    "status_moments": set(TOOLS),
    "status_moment_days": {*TOOLS, MOMENTS_JOB},
    # SP8 7.2: 몸 기록은 `record_body_days`(즉시 갈래, `/body`)와 56일 정리(`prune_records`, 즉시 갈래)만
    "body_days": set(TOOLS),
    # SP13 6.5: 측정값은 도구 함수(`save_measures`·`delete_measure`, 즉시 갈래)와 가져오기 명령(SP13-07)만.
    # 스냅숏은 그 저장·영역 점수 기록·하루 한 번 따라잡기가 부르는 `standing.service`도
    "standing_measures": {*TOOLS, "my_planner.standing.importer"},
    "standing_snapshots": {*TOOLS, "my_planner.standing.service", "my_planner.standing.importer"},
    # SP12 운동 기록·계획(도구 함수), SP14 사건 기록·받은편지함·관찰(스펙 5.1)
    "body_notes": set(TOOLS),
    "workout_plans": set(TOOLS),
    "workout_plan_sessions": set(TOOLS),
    "workout_logs": set(TOOLS),
    "workout_log_items": set(TOOLS),
    "agent_events": {*TOOLS, IMPORTER, DAYEND_JOB},  # 90일 정리는 하루 끝 작업
    "agent_inbox": {*TOOLS, DISPATCHER, DAYEND_JOB, IMPORTER},  # 읽음 표시는 디스패처·하루 끝 작업
    "agent_notes": {*TOOLS, DISPATCHER, DAYEND_JOB},  # 쓰기는 `tools.agents`, `shown_at`은 디스패처
    # 4.3 2행: 변경과 같은 트랜잭션(`tools/activity.py`), 되돌리기 표시(`apply_action`, U5)
    "activity": set(TOOLS),
    "activity_targets": set(TOOLS),
    # 4.3 3행: 만들기는 도구 함수·`/actions`, 확인·거절·만료는 `apply_action`
    "pending_confirms": set(TOOLS),
    # 4.3 4~6행: X1/X2/X4/X6/X7/X10 도구 함수, X3/X5/X8 디스패처의 `mark_answered`, X9 하루 한 번 작업(`apply_action`)
    "status_xp_ledger": {*TOOLS, DISPATCHER, "my_planner.standing.importer"},  # X14 가져오기(SP13-07)
    "runs": {LOOP, DISPATCHER},  # 4.3 5행 `answered_at`(`mark_answered`)과 마지막 행(SP1 운영 상태)
    # 4.3 7·8행: 구독 추가·삭제는 `apply_action`, 결과는 `harness/delivery.py`. `run_deliveries`도 delivery.py
    "push_subscriptions": {*TOOLS, "my_planner.harness.delivery"},
    "run_deliveries": {"my_planner.harness.delivery"},
    # 4.3 9행: 받을 때 `api/chat.py`(`inbound_pending`만), 끝낼 때 디스패처(M5), `/actions`·`/undo`·명령은 `apply_action`.
    # 텔레그램 행은 SP1 그대로 `bot/telegram_io.py`
    "api_idempotency": {*TOOLS, DISPATCHER},
    "inbound_pending": {"my_planner.api.chat", "my_planner.bot.telegram_io", DISPATCHER},
    # 4.3 10행: 앱 요청이 여는 대화는 `route_app_message`(디스패처 → 대화 라우터). 그 밖은 SP1 그대로
    "conversations": {"my_planner.harness.conversations", DISPATCHER},
    # SP9 7.1: 대화의 세션 id(새 id를 받는 디스패처, 다시 연 대화는 라우터), 지우기는 디스패처
    "conversation_sessions": {"my_planner.harness.conversations", DISPATCHER},
    # 4.3 마지막 행: 운영 상태(SP1처럼 루프와 디스패처가 직접)
    "usage_state": {LOOP, DISPATCHER},
    "telegram_updates": {LOOP, DISPATCHER, "my_planner.bot.telegram_io"},
    "app_state": {
        LOOP, DISPATCHER, "my_planner.app",
        # 4.3 7행 `notify_primary`(`PUT /settings/notify` → `apply_action`), 9.1 X9 `last_rest_day_checked`
        # (하루 한 번 작업이 `apply_action`을 부른다)
        *TOOLS,
        # 4.3 마지막 행의 운영 상태: 회고 단계 `ladder_prompted_run_id`, `review_step_stage`. 텔레그램 버튼 처리기도
        # 디스패처와 같은 `ReviewFlow`로 적는다(티켓 14)
        "my_planner.harness.review_steps",
        # 5.1: 앱 메시지의 `inbound_id`(`app_inbound_seq`)는 받을 때 `api/chat.py`가 `inbound_pending` 행과 함께 받는다
        "my_planner.api.chat",
        # 12장: `app_state.life_seed_imported_at`
        SEED,
        # SP8 6.2: `moments_since`(처음 작업이 돈 날의 전날)
        MOMENTS_JOB,
        # SP14: `agent_dayend_day:*`, `agent_dayend_attempts:*`
        DAYEND_JOB,
    },
}

_TABLE = re.compile(
    r"^\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM|REPLACE\s+INTO)\s+(\w+)", re.IGNORECASE
)


class Recorder:
    """쓰기마다 (표, 안쪽 모듈)을 `seen`에. 도구 쓰기는 (표, 안쪽 모듈, 입구 모듈, 문을 지났나)를 `tool_calls`에,
    읽기 API 프레임이 낀 쓰기는 (표, 안쪽 모듈)을 `from_read`에."""

    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()
        self.tool_calls: set[tuple[str, str, str, bool]] = set()
        self.from_read: set[tuple[str, str]] = set()
        self.unparsed: list[str] = []

    def __call__(self, sql: str) -> None:
        m = _TABLE.match(sql)
        if m is None:
            self.unparsed.append(sql.split(None, 1)[0])
            return
        table = m.group(1)
        inner: str | None = None
        entry: str | None = None
        gated = in_read = False
        f = sys._getframe(1)
        while f is not None:
            name = f.f_globals.get("__name__", "")
            if name == "my_planner.store.db" and f.f_code.co_name == "migrate":
                return  # 마이그레이션 스크립트 안의 INSERT(012의 원장 옮기기)는 앱의 쓰기 경로가 아니다
            if name.startswith("my_planner"):
                if inner is None and not name.startswith("my_planner.store"):
                    inner = name
                if name not in HTTP_PLUMBING:
                    entry = name
                gated = gated or (name, f.f_code.co_qualname) in GATES
                in_read = in_read or name == READ_API or name.startswith(READ_API + ".")
            f = f.f_back
        if inner is None:
            return
        self.seen.add((table, inner))
        if inner in TOOLS:
            self.tool_calls.add((table, inner, entry or "", gated))
        if in_read:
            self.from_read.add((table, inner))

    def bypasses(self) -> list[tuple[str, str, str, bool]]:
        """도구 쓰기인데 문을 지나지 않았거나 입구가 4.3에 없는 것."""
        return sorted(c for c in self.tool_calls if not c[3] or c[2] not in ENTRIES)


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
    assert not any(m.startswith(READ_API) for _, m in rec.seen)  # 읽기 처리기는 쓰지 않는다
    assert rec.from_read == set()  # 읽기 처리기를 거친 쓰기도 없다
    assert rec.bypasses() == []  # 도구 쓰기는 모두 두 갈래의 문을 지나 4.3의 입구에서 왔다
    # 입구 감시도 실제로 보고 있다: 두 갈래와 주요 입구가 잡힌다
    entries = {(e, g) for _, _, e, g in rec.tool_calls}
    assert {(DISPATCHER, True), ("my_planner.api.actions", True), ("my_planner.bot.callbacks", True),
            ("my_planner.loop.runner", True)} <= entries
    # 감시가 실제로 보고 있다: 표마다 그 경로가 잡힌다
    assert ("status_xp_ledger", DISPATCHER) in rec.seen and ("status_xp_ledger", "my_planner.tools.core") in rec.seen
    assert ("status_xp_ledger", "my_planner.tools.actions") in rec.seen  # X9
    assert ("curve_milestones", SEED) in rec.seen and ("run_deliveries", "my_planner.harness.delivery") in rec.seen
    assert ("inbound_pending", "my_planner.api.chat") in rec.seen
    # SP8: 순간은 두뇌 갈래의 도구만, 날 행은 하루 끝 작업도
    assert ("status_moments", "my_planner.tools.moments") in rec.seen
    assert ("status_moment_days", MOMENTS_JOB) in rec.seen and ("app_state", MOMENTS_JOB) in rec.seen
    assert ("status_moments", "my_planner.tools.moments", DISPATCHER, True) in rec.tool_calls
    # SP8 7.2: 몸 기록은 `/body` 입구에서 즉시 갈래를 지나 쓰고, 정리는 하루 한 번 작업이 즉시 갈래로
    assert ("body_days", "my_planner.tools.body", "my_planner.api.body", True) in rec.tool_calls
    assert ("body_days", "my_planner.tools.actions", "my_planner.loop.runner", True) in rec.tool_calls
    # SP13: 측정값은 `/actions`의 즉시 갈래로만, 스냅숏은 `standing.service`가(첫 기준선)
    assert ("standing_measures", "my_planner.tools.standing", "my_planner.api.actions", True) in rec.tool_calls
    assert ("standing_snapshots", "my_planner.standing.service") in rec.seen
    # SP14: 사건은 쓰기 경로마다 같은 트랜잭션에서 `tools.activity.record_agent_event`가
    assert ("agent_events", "my_planner.tools.activity", "my_planner.api.actions", True) in rec.tool_calls
    assert ("agent_inbox", "my_planner.tools.activity") in rec.seen
    # SP14 이야기(`test_sp14_master_story`): 관찰은 두뇌 갈래의 `tools.agents`, 보인 표시(`shown_at`)는 디스패처,
    # 읽음 표시와 그날 키는 하루 끝 작업
    assert ("agent_notes", "my_planner.tools.agents", DISPATCHER, True) in rec.tool_calls
    assert ("agent_notes", DISPATCHER) in rec.seen
    assert ("agent_inbox", DAYEND_JOB) in rec.seen and ("app_state", DAYEND_JOB) in rec.seen


async def test_sp8_write_paths(tmp_path, monkeypatch):
    """SP8 이야기(`tests/test_sp8_story.py`)의 쓰기도 4.3의 길만 지난다: 순간은 두뇌 갈래의 `save_moments`, 숨기기·지우기는
    `/actions`, 날 행과 `moments_since`는 하루 끝 작업(`harness/moments.py`), 몸 기록은 `/body`의 즉시 갈래."""
    from sp8_story_flow import sp8_story

    rec = Recorder()
    monkeypatch.setattr(be_env, "ON_WRITE", rec)
    await sp8_story(tmp_path)

    assert rec.unparsed == []
    assert sorted((t, m) for t, m in rec.seen if not _allowed(t, m)) == []
    assert not any(m.startswith(READ_API) for _, m in rec.seen) and rec.from_read == set()
    assert rec.bypasses() == []
    moments = {(e, g) for t, _, e, g in rec.tool_calls if t == "status_moments"}
    assert moments == {(DISPATCHER, True), ("my_planner.api.actions", True)}  # 저장(두뇌 갈래), 숨기기·지우기(`/actions`)
    assert ("status_moment_days", MOMENTS_JOB) in rec.seen and ("app_state", MOMENTS_JOB) not in rec.seen  # 이미 적힌 since
    assert ("status_moment_days", "my_planner.tools.moments", DISPATCHER, True) in rec.tool_calls
    assert ("body_days", "my_planner.tools.body", "my_planner.api.body", True) in rec.tool_calls
    assert ("habit_checks", "my_planner.tools.habits", "my_planner.api.actions", True) in rec.tool_calls


async def test_sp14_dayend_write_paths(tmp_path, monkeypatch):
    """SP14 하루 끝 판단의 쓰기: 그날 키·시도 수·읽음 표시·90일 정리는 `harness/dayend.py`, 관찰과 넘기기는 두뇌 갈래의
    `tools.agents`(입구는 디스패처). 사건은 `/actions`의 즉시 갈래로 받은편지함에 든다."""
    from be_env import BeEnv
    from fakes import FakeTurn
    from test_dispatcher_messages import kst

    rec = Recorder()
    monkeypatch.setattr(be_env, "ON_WRITE", rec)
    turn = FakeTurn([
        ("write_note", {"text": "토요일 저녁만 비어 있어요", "priority": 2, "refs": ["checkin:2026-11-01"]}),
        ("hand_off", {"to": "manager", "text": "저녁 일정이 많아요", "refs": ["checkin:2026-11-01"]}),
    ], "")
    async with BeEnv.start(tmp_path, script=[turn], start=kst(2026, 11, 2, 3, 0), dayend=True) as env:
        env.parts.runner.checkins = False
        status, _ = await env.action("record_condition", {"score": 4})  # `condition_logged` → 메이트에게도
        assert status == 200
        env.clock.set(kst(2026, 11, 2, 4, 1))
        await env.tick()
        assert [c["run_ctx"].kind for c in env.brain.calls] == ["dayend"]

    assert rec.unparsed == []
    assert sorted((t, m) for t, m in rec.seen if not _allowed(t, m)) == []
    assert rec.bypasses() == []
    assert {("app_state", DAYEND_JOB), ("agent_inbox", DAYEND_JOB), ("agent_events", DAYEND_JOB)} <= rec.seen
    assert ("agent_notes", "my_planner.tools.agents", DISPATCHER, True) in rec.tool_calls
    assert {t for t, m in rec.seen if m == DAYEND_JOB} <= {"app_state", "agent_inbox", "agent_events", "agent_notes"}


@pytest.mark.parametrize("table", sorted(ALLOWED))
def test_allowed_tables_exist(conn, table):
    """`ALLOWED`의 표 이름이 실제 표다(오타로 감시가 비지 않게)."""
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()


def _bypass(tools, module: str, task_id: int) -> None:
    """`module`에 있는 척하는 함수가 도구를 바로 부른다(두 갈래를 거치지 않는다)."""
    from my_planner.domain import RunContext

    g = {"__name__": module, "tools": tools, "RunContext": RunContext, "task_id": task_id}
    exec(  # noqa: S102 - 시험: 다른 모듈의 프레임을 꾸민다
        "def handler():\n    tools.complete_task(RunContext(conversation_id=None, run_id=None), id=task_id)\n", g
    )
    g["handler"]()


@pytest.mark.parametrize("module", [READ_API, "my_planner.bot.telegram_io", "my_planner.harness.review_steps"])
async def test_audit_flags_tool_call_that_bypasses_both_lanes(tmp_path, monkeypatch, module):
    """읽기 처리기나 다른 모듈이 `Tools`를 바로 부른 쓰기는 안쪽 모듈이 `tools.core`여도 감시에 걸린다(I3)."""
    from be_env import BeEnv
    from test_dispatcher_messages import kst

    rec = Recorder()
    monkeypatch.setattr(be_env, "ON_WRITE", rec)
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 13, 0)) as env:
        _, body = await env.action("add_task", {"title": "꾸민 할 일", "areas": ["health"]})
        assert rec.bypasses() == []  # `/actions`는 문을 지난다
        _bypass(env.parts.tools, module, body["result"]["id"])

    bad = rec.bypasses()
    assert bad and all(not gated for *_, gated in bad)
    assert {t for t, *_ in bad} >= {"tasks", "status_xp_ledger"}
    assert all(_allowed(t, m) for t, m in rec.seen)  # 안쪽 모듈만 보면 지나간다: 입구 감시가 필요한 까닭
    assert (rec.from_read != set()) == (module == READ_API)

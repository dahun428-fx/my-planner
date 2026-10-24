"""속성 시험 (SP3-4 1장 완료 조건 8, 16장): 무작위 순서의 도구, 되돌리기, 회차 답, 하루 한 번 작업 뒤에도
경험치 합계와 레벨은 줄지 않고 원장의 모든 행은 양수다. 내용은 꾸며 낸 것이다."""

import tempfile
from datetime import timedelta
from pathlib import Path

from fakes import FakeBrain, FakeSender, make_settings
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_dispatcher_messages import kst

from my_planner.app import build_be
from my_planner.clock import FakeClock, period_of, to_iso
from my_planner.domain import Cadence, LoopKey, RunContext
from my_planner.status.xp import level_for
from my_planner.store.db import migrate, open_db
from my_planner.tools.actions import ActionRequest

START = kst(2026, 10, 24, 13, 0)

OPS = st.one_of(
    st.tuples(st.just("add"), st.integers(0, 5)),
    st.tuples(st.just("complete"), st.integers(0, 7)),
    st.tuples(st.just("reopen"), st.integers(0, 7)),
    st.tuples(st.just("drop"), st.integers(0, 7)),
    st.tuples(st.just("undo"), st.integers(0, 30)),
    st.tuples(st.just("condition"), st.integers(1, 5)),
    st.tuples(st.just("ladder"), st.integers(0, 10)),
    st.tuples(st.just("areas"), st.integers(1, 10)),
    st.tuples(st.just("priority"), st.sampled_from(list(Cadence))),
    st.tuples(st.just("grant"), st.sampled_from([5, 10, 7])),
    st.tuples(st.just("answer"), st.sampled_from(list(LoopKey))),
    st.tuples(st.just("hours"), st.integers(1, 40)),
    st.tuples(st.just("daily"), st.just(0)),
)


def _parts(root: Path):
    s = make_settings(root)
    conn = open_db(s.paths.state_dir / "planner.db")
    migrate(conn)
    clock = FakeClock(START)
    parts = build_be(s, conn, clock, brain_factory=lambda tools: FakeBrain([], tools, clock=clock),
                     sender_factory=lambda _t: FakeSender())
    parts.state.set("installed_at", to_iso(START - timedelta(minutes=1)))
    return parts, conn, clock


def _apply(parts, action, args, channel="app"):
    actor = "secretary" if channel == "scheduler" else "user"
    return parts.dispatcher.apply_action(ActionRequest(action, args, actor=actor, channel=channel))


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(OPS, min_size=1, max_size=25))
def test_xp_and_level_never_decrease(ops):
    with tempfile.TemporaryDirectory() as tmp:
        parts, conn, clock = _parts(Path(tmp))
        try:
            ids: list[int] = []
            total = parts.dispatcher.xp_total()
            for op, v in ops:
                if op == "add":
                    res = _apply(parts, "add_task", {"title": f"꾸민 일 {v}", "areas": ["health"]})
                    if res.status == "applied":
                        ids.append(res.body["result"]["id"])
                elif op in ("complete", "reopen", "drop") and ids:
                    action = {"complete": "complete_task", "reopen": "reopen_task", "drop": "drop_task"}[op]
                    _apply(parts, action, {"id": ids[v % len(ids)]}, channel="telegram")  # 확인 없이 바로
                elif op == "undo":
                    _apply_undo(parts, v)
                elif op == "condition":
                    _apply(parts, "record_condition", {"score": v})
                elif op == "ladder":
                    _apply(parts, "record_ladder_score", {"now": v})
                elif op == "areas":
                    _apply(parts, "record_area_scores", {"scores": {"career": v}})
                elif op == "priority" and ids:
                    today = parts.tools.today()
                    _apply(parts, "set_priorities", {"cadence": v.value, "period": period_of(v, today),
                                                     "task_ids": ids[-1:]}, channel="telegram")
                elif op == "grant":
                    parts.tools.grant_xp(RunContext(conversation_id=None, run_id=None), amount=v, reason="꾸민 사유")
                elif op == "answer":
                    run = parts.runs.ensure(v, clock.now() - timedelta(minutes=10),
                                            Cadence.week if v is LoopKey.review else Cadence.day)
                    parts.runs.mark_done(run.id)
                    parts.dispatcher.mark_answered(run.id, "app")
                elif op == "hours":
                    clock.advance(hours=v)
                elif op == "daily":
                    _apply(parts, "grant_rest_days", {}, channel="scheduler")
                now_total = parts.dispatcher.xp_total()
                assert now_total >= total, op
                assert level_for(now_total) >= level_for(total), op
                total = now_total
            amounts = [r[0] for r in conn.execute("SELECT amount FROM status_xp_ledger")]
            assert all(a > 0 for a in amounts)
            assert sum(amounts) == total
        finally:
            conn.close()


def _apply_undo(parts, v):
    ids = [r[0] for r in parts.tools.tasks.conn.execute("SELECT id FROM activity ORDER BY id").fetchall()]
    if ids:
        parts.dispatcher.apply_action(ActionRequest("undo", {"activity_id": ids[v % len(ids)]}, actor="user",
                                                    channel="app", endpoint="undo"))

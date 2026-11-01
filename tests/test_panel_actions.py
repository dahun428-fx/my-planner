"""SP15-09: 제안 받기·버리기·내가 한 말 지우기(`/actions`)와 되돌리기(T6, T7, T14, T19, 스펙 5.4, 7.1, 7.4).

글과 값은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from be_env import BeEnv
from test_api_undo import undo
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.store.db import transaction

WED = kst(2026, 11, 4, 12, 0)  # 논리적 오늘 2026-11-04, 2026-W45
TODAY = date(2026, 11, 4)
EV_BENCH = {"type": "external", "ref": "bench:income", "note": "가짜 기준"}


def _suggest(env, *, kind: str = "task", area: str = "career", title: str = "가짜 제안", per_week: int | None = None,
             due_hint: date | None = None, evidence: list[dict[str, str]] | None = None) -> int:
    with transaction(env.conn):
        return env.parts.panel.add_suggestion(
            conversation_id=None, kind=kind, title=title, area=area, size_min=30, per_week=per_week,
            due_hint=due_hint, experts=["career"], evidence=evidence or [EV_BENCH], week="2026-W45",
            now=env.clock.now(),
        )


def _q(env, sql: str, *args: Any) -> list[Any]:
    return env.conn.execute(sql, args).fetchall()


def _events(env, kind: str) -> list[Any]:
    return _q(env, "SELECT ref, area FROM agent_events WHERE kind = ? ORDER BY id", kind)


def _xp_rows(env) -> int:
    return _q(env, "SELECT COUNT(*) FROM status_xp_ledger")[0][0]


async def test_accept_makes_task_and_events_same_txn(tmp_path, monkeypatch):
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env, due_hint=date(2026, 11, 10))
        status, body = await env.action("accept_suggestion", {"id": sid})
        (task,) = _q(env, "SELECT id, title, status, planned_for FROM tasks")
        areas = [r[0] for r in _q(env, "SELECT area FROM task_areas WHERE task_id = ?", task["id"])]
        added, accepted = _events(env, "task_added"), _events(env, "suggestion_accepted")
        row = env.parts.panel.suggestion(sid)
        (act,) = _q(env, "SELECT kind, target, summary, risk FROM activity")
        targets = [r[0] for r in _q(env, "SELECT target FROM activity_targets ORDER BY target")]

        # 사건 쓰기가 실패하면 할 일도 없고 제안은 그대로다
        other = _suggest(env, area="health", title="가짜 둘")
        from my_planner.tools import core

        real = core.record_agent_event

        def broken(repo, ctx, kind, *a: Any, **kw: Any):
            if kind == "suggestion_accepted":
                raise RuntimeError("가짜 실패")
            return real(repo, ctx, kind, *a, **kw)

        monkeypatch.setattr(core, "record_agent_event", broken)
        failed = await env.post("/actions", json={"action": "accept_suggestion", "args": {"id": other},
                                                  "client_msg_id": "cm-broken"})
        n_tasks = _q(env, "SELECT COUNT(*) FROM tasks")[0][0]
        other_row = env.parts.panel.suggestion(other)
    assert status == 200 and body["status"] == "applied", body
    assert body["result"] == {"ok": True, "result_ref": f"task:{task['id']}"}
    assert body["confirmation"] == "✓ 제안 받음 · 가짜 제안" and body["undo_id"] == body["activity_id"]
    assert (task["title"], task["status"], task["planned_for"]) == ("가짜 제안", "open", "2026-11-10")
    assert areas == ["career"]
    assert [tuple(r) for r in added] == [(f"task:{task['id']}", "career")]
    assert [tuple(r) for r in accepted] == [(f"suggestion:{sid}", "career")]
    assert row.state == "accepted" and row.result_ref == f"task:{task['id']}" and row.decided_at is not None
    assert tuple(act) == ("suggestion_accepted", f"suggestion:{sid}", "✓ 제안 받음 · 가짜 제안", "low")
    assert targets == [f"suggestion:{sid}", f"task:{task['id']}"]
    assert failed.status == 500
    assert n_tasks == 1 and other_row.state == "proposed" and other_row.result_ref is None


async def test_accept_task_without_due_is_today(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env)
        await env.action("accept_suggestion", {"id": sid})
        (task,) = _q(env, "SELECT planned_for FROM tasks")
    assert task["planned_for"] == TODAY.isoformat()


async def test_accept_habit_per_week(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        two = _suggest(env, kind="habit", area="health", title="가짜 걷기", per_week=2)
        seven = _suggest(env, kind="habit", area="health", title="가짜 스트레칭", per_week=7)
        s2, b2 = await env.action("accept_suggestion", {"id": two})
        s7, b7 = await env.action("accept_suggestion", {"id": seven})
        habits = _q(env, "SELECT id, title, area, kind, target_per_week FROM habits ORDER BY id")
        tasks = _q(env, "SELECT COUNT(*) FROM tasks")[0][0]
    assert (s2, s7) == (200, 200)
    assert [tuple(h)[1:] for h in habits] == [
        ("가짜 걷기", "health", "weekly", 2), ("가짜 스트레칭", "health", "daily", None),
    ]
    assert b2["result"]["result_ref"] == f"habit:{habits[0]['id']}"
    assert b7["result"]["result_ref"] == f"habit:{habits[1]['id']}"
    assert tasks == 0


async def test_accept_twice_one_task(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env)
        first = await env.action("accept_suggestion", {"id": sid})
        second = await env.action("accept_suggestion", {"id": sid})
        dismiss = await env.action("dismiss_suggestion", {"id": sid, "reason": "too_big"})
        missing = await env.action("accept_suggestion", {"id": 999})
        n_tasks = _q(env, "SELECT COUNT(*) FROM tasks")[0][0]
        accepted = _events(env, "suggestion_accepted")
    assert first[0] == 200
    assert second[0] == 422 and second[1]["error"]["message"] == "이미 정한 제안이에요."
    assert dismiss[0] == 422 and dismiss[1]["error"]["message"] == "이미 정한 제안이에요."
    assert missing[0] == 404
    assert n_tasks == 1 and len(accepted) == 1


async def test_accept_no_extra_xp_then_x1(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env)
        before = _xp_rows(env)
        _, body = await env.action("accept_suggestion", {"id": sid})
        after_accept = _xp_rows(env)
        tid = int(body["result"]["result_ref"].removeprefix("task:"))
        await env.action("complete_task", {"id": tid})
        rows = _q(env, "SELECT source_kind, amount FROM status_xp_ledger")
    assert after_accept == before == 0
    assert body["xp"]["gained"] == 0
    assert [tuple(r) for r in rows] == [("task_done", 10)]


async def test_undo_accept(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env)
        _, body = await env.action("accept_suggestion", {"id": sid})
        n_events = _q(env, "SELECT COUNT(*) FROM agent_events")[0][0]
        status, out = await undo(env, body["undo_id"])
        (task,) = _q(env, "SELECT deleted_at FROM tasks")
        row = env.parts.panel.suggestion(sid)
        n_after = _q(env, "SELECT COUNT(*) FROM agent_events")[0][0]

        habit = _suggest(env, kind="habit", area="health", title="가짜 걷기", per_week=3)
        _, hb = await env.action("accept_suggestion", {"id": habit})
        h_status, _ = await undo(env, hb["undo_id"])
        (h,) = _q(env, "SELECT deleted_at FROM habits")
        h_row = env.parts.panel.suggestion(habit)
    assert status == 200 and out["status"] == "undone"
    assert task["deleted_at"] is not None
    assert (row.state, row.result_ref, row.decided_at) == ("proposed", None, None)
    assert n_after == n_events
    assert h_status == 200 and h["deleted_at"] is not None and h_row.state == "proposed"


async def test_undo_accept_after_done_superseded(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env)
        _, body = await env.action("accept_suggestion", {"id": sid})
        tid = int(body["result"]["result_ref"].removeprefix("task:"))
        await env.action("complete_task", {"id": tid})
        status, out = await undo(env, body["undo_id"])
        (task,) = _q(env, "SELECT status, deleted_at FROM tasks")
        row = env.parts.panel.suggestion(sid)
    assert status == 409 and out["error"]["code"] == "superseded"
    assert (task["status"], task["deleted_at"]) == ("done", None)
    assert row.state == "accepted"


async def test_undo_accept_handler_superseded_when_done(tmp_path):
    """U3 밖에서 할 일이 끝났어도(활동 없이 바뀐 상태) 처리 함수가 `superseded`로 막는다."""
    async with BeEnv.start(tmp_path, start=WED) as env:
        sid = _suggest(env)
        _, body = await env.action("accept_suggestion", {"id": sid})
        with transaction(env.conn):
            env.conn.execute("UPDATE tasks SET status = 'done', completed_at = created_at")
        status, out = await undo(env, body["undo_id"])
        row = env.parts.panel.suggestion(sid)
    assert status == 409 and out["error"]["code"] == "superseded"
    assert row.state == "accepted"


async def test_dismiss_reason_twice_makes_statement(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        a, b, c = (_suggest(env, title=f"가짜 커리어 {i}") for i in range(3))
        n1, n2 = (_suggest(env, area="health", title=f"가짜 건강 {i}") for i in range(2))
        s1, d1 = await env.action("dismiss_suggestion", {"id": a, "reason": "too_big"})
        none_yet = _q(env, "SELECT COUNT(*) FROM owner_statements WHERE source_ref LIKE 'suggestion:%'")[0][0]
        s2, d2 = await env.action("dismiss_suggestion", {"id": b, "reason": "too_big"})
        made = _q(env, "SELECT id, kind, area, text, source_ref, retired_at FROM owner_statements "
                       "WHERE source_ref LIKE 'suggestion:%'")
        await env.action("dismiss_suggestion", {"id": c, "reason": "too_big"})
        await env.action("dismiss_suggestion", {"id": n1})
        await env.action("dismiss_suggestion", {"id": n2, "reason": "none"})
        bad = await env.action("dismiss_suggestion", {"id": _suggest(env, title="가짜 넷"), "reason": "bored"})
        after_three = _q(env, "SELECT COUNT(*) FROM owner_statements WHERE source_ref LIKE 'suggestion:%'")[0][0]
        dismissed = _events(env, "suggestion_dismissed")
        row_b = env.parts.panel.suggestion(b)
        u_status, _ = await undo(env, d2["undo_id"])
        (st,) = _q(env, "SELECT retired_at FROM owner_statements WHERE id = ?", made[0]["id"])
        back = env.parts.panel.suggestion(b)
    assert (s1, s2) == (200, 200) and none_yet == 0
    assert d1["confirmation"] == "✓ 제안 버림 · 가짜 커리어 0"
    assert [tuple(r)[1:] for r in made] == [
        ("preference", "career", "커리어 제안이 너무 크다고 두 번 버렸어요.", f"suggestion:{b}", None),
    ]
    assert after_three == 1
    assert bad[0] == 422
    assert [r["ref"] for r in dismissed] == [f"suggestion:{i}" for i in (a, b, c, n1, n2)]
    assert (row_b.state, row_b.dismiss_reason) == ("dismissed", "too_big") and row_b.decided_at is not None
    assert u_status == 200 and st["retired_at"] is not None
    assert (back.state, back.dismiss_reason, back.decided_at) == ("proposed", None, None)


async def test_dismiss_statement_templates(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        for reason in ("no_time", "not_interested", "already"):
            for i in range(2):
                sid = _suggest(env, area="quality_of_life", title=f"가짜 {reason} {i}")
                await env.action("dismiss_suggestion", {"id": sid, "reason": reason})
        texts = [r[0] for r in _q(env, "SELECT text FROM owner_statements WHERE source_ref LIKE 'suggestion:%' "
                                       "ORDER BY id")]
    assert texts == [
        "삶의 질 제안을 시간이 없다고 두 번 버렸어요.",
        "삶의 질 제안에 관심 없다고 두 번 버렸어요.",
        "삶의 질 제안을 이미 하고 있다고 두 번 버렸어요.",
    ]


async def test_retire_statement_and_evidence(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        with transaction(env.conn):
            stid = env.parts.panel.add_statement("fact", "career", "가짜 사실", now=env.clock.now())
            conv = int(env.conn.execute(
                "INSERT INTO conversations (kind, channel, logical_date, opened_at, last_message_at, agent) "
                "VALUES ('chat', 'app', '2026-11-04', 'a', 'a', 'manager')"
            ).lastrowid)
        args = {
            "kind": "task", "title": "가짜 제안", "area": "career", "size_min": 30, "experts": ["career"],
            "evidence": [{"type": "statement", "ref": f"statement:{stid}", "note": "가짜 근거"}, EV_BENCH],
        }

        def propose() -> dict[str, Any]:
            ctx = RunContext(conv, None, channel="app", agent="manager", in_brain=True)
            return env.parts.tools.propose_suggestion(ctx, **args)

        status, body = await env.action("retire_statement", {"id": stid})
        retired = propose()
        again = await env.action("retire_statement", {"id": stid})
        missing = await env.action("retire_statement", {"id": 999})
        u_status, _ = await undo(env, body["undo_id"])
        ok = propose()
        (act,) = _q(env, "SELECT summary, target FROM activity WHERE kind = 'statement_retired'")
        # 결정도 지울 수 있다
        dec = env.parts.panel.decision("career_first")
        d_status, _ = await env.action("retire_statement", {"id": dec.id})
        dec_after = env.parts.panel.decision("career_first")
    assert status == 200 and body["confirmation"] == "✓ 내가 한 말 지움"
    assert tuple(act) == ("✓ 내가 한 말 지움", f"statement:{stid}")
    assert retired["rejected"] == "unknown_ref"
    assert again[0] == 422 and missing[0] == 404
    assert u_status == 200 and ok["ok"] is True
    assert d_status == 200 and dec_after is None

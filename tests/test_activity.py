"""활동 기록 (SP3-4 스펙 5.2, 6.4.4)과 하루 한 번 작업의 즉시 갈래. 내용은 꾸며 낸 것이다."""

import json
from datetime import timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from test_tools_tasks import ToolEnv

from my_planner.clock import to_iso
from my_planner.domain import RunContext, TaskStatus
from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo, IdempotencyRepo
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.views import draft_live

SAT_1300 = kst(2026, 10, 24, 13, 0)


class ActivityEnv(ToolEnv):
    def __init__(self, tmp_path, conn):
        super().__init__(tmp_path, conn)
        self.activity = ActivityRepo(conn, self.clock)
        self.conditions = ConditionsRepo(conn, self.clock)
        self.tools.activity = self.activity
        self.tools.conditions = self.conditions

    def rows(self):
        return self.conn.execute("SELECT * FROM activity ORDER BY id").fetchall()


@pytest.fixture
def aenv(tmp_path, conn):
    return ActivityEnv(tmp_path, conn)


def _boom(*a, **kw):
    raise RuntimeError("boom")


def test_activity_same_transaction_as_change(aenv, monkeypatch):
    tid = aenv.tools.add_task(aenv.ctx(), title="운동", areas=["health"])["id"]
    monkeypatch.setattr(aenv.activity, "add", _boom)

    with pytest.raises(RuntimeError):
        aenv.tools.add_task(aenv.ctx(), title="새 일", areas=["career"])
    with pytest.raises(RuntimeError):
        aenv.tools.complete_task(aenv.ctx(), id=tid)

    count = aenv.conn.execute("SELECT count(*) FROM tasks").fetchone()[0]
    assert count == 1  # 새 할 일이 없다
    assert aenv.repo.get(tid).status is TaskStatus.open  # 완료도 되돌려졌다
    kinds = [r["kind"] for r in aenv.conn.execute("SELECT kind FROM tool_events_log")]
    assert kinds == ["task_added"]
    assert len(aenv.rows()) == 1


def test_record_condition_and_activity_atomic(aenv, monkeypatch):
    monkeypatch.setattr(aenv.activity, "add", _boom)
    with pytest.raises(RuntimeError):
        aenv.tools.record_condition(aenv.ctx(), score=4)
    assert aenv.conn.execute("SELECT count(*) FROM conditions").fetchone()[0] == 0
    assert aenv.rows() == []


def test_every_mutation_records_activity_with_undo_before_values(aenv):
    t = aenv.tools
    a = t.add_task(aenv.ctx(), title="운동", areas=["health"], planned_for="2026-10-24")["id"]
    b = t.add_task(aenv.ctx(), title="독서", areas=["learning"])["id"]
    t.update_task(aenv.ctx(), id=a, title="아침 운동")
    t.move_task(aenv.ctx(), id=a, planned_for="2026-10-25")
    t.set_priorities(aenv.ctx(), cadence="week", period="2026-W43", task_ids=[a])
    t.complete_task(aenv.ctx(), id=b)
    t.reopen_task(aenv.ctx(), id=b)
    t.drop_task(aenv.ctx(), id=a)
    (d,) = [x["id"] for x in t.propose_tasks(aenv.ctx(), tasks=[{"title": "산책", "areas": ["health"]}])["proposed"]]
    t.confirm_tasks(aenv.ctx(), ids=[d])
    t.record_condition(aenv.ctx(), score=3, note="꾸민 메모")
    t.record_condition(aenv.ctx(), score=4)

    rows = aenv.rows()
    got = [(r["kind"], r["target"], r["summary"]) for r in rows]
    assert got == [
        ("task_added", f"task:{a}", "✓ 추가: 운동 → 오늘"),
        ("task_added", f"task:{b}", "✓ 추가: 독서"),
        ("task_updated", f"task:{a}", "✓ 바꿈: 아침 운동"),
        ("task_moved", f"task:{a}", "✓ 옮김: 아침 운동 → 내일"),
        ("priorities_set", "priorities:week:2026-W43", "✓ 우선순위(이번 주): 1. 아침 운동"),
        ("task_completed", f"task:{b}", "✓ 완료: 독서"),
        ("task_reopened", f"task:{b}", "✓ 되돌림: 독서"),
        ("task_dropped", f"task:{a}", "✓ 내려놓음: 아침 운동"),
        ("tasks_proposed", f"task:{d}", "✓ 제안: 산책"),
        ("tasks_confirmed", f"task:{d}", "✓ 확정: 산책"),
        ("condition_recorded", "condition:2026-10-24", "✓ 컨디션: 3 (오늘)"),
        ("condition_recorded", "condition:2026-10-24", "✓ 컨디션: 4 (오늘)"),
    ]
    undo = [json.loads(r["undo_json"]) if r["undo_json"] else None for r in rows]
    assert undo[0] == {"task_id": a}
    assert undo[2] == {"task_id": a, "before": {"title": "운동"}}
    assert undo[3] == {"task_id": a, "planned_for": "2026-10-24", "scheduled_at": None}
    assert undo[4] == {"cadence": "week", "period": "2026-W43", "task_ids": []}
    assert undo[5]["status"] == "open" and undo[5]["completed_at"] is None
    assert undo[6]["status"] == "done" and undo[6]["completed_at"] is not None
    assert undo[7]["status"] == "open" and undo[7]["priorities"] == [["week", "2026-W43", 1]]
    assert undo[8] is None  # 제안은 되돌리기가 없다
    assert undo[9] == {"task_ids": [d]}
    assert undo[10] == {"date": "2026-10-24", "before": None}
    assert undo[11]["before"]["score"] == 3 and undo[11]["before"]["note"] == "꾸민 메모"
    assert {(r["actor"], r["channel"], r["risk"]) for r in rows} == {("secretary", "telegram", "low")}
    assert all(r["conversation_id"] == 1 for r in rows)


def test_ctx_collects_activity_and_undo_ids(aenv):
    ctx = aenv.ctx()
    aenv.tools.add_task(ctx, title="운동", areas=["health"])
    aenv.tools.propose_tasks(ctx, tasks=[{"title": "산책", "areas": ["health"]}])
    ids = [r["id"] for r in aenv.rows()]
    assert ctx.activity_ids == ids
    assert ctx.undo_ids == ids[:1]  # 제안은 되돌릴 수 없다


async def test_actor_channel_mapping(tmp_path):
    add = ("add_task", {"title": "물 마시기", "areas": ["health"]})
    brief = ("add_task", {"title": "스트레칭", "areas": ["health"]})
    propose = ("propose_tasks", {"tasks": [{"title": "산책", "areas": ["health"]}]})
    script = [FakeTurn([brief], "좋은 아침이에요"), FakeTurn([add, propose], "넣었어요")]
    # 토요일 10:00:30: 주말 아침 브리핑(회차 첫 호출 → scheduler)
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 24, 10, 0) + timedelta(seconds=30), script=script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 24, 13, 0))
        await env.telegram("물 마시기 추가해 줘")  # 사용자 메시지에 답하는 두뇌 → secretary/telegram
        draft = env.parts.tasks.list(status="draft")[0].id
        await env.press(f"d:c:{draft}")  # 버튼 → user/telegram
        await env.action("record_condition", {"score": 4})  # /actions → user/app
        env.parts.tools.propose_tasks(RunContext(conversation_id=None, run_id=None),
                                      tasks=[{"title": "오래된 초안", "areas": ["career"]}])
        env.clock.set(kst(2026, 10, 28, 13, 0))
        env.parts.state.set("last_seen_at", to_iso(env.clock.now() - timedelta(minutes=1)))
        await env.tick()  # 하루 한 번 작업: 초안 만료 → secretary/scheduler
        rows = [(r["kind"], r["actor"], r["channel"]) for r in env.activity()]

    assert rows == [
        ("task_added", "secretary", "scheduler"),
        ("task_added", "secretary", "telegram"),
        ("tasks_proposed", "secretary", "telegram"),
        ("tasks_confirmed", "user", "telegram"),
        ("condition_recorded", "user", "app"),
        ("tasks_proposed", "secretary", "telegram"),
        ("drafts_expired", "secretary", "scheduler"),
    ]


async def test_activity_summary_has_no_message_body(tmp_path):
    body = "꾸민 본문 문장 열두 글자"
    add = ("add_task", {"title": "물 마시기", "areas": ["health"], "note": "꾸민 노트 문장"})
    async with BeEnv.start(tmp_path, start=SAT_1300, script=[FakeTurn([add], "넣었어요")]) as env:
        await env.telegram(body)
        await env.action("record_condition", {"score": 2, "note": "꾸민 컨디션 메모"})
        await env.action("update_task", {"id": 1, "note": "꾸민 새 노트"})
        summaries = [r["summary"] for r in env.activity()]

    assert summaries == ["✓ 추가: 물 마시기", "✓ 컨디션: 2 (오늘)", "✓ 바꿈: 물 마시기"]
    for s in summaries:
        for text in (body, "꾸민 노트 문장", "꾸민 컨디션 메모", "꾸민 새 노트"):
            assert text not in s


async def test_buttons_go_through_apply_action(tmp_path, monkeypatch):
    propose = ("propose_tasks", {"tasks": [{"title": "산책", "areas": ["health"]},
                                           {"title": "스트레칭", "areas": ["health"]}]})
    async with BeEnv.start(tmp_path, start=SAT_1300, script=[FakeTurn([propose], "어때요?")]) as env:
        await env.telegram("오늘 뭐 할까")
        a, b = [t.id for t in env.parts.tasks.list(status="draft")]
        seen = []
        real = env.parts.dispatcher.apply_action

        def spy(req):
            seen.append((req.action, req.actor, req.channel))
            return real(req)

        monkeypatch.setattr(env.parts.dispatcher, "apply_action", spy)
        # 처리기는 조립 때 묶은 함수를 쓴다: 그 함수가 디스패처의 즉시 갈래인지 본다
        assert env.parts.callbacks.keywords["apply"] == real
        env.parts.callbacks.keywords["apply"] = spy
        assert await env.press(f"d:c:{a}") == "confirmed"
        assert await env.press(f"d:x:{b}") == "dropped"
        assert await env.press("c:2026-10-24:5") == "recorded"
        assert await env.press(f"d:c:{a}") == "stale"
        rows = [(r["kind"], r["actor"], r["channel"], r["target"]) for r in env.activity()][1:]
        answers = [t for _, t in env.bot.answers]

    assert seen == [("confirm_tasks", "user", "telegram"), ("drop_task", "user", "telegram"),
                    ("record_condition", "user", "telegram")]
    assert rows == [
        ("tasks_confirmed", "user", "telegram", f"task:{a}"),
        ("task_dropped", "user", "telegram", f"task:{b}"),
        ("condition_recorded", "user", "telegram", "condition:2026-10-24"),
    ]
    assert answers == ["✓ 확정: 산책", "✗ 뺐어요: 스트레칭", "컨디션 5 기록했어요.", "이미 정리된 할 일이에요."]


async def test_daily_jobs_expire_tokens_and_prune_idempotency(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        a = (await env.action("add_task", {"title": "가", "areas": ["health"]}, client_msg_id="old-1"))[1]
        q = {"cadence": "quarter", "period": "2026-Q4"}
        await env.action("set_priorities", {**q, "task_ids": [a["result"]["id"]]})
        _, nc = await env.action("set_priorities", {**q, "task_ids": []})
        token = nc["confirm_token"]

        def tick_at(at):
            env.clock.set(at)
            env.parts.state.set("last_seen_at", to_iso(at - timedelta(minutes=1)))
            return env.tick()

        await tick_at(kst(2026, 10, 25, 13, 0))  # 다음 날: 토큰 만료(10분), 요청 기록은 아직(2일)
        resolution = env.conn.execute("SELECT resolution FROM pending_confirms WHERE token = ?",
                                      (token,)).fetchone()[0]
        kept = env.conn.execute("SELECT count(*) FROM api_idempotency").fetchone()[0]
        await tick_at(kst(2026, 10, 26, 13, 1))  # 2일 지남: 요청 기록 정리
        pruned = env.conn.execute("SELECT count(*) FROM api_idempotency").fetchone()[0]
        tokens_mid = env.conn.execute("SELECT count(*) FROM pending_confirms").fetchone()[0]
        await tick_at(kst(2026, 10, 31, 13, 1))  # 7일 지남: 토큰 행 정리
        tokens_end = env.conn.execute("SELECT count(*) FROM pending_confirms").fetchone()[0]
        replay = await env.action("add_task", {"title": "가", "areas": ["health"]}, client_msg_id="old-1")
        activity = [r["kind"] for r in env.activity()]

    assert resolution == "expired"
    assert kept == 3 and pruned == 0
    assert tokens_mid == 1 and tokens_end == 0
    assert replay[0] == 200 and replay[1]["result"]["id"] != a["result"]["id"]  # 지운 뒤에는 새 요청이다
    assert "drafts_expired" not in activity  # 정리할 초안이 없으면 활동도 없다


def test_expire_drafts_counts_from_latest_proposed(aenv):
    """`/drafts`(`draft_live`)와 밤 정리가 같은 시각(`proposed_at`)을 본다(스펙 6.3.8)."""
    ttl = 3
    (d,) = [x["id"] for x in aenv.tools.propose_tasks(aenv.ctx(), tasks=[{"title": "산책", "areas": ["health"]}])
            ["proposed"]]
    (old,) = [x["id"] for x in aenv.tools.propose_tasks(aenv.ctx(), tasks=[{"title": "독서", "areas": ["learning"]}])
              ["proposed"]]
    aenv.clock.advance(days=2)
    aenv.repo._event(d, "proposed")  # 확정 되돌리기처럼 다시 제안한 시각(6.4.3)
    aenv.clock.advance(days=1)  # 만든 지 3일, 다시 제안한 지 1일

    now = aenv.clock.now()
    live = {i: draft_live(aenv.repo.get(i), aenv.repo, ttl, now) for i in (d, old)}
    ctx = RunContext(conversation_id=None, run_id=None, activity_channel="scheduler")
    out = aenv.tools.expire_drafts(ctx, now - timedelta(days=ttl))

    assert live == {d: True, old: False}
    assert out == {"expired_ids": [old]}
    assert aenv.repo.get(d).status is TaskStatus.draft
    assert aenv.repo.get(old).status is TaskStatus.dropped
    (row,) = [r for r in aenv.rows() if r["kind"] == "drafts_expired"]
    assert (row["actor"], row["channel"], row["summary"], row["undo_json"]) == (
        "secretary", "scheduler", "✓ 초안 정리: 1개", None)
    aenv.clock.advance(days=2)  # 다시 제안한 지 3일
    assert aenv.repo.expire_drafts(aenv.clock.now() - timedelta(days=ttl)) == [d]


def test_repos_roundtrip(conn):
    from my_planner.clock import FakeClock

    clock = FakeClock(SAT_1300)
    confirms, idem = ConfirmsRepo(conn, clock), IdempotencyRepo(conn, clock)
    p = confirms.create(action="drop_task", args={"id": 1}, summary="꾸민 확인", origin="actions",
                        expires_at=clock.now() + timedelta(minutes=10))
    assert p.token.startswith("ct_") and len(p.token) == 3 + 22
    assert confirms.get(p.token).args == {"id": 1} and p.open_at(clock.now())
    assert confirms.resolve(p.token, "applied") and not confirms.resolve(p.token, "declined")
    assert confirms.get(p.token).resolution == "applied"
    idem.put("c1", "actions", 200, {"status": "applied"})
    got = idem.get("c1")
    assert (got.endpoint, got.status_code, got.body) == ("actions", 200, {"status": "applied"})
    clock.advance(days=2, seconds=1)
    assert idem.prune(clock.now() - timedelta(days=2)) == 1 and idem.get("c1") is None

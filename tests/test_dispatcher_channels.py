"""통로별 대화 규칙, 회차 대화 가르기, 답한 회차 (SP3-4 스펙 7.1, 7.2, 6.4.5, 7.5 M3).

가짜 두뇌 + 가짜 시계(`BeEnv`). 날짜는 2026-10-26(월): 아침 브리핑 09:00, 저녁 체크인 17:30(답장 창은 10/27 04:00까지).
내용은 모두 꾸며 낸 것이다.
"""

import logging
from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from ui_stream import parse_sse

EVENING = kst(2026, 10, 26, 17, 30) + timedelta(seconds=30)
RUN_TEXT = "오늘 하루 어떠셨어요? 꾸민 회차 본문"


def start_meta(raw):
    return parse_sse(raw)[0]["messageMetadata"]


def conv_row(env, cid):
    return env.conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()


def run_row(env, loop="evening_checkin"):
    return env.conn.execute("SELECT * FROM runs WHERE loop = ? ORDER BY id DESC", (loop,)).fetchone()


async def evening_env(tmp_path, script, **kw):
    """10/26 17:30 저녁 체크인을 텔레그램으로 보낸 BE(`script[0]`이 회차 두뇌 호출)."""
    return BeEnv.start(tmp_path, start=EVENING, script=script, **kw)


# --- 7.1: 통로마다 따로 ---


async def test_telegram_chat_and_app_chat_do_not_continue(tmp_path):
    script = [FakeTurn([], "텔레 답"), FakeTurn([], "앱 답"), FakeTurn([], "텔레 둘"), FakeTurn([], "앱 둘")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 13, 0), script=script) as env:
        await env.telegram("꾸민 인사")
        env.clock.advance(timedelta(minutes=5))
        _, raw = await env.chat("꾸민 앱 인사")
        app_id = start_meta(raw)["conversation_id"]
        env.clock.advance(timedelta(minutes=5))
        await env.telegram("꾸민 둘째 인사")
        env.clock.advance(timedelta(minutes=5))
        tele_id = env.brain.calls[0]["run_ctx"].conversation_id
        # 앱이 텔레그램 대화 id를 보내도 잇지 않는다
        _, raw2 = await env.chat("꾸민 앱 둘째", conversation_id=tele_id)
        calls = [c["run_ctx"].conversation_id for c in env.brain.calls]
        channels = {cid: conv_row(env, cid)["channel"] for cid in set(calls)}

    assert calls == [tele_id, app_id, tele_id, app_id]
    assert start_meta(raw2)["conversation_id"] == app_id
    assert channels == {tele_id: "telegram", app_id: "app"}
    assert env.brain.session_ids == [None, None, "s1", "s1"]  # 세션도 통로마다 따로


async def test_plan_is_per_channel_but_runs_wait_for_any(tmp_path):
    script = [FakeTurn([], "계획을 세워 봐요"), FakeTurn([], "텔레 답")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 17, 0), script=script) as env:
        _, raw = await env.chat("/plan 꾸민 주제")
        plan_id = start_meta(raw)["conversation_id"]
        env.clock.advance(timedelta(minutes=10))
        await env.telegram("꾸민 텔레 메시지")  # 텔레그램은 앱의 계획 대화를 잇지 않는다
        tele_id = env.brain.calls[1]["run_ctx"].conversation_id
        env.clock.set(EVENING)
        await env.tick()  # 앱 통로의 계획 대화가 열려 있으니 17:30 회차는 기다린다
        run = run_row(env)
        calls = len(env.brain.calls)
        kinds = (conv_row(env, plan_id)["kind"], conv_row(env, plan_id)["channel"], conv_row(env, tele_id)["kind"])

    assert kinds == ("plan", "app", "chat")
    assert run is not None and run["status"] == "pending"
    assert calls == 2  # 회차 두뇌 호출은 없다


# --- 7.2: 가르기 ---


async def test_run_reply_from_other_channel_forks(tmp_path):
    script = [
        FakeTurn([], RUN_TEXT, session_id="s-run"),
        FakeTurn([], "앱에서 이어 가요", session_id="s-fork"),
        FakeTurn([], "앱 둘째 답", session_id="s-fork"),
        FakeTurn([], "텔레 답", session_id="s-run"),
    ]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        tele_run = env.brain.calls[0]["run_ctx"].conversation_id
        env.clock.set(kst(2026, 10, 26, 18, 0))
        _, raw = await env.chat("꾸민 앱 답")
        fork_id = start_meta(raw)["conversation_id"]
        env.clock.advance(timedelta(minutes=5))
        await env.chat("꾸민 앱 둘째", conversation_id=fork_id)
        env.clock.advance(timedelta(minutes=5))
        await env.telegram("꾸민 텔레 답")
        fork = conv_row(env, fork_id)
        run = run_row(env)
        sessions = env.brain.session_ids
        forks = env.brain.forks
        conv_ids = [c["run_ctx"].conversation_id for c in env.brain.calls]
        origin_session = conv_row(env, tele_run)["session_id"]

    assert start_meta(raw)["kind"] == "run"
    assert (fork["kind"], fork["channel"], fork["run_id"], fork["forked_from"]) == ("run", "app", run["id"], tele_run)
    assert fork["session_id"] == "s-fork"
    assert sessions == [None, "s-run", "s-fork", "s-run"]
    assert forks == [False, True, False, False]  # 두 번째 앱 답은 갈라 얻은 세션을 그대로 잇는다
    assert conv_ids == [tele_run, fork_id, fork_id, tele_run]
    assert origin_session == "s-run"  # 원래 대화의 세션은 그대로


async def test_fork_failure_falls_back_with_outbound_text(tmp_path, caplog):
    script = [
        FakeTurn([], RUN_TEXT, session_id="s-run"),
        FakeTurn([], "", status="error", session_id=None, resume_failed=True),
        FakeTurn([], "새 세션으로 답해요", session_id="s-new"),
    ]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 18, 0))
        with caplog.at_level(logging.WARNING):
            _, raw = await env.chat("꾸민 앱 답")
        fork = conv_row(env, start_meta(raw)["conversation_id"])
        calls = env.brain.calls

    assert [(c["session_id"], c["fork_session"]) for c in calls[1:]] == [("s-run", True), (None, False)]
    assert f"## 회차 메시지\n{RUN_TEXT}" in calls[2]["prompt"]
    assert "## 메시지\n꾸민 앱 답" in calls[2]["prompt"]
    assert "## 회차 메시지" not in calls[1]["prompt"]  # 갈라 이을 때는 세션이 회차를 안다
    assert fork["session_id"] == "s-new"
    assert "fork_session_failed" in caplog.text
    assert "꾸민 앱 답" not in caplog.text and RUN_TEXT not in caplog.text


async def test_checkin_id_within_window_targets_run(tmp_path):
    script = [FakeTurn([], RUN_TEXT, session_id="s-run"), FakeTurn([], "계획 답"), FakeTurn([], "회차 답")]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        run = run_row(env)
        env.clock.set(kst(2026, 10, 26, 17, 40))
        _, raw_plan = await env.chat("/plan 꾸민 주제")
        plan_id = start_meta(raw_plan)["conversation_id"]
        env.clock.set(kst(2026, 10, 26, 18, 0))
        # 규칙 1이 계획 대화(규칙 2)보다 먼저다
        _, raw = await env.chat("꾸민 체크인 답", conversation_id=plan_id, checkin_id=run["id"])
        meta = start_meta(raw)
        target = conv_row(env, meta["conversation_id"])

    assert meta["kind"] == "run" and meta["checkin_id"] == run["id"]
    assert (target["run_id"], target["channel"]) == (run["id"], "app")
    assert target["id"] != plan_id
    assert env.brain.forks[-1] is True


async def test_checkin_id_outside_window_falls_through_to_rule_2(tmp_path):
    # 월요일 09:00 아침 브리핑(답장 창 12:00까지). 13:00에 앱 계획 대화를 열고 아침 회차로 답한다
    script = [FakeTurn([], "좋은 아침이에요", session_id="s-run"), FakeTurn([], "계획 답"), FakeTurn([], "계획 둘")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), script=script) as env:
        await env.tick()
        morning = run_row(env, "morning_brief")
        env.clock.set(kst(2026, 10, 26, 13, 0))
        _, raw_plan = await env.chat("/plan 꾸민 주제")
        plan_id = start_meta(raw_plan)["conversation_id"]
        env.clock.advance(timedelta(minutes=10))
        _, raw = await env.chat("꾸민 늦은 답", checkin_id=morning["id"])
        meta = start_meta(raw)
        run_after = run_row(env, "morning_brief")

    assert meta["conversation_id"] == plan_id and meta["kind"] == "plan"
    assert env.brain.forks == [False, False, False]
    assert run_after["answered_at"] is None  # 창 밖이라 답이 아니다


async def test_other_channel_notice_max_5_lines(tmp_path):
    script = [FakeTurn([], "텔레 답"), FakeTurn([], "텔레 둘"), FakeTurn([], "텔레 셋")]
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 13, 0), script=script) as env:
        await env.telegram("꾸민 인사")
        env.clock.advance(timedelta(minutes=5))
        for n in range(1, 7):  # 앱에서 할 일 여섯 개(활동 여섯 줄)
            status, _ = await env.action("add_task", {"title": f"꾸민 일 {n}", "areas": ["health"]})
            assert status == 200
        env.clock.advance(timedelta(minutes=5))
        await env.telegram("꾸민 둘째")
        env.clock.advance(timedelta(minutes=5))
        await env.telegram("꾸민 셋째")  # 그 뒤로 앱에서 바뀐 것이 없다
        prompts = env.brain.prompts

    assert "다른 곳에서 바뀐 것" not in prompts[0]
    section = prompts[1].split("## 다른 곳에서 바뀐 것\n", 1)[1].split("\n\n", 1)[0]
    assert section.splitlines() == [f"- ✓ 추가: 꾸민 일 {n}" for n in range(2, 7)]  # 최근 5줄, 시간순
    assert "다른 곳에서 바뀐 것" not in prompts[2]


# --- 6.4.5: 답한 회차 ---


async def test_answered_once_first_channel_wins(tmp_path):
    script = [FakeTurn([], RUN_TEXT, session_id="s-run"), FakeTurn([], "앱 답"), FakeTurn([], "텔레 답")]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 18, 0))
        await env.chat("꾸민 앱 답")
        first = run_row(env)
        env.clock.set(kst(2026, 10, 26, 18, 10))
        await env.telegram("꾸민 텔레 답")
        after = run_row(env)

    assert (first["answered_via"], first["answered_at"]) == ("app", "2026-10-26T09:00:00.000000+00:00")
    assert (after["answered_via"], after["answered_at"]) == (first["answered_via"], first["answered_at"])


async def test_answer_clears_telegram_buttons(tmp_path, caplog):
    script = [FakeTurn([], RUN_TEXT, session_id="s-run"), FakeTurn([], "앱 답"), FakeTurn([], "텔레 답")]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()  # 저녁 체크인에는 컨디션 버튼이 붙는다
        (mid,) = [m for m in env.sender.message_ids if m is not None]
        stored = env.parts.deliveries.telegram_message_id(run_row(env)["id"])
        env.clock.set(kst(2026, 10, 26, 18, 0))
        await env.chat("꾸민 앱 답")
        cleared = list(env.sender.cleared)
        env.clock.set(kst(2026, 10, 26, 18, 10))
        await env.telegram("꾸민 텔레 답")  # 이미 답했다: 다시 거두지 않는다

    assert stored == mid
    assert cleared == [mid]
    assert env.sender.cleared == [mid]
    assert "buttons_clear_error" not in caplog.text


async def test_buttons_clear_failure_only_logs(tmp_path, caplog):
    script = [FakeTurn([], RUN_TEXT, session_id="s-run"), FakeTurn([], "앱 답")]
    async with await evening_env(tmp_path, script) as env:
        env.sender.clear_fail = True
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 18, 0))
        with caplog.at_level(logging.WARNING):
            resp, raw = await env.chat("꾸민 앱 답")
            await env.drain()
        run = run_row(env)

    assert run["answered_via"] == "app"
    assert resp.status == 200 and "앱 답" in "".join(c.get("delta", "") for c in parse_sse(raw))
    assert env.sender.cleared == []
    assert "buttons_clear_error" in caplog.text


async def test_telegram_reply_keeps_buttons(tmp_path):
    """Dahun 결정: 텔레그램 글 답장은 SP1처럼 버튼을 그대로 둔다(거두는 것은 앱에서 먼저 답했을 때만)."""
    script = [FakeTurn([], RUN_TEXT, session_id="s-run"), FakeTurn([], "텔레 답"), FakeTurn([], "앱 답")]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 18, 0))
        await env.telegram("꾸민 텔레 답")
        first = run_row(env)
        env.clock.set(kst(2026, 10, 26, 18, 10))
        await env.chat("꾸민 앱 답")  # 첫 답이 아니므로 거두지 않는다
        await env.drain()
        final = run_row(env)

    assert final["answered_via"] == "telegram"
    assert first["answered_via"] == "telegram"
    assert env.sender.cleared == []


async def test_condition_action_answers_evening_checkin(tmp_path):
    async with await evening_env(tmp_path, [FakeTurn([], RUN_TEXT)]) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 18, 0))
        # 다른 날짜의 컨디션은 이 저녁 체크인의 답이 아니다
        await env.action("record_condition", {"score": 3, "date": "2026-10-25"})
        before = run_row(env)
        status, body = await env.action("record_condition", {"score": 4, "date": "2026-10-26"})
        await env.drain()
        run = run_row(env)
        detail = await (await env.get(f"/checkins/{run['id']}")).json()

    assert before["answered_at"] is None
    assert status == 200 and body["status"] == "applied"
    assert run["answered_via"] == "app"
    assert (detail["state"], detail["answered_via"]) == ("answered", "app")
    assert len(env.sender.cleared) == 1
    assert all(c["component"] != "ui_condition_picker" for c in detail["cards"])


async def test_draft_button_answers_its_run(tmp_path):
    propose = ("propose_tasks", {"tasks": [{"title": "꾸민 초안", "areas": ["health"]}]})
    async with await evening_env(tmp_path, [FakeTurn([propose], RUN_TEXT)]) as env:
        await env.tick()
        (task,) = env.conn.execute("SELECT id FROM tasks").fetchall()
        mid = env.parts.deliveries.telegram_message_id(run_row(env)["id"])
        env.clock.set(kst(2026, 10, 26, 18, 0))
        result = await env.press(f"d:c:{task['id']}", message_id=mid)
        await env.drain()
        run = run_row(env)

    assert result == "confirmed"
    assert run["answered_via"] == "telegram"
    assert mid is not None and env.sender.cleared == []  # 텔레그램 버튼 누름은 버튼을 그대로 둔다


async def test_condition_button_answers_message_run(tmp_path):
    """아침 브리핑이 물은 어제 컨디션 버튼: 누른 메시지(`run_deliveries.telegram_message_id`)의 회차에 답한다."""
    async with BeEnv.start(
        tmp_path, start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), script=[FakeTurn([], "좋은 아침이에요")]
    ) as env:
        await env.tick()
        morning = run_row(env, "morning_brief")
        mid = env.parts.deliveries.telegram_message_id(morning["id"])
        assert env.sender.sent[0].ask_condition_for.isoformat() == "2026-10-25"
        env.clock.set(kst(2026, 10, 26, 9, 30))
        result = await env.press("c:2026-10-25:4", message_id=mid)
        await env.drain()
        after = run_row(env, "morning_brief")
        found = env.parts.deliveries.run_for_message(mid)

    assert result == "recorded"
    assert after["answered_via"] == "telegram"
    assert found == morning["id"]


async def test_condition_recorded_before_brief_is_not_its_answer(tmp_path):
    """보낼 때 어제 컨디션이 이미 있었으면 아침 브리핑에는 컨디션 버튼이 없다: 다시 기록해도 그 브리핑의 답이 아니다."""
    async with BeEnv.start(
        tmp_path, start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30), script=[FakeTurn([], "좋은 아침이에요")]
    ) as env:
        await env.action("record_condition", {"score": 3, "date": "2026-10-25"})
        await env.tick()
        assert env.sender.sent[0].ask_condition_for is None
        env.clock.set(kst(2026, 10, 26, 9, 30))
        status, _ = await env.action("record_condition", {"score": 4, "date": "2026-10-25"})
        morning = run_row(env, "morning_brief")

    assert status == 200
    assert morning["answered_at"] is None


async def test_late_reply_by_sent_at(tmp_path):
    script = [FakeTurn([], RUN_TEXT, session_id="s-run"), FakeTurn([], "늦게 받았어요")]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        tele_run = env.brain.calls[0]["run_ctx"].conversation_id
        env.clock.set(kst(2026, 10, 27, 5, 0))  # 노트북이 잠든 동안 03:50에 보낸 답을 05:00에 받는다
        await env.telegram("꾸민 새벽 답", sent_at=kst(2026, 10, 27, 3, 50))
        run = run_row(env)
        listing = await (await env.get("/checkins?date=2026-10-26")).json()

    assert env.brain.calls[1]["run_ctx"].conversation_id == tele_run
    assert run["answered_via"] == "telegram"
    assert run["answered_at"] == "2026-10-26T18:50:00.000000+00:00"  # 보낸 시각
    (item,) = [i for i in listing["items"] if i["loop"] == "evening_checkin"]
    assert item["state"] == "answered"


# --- 05와 06이 만나는 자리 ---


async def test_chat_activity_ids_are_undoable(tmp_path):
    add = ("add_task", {"title": "꾸민 치과", "areas": ["health"], "planned_for": "2026-10-27"})
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 13, 0), script=[FakeTurn([add], "넣었어요")]) as env:
        _, raw = await env.chat("꾸민 할 일 넣어 줘")
        (activity,) = [c for c in parse_sse(raw) if c["type"] == "data-activity"]
        (undo_id,) = activity["data"]["undo_ids"]
        resp = await env.post(f"/activity/{undo_id}/undo", json={"client_msg_id": "cm-undo-1"})
        body = await resp.json()
        deleted = env.conn.execute("SELECT deleted_at FROM tasks").fetchone()["deleted_at"]

    assert resp.status == 200 and body["status"] == "undone" and body["undone"] == undo_id
    assert deleted is not None  # 추가 되돌리기는 소프트 삭제


# --- fix1: 같은 세션 id, 원래 대화만 보는 규칙 3, 갓 가른 대화의 알림 기준 ---


async def test_fork_returning_original_session_falls_back(tmp_path, caplog):
    """가르기가 원래 세션 id를 돌려주면 가르기 실패다: 그 세션을 적지 않고 바로 대체 경로(새 세션)로 다시 부른다."""
    script = [
        FakeTurn([], RUN_TEXT, session_id="s-run"),
        FakeTurn([], "텔레 답", session_id="s-run"),
        FakeTurn([], "갈라지지 않은 답", session_id="s-run"),
        FakeTurn([], "대체 경로 답", session_id="s-new"),
        FakeTurn([], "앱 둘째 답", session_id="s-new"),
    ]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 17, 45))
        await env.telegram("꾸민 텔레 먼저")
        env.clock.set(kst(2026, 10, 26, 18, 0))
        with caplog.at_level(logging.WARNING):
            _, raw = await env.chat("꾸민 앱 답")
        fork_id = start_meta(raw)["conversation_id"]
        env.clock.advance(timedelta(minutes=5))
        await env.chat("꾸민 앱 둘째", conversation_id=fork_id)
        fork = conv_row(env, fork_id)
        calls = env.brain.calls
        text = "".join(c.get("delta", "") for c in parse_sse(raw))

    assert [(c["session_id"], c["fork_session"]) for c in calls[2:]] == [
        ("s-run", True), (None, False), ("s-new", False),
    ]
    fallback = calls[3]["prompt"]
    assert f"## 회차 메시지\n{RUN_TEXT}" in fallback
    # 대체 경로의 최근 원문은 원래(텔레그램) 대화의 기록이다(S11): 회차 본문과 텔레그램에서 주고받은 답
    history = fallback.split("## 최근 대화\n", 1)[1]
    assert "꾸민 텔레 먼저" in history and "텔레 답" in history
    assert fork["session_id"] == "s-new"
    assert text == "대체 경로 답"
    assert "fork_session_not_forked" in caplog.text


async def test_fork_failure_history_uses_origin_transcript(tmp_path):
    """resume 실패로 끝난 가르기도 원래 대화의 최근 원문을 붙인다(S11 대체 경로)."""
    script = [
        FakeTurn([], RUN_TEXT, session_id="s-run"),
        FakeTurn([], "텔레 답", session_id="s-run"),
        FakeTurn([], "", status="error", session_id=None, resume_failed=True),
        FakeTurn([], "새 세션 답", session_id="s-new"),
    ]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 17, 45))
        await env.telegram("꾸민 텔레 먼저")
        env.clock.set(kst(2026, 10, 26, 18, 0))
        await env.chat("꾸민 앱 답")
        prompt = env.brain.calls[3]["prompt"]

    history = prompt.split("## 최근 대화\n", 1)[1].split("\n\n## 메시지", 1)[0]
    assert RUN_TEXT in history and "꾸민 텔레 먼저" in history and "텔레 답" in history
    assert history.count("꾸민 앱 답") == 0  # 지금 메시지는 `## 메시지`에만
    assert "## 메시지\n꾸민 앱 답" in prompt


async def test_rule_3_ignores_newer_fork_of_older_run(tmp_path):
    """규칙 3은 원래 회차 대화만 본다: 더 오래된 회차를 앱에서 갈라 연 대화가 새 회차의 텔레그램 답을 가져가지 않는다."""
    from my_planner.domain import LoopKey

    async with BeEnv.start(tmp_path, start=kst(2026, 10, 26, 17, 30)) as env:
        p = env.parts
        older = p.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 26, 17, 30))
        older_conv = p.router.for_run(older)
        p.runs.set_conversation(older.id, older_conv.id)
        p.runs.mark_done(older.id)
        env.clock.set(kst(2026, 10, 26, 20, 0))
        newer = p.runs.ensure(LoopKey.return_, kst(2026, 10, 26, 20, 0))
        newer_conv = p.router.for_run(newer)
        p.runs.set_conversation(newer.id, newer_conv.id)
        p.runs.mark_done(newer.id)
        env.clock.set(kst(2026, 10, 26, 21, 0))
        fork = p.dispatcher.route_app_message(env.clock.now(), conversation_id=None, checkin_id=older.id)
        env.clock.set(kst(2026, 10, 26, 21, 10))
        target = p.router.for_user_message(env.clock.now(), sent_at=env.clock.now())

    assert (fork.run_id, fork.channel, fork.forked_from) == (older.id, "app", older_conv.id)
    assert target.id == newer_conv.id


async def test_fresh_fork_notices_changes_since_run_sent(tmp_path):
    """갓 가른 대화의 첫 호출은 회차를 보낸 때부터 다른 통로 변경을 본다(가른 시각부터가 아니다)."""
    script = [FakeTurn([], RUN_TEXT, session_id="s-run"), FakeTurn([], "앱 답", session_id="s-fork")]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        mid = env.parts.deliveries.telegram_message_id(run_row(env)["id"])
        env.clock.set(kst(2026, 10, 26, 17, 45))
        assert await env.press("c:2026-10-26:4", message_id=mid) == "recorded"  # 세션 밖(버튼)의 변경
        env.clock.set(kst(2026, 10, 26, 18, 0))
        (pressed,) = [r for r in env.activity() if r["channel"] == "telegram"]
        await env.chat("꾸민 앱 답")
        prompt = env.brain.calls[1]["prompt"]

    section = prompt.split("## 다른 곳에서 바뀐 것\n", 1)[1].split("\n\n", 1)[0]
    assert section.splitlines() == [f"- {pressed['summary']}"]


async def test_answer_record_failure_keeps_committed_action(tmp_path, caplog):
    """답 표시가 예외를 올려도 이미 커밋한 동작은 그대로 200이다(리뷰 Minor 2)."""
    async with await evening_env(tmp_path, [FakeTurn([], RUN_TEXT)]) as env:
        await env.tick()

        def boom(run_id, channel, **kw):
            raise RuntimeError("fake answer failure")

        env.parts.dispatcher.mark_answered = boom
        env.clock.set(kst(2026, 10, 26, 18, 0))
        with caplog.at_level(logging.WARNING):
            status, body = await env.action("record_condition", {"score": 4, "date": "2026-10-26"})
        score = env.conn.execute("SELECT score FROM conditions WHERE date = '2026-10-26'").fetchone()["score"]

    assert status == 200 and body["status"] == "applied"
    assert score == 4
    assert "action_answer_record_error" in caplog.text and "action_failed" not in caplog.text


# --- fix2 ---


async def test_streamed_not_forked_answer_is_kept_and_next_message_falls_back(tmp_path):
    """같은 id를 돌려준 가르기가 이미 글을 스트리밍했으면 그 답을 그대로 둔다(답 둘 방지). 다음 메시지부터 대체 경로."""
    script = [
        FakeTurn([], RUN_TEXT, session_id="s-run"),
        FakeTurn([], "갈라지지 않은 답", session_id="s-run", deltas=["갈라지지 ", "않은 답"]),
        FakeTurn([], "대체 경로 답", session_id="s-new"),
    ]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 18, 0))
        _, raw = await env.chat("꾸민 앱 답")
        fork_id = start_meta(raw)["conversation_id"]
        after_first = len(env.brain.calls)
        fork_before = conv_row(env, fork_id)["session_id"]
        stored = env.parts.idempotency.get(env.conn.execute(
            "SELECT client_msg_id FROM api_idempotency ORDER BY rowid DESC LIMIT 1").fetchone()[0])
        env.clock.advance(timedelta(minutes=5))
        await env.chat("꾸민 앱 둘째", conversation_id=fork_id)
        fork_after = conv_row(env, fork_id)["session_id"]
        calls = env.brain.calls
        chunks = parse_sse(raw)

    assert after_first == 2  # 대체 호출을 더 하지 않았다
    assert "".join(c["delta"] for c in chunks if c["type"] == "text-delta") == "갈라지지 않은 답"
    assert sum(1 for c in chunks if c["type"] == "text-start") == 1
    assert stored.body["reply_text"] == "갈라지지 않은 답"
    assert fork_before is None  # 원래 세션 id는 적지 않는다
    assert (calls[2]["session_id"], calls[2]["fork_session"]) == (None, False)
    assert f"## 회차 메시지\n{RUN_TEXT}" in calls[2]["prompt"]
    assert fork_after == "s-new"


async def test_fork_error_retries_and_keeps_forking(tmp_path):
    """가르기 호출의 오류(원래 id가 돌아와도)는 가르기 실패가 아니다: 2/4/8초 재시도가 다시 가른다."""
    script = [
        FakeTurn([], RUN_TEXT, session_id="s-run"),
        FakeTurn([], "", status="error", session_id="s-run"),
        FakeTurn([], "다시 갈라 답해요", session_id="s-fork"),
    ]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        env.clock.set(kst(2026, 10, 26, 18, 0))
        _, raw = await env.chat("꾸민 앱 답")
        fork = conv_row(env, start_meta(raw)["conversation_id"])
        calls = [(c["session_id"], c["fork_session"]) for c in env.brain.calls[1:]]
        no_fork = set(env.parts.dispatcher._no_fork)

    assert calls == [("s-run", True), ("s-run", True)]
    assert fork["session_id"] == "s-fork"
    assert no_fork == set()


async def test_fork_fallback_history_is_20_lines_total(tmp_path):
    """대체 경로의 원문은 합쳐 20개: 갈라 연 대화의 것을 먼저, 남는 자리를 원래 대화의 최근 것으로(S11)."""
    script = [
        FakeTurn([], RUN_TEXT, session_id="s-run"),
        FakeTurn([], "앱 첫 답", session_id="s-fork"),
        FakeTurn([], "", status="error", session_id=None, resume_failed=True),
        FakeTurn([], "새 세션 답", session_id="s-new"),
    ]
    async with await evening_env(tmp_path, script) as env:
        await env.tick()
        origin = env.brain.calls[0]["run_ctx"].conversation_id
        for n in range(25):  # 원래 대화의 꾸민 원문 25줄
            env.parts.transcripts.append(env.clock.now(), "사용자", origin, None, f"꾸민 줄 {n}")
        env.clock.set(kst(2026, 10, 26, 18, 0))
        _, raw = await env.chat("꾸민 앱 첫")
        env.clock.advance(timedelta(minutes=5))
        await env.chat("꾸민 앱 둘째", conversation_id=start_meta(raw)["conversation_id"])
        prompt = env.brain.calls[3]["prompt"]

    history = prompt.split("## 최근 대화\n", 1)[1].split("\n\n## 메시지", 1)[0].splitlines()
    assert len(history) == 20
    assert history[0].endswith("꾸민 줄 7") and history[17].endswith("꾸민 줄 24")
    assert history[18].endswith("꾸민 앱 첫") and history[19].endswith("앱 첫 답")

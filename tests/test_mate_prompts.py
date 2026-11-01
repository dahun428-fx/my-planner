"""메이트 차례의 지시문·프롬프트 조각·도구 목록 (SP12 스펙 5.3, 5.4). 비서 쪽은 바이트까지 그대로다.

디스패처 쪽은 가짜 두뇌 + 가짜 시계(`BeEnv`)에 `Inbound`를 바로 넣는다(`POST /chat`의 상대 받기는 Task 5).
"""

from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn, ListSink
from test_brain_options import _capture_build
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.harness.brain import ClaudeBrain
from my_planner.harness.dispatcher import Inbound
from my_planner.tools.mcp_adapter import MATE_TOOLS, MOMENTS_TOOLS, tool_names_for

START = kst(2026, 10, 31, 19, 0)
DENTIST = ("add_task", {"title": "치과", "areas": ["health"], "planned_for": "2026-11-01"})
BANNED = ("연속", "스트릭", "달성률", "%")


def app_message(env, text, cmid, *, agent="secretary", sink=None):
    """`POST /chat`이 하는 것처럼: 받을 때 그 상대의 대화를 고르고, 가린 글을 먼저 저장한 뒤의 `Inbound`."""
    d = env.parts.dispatcher
    now = env.clock.now()
    conv = d.route_app_message(now, conversation_id=None, checkin_id=None, agent=agent)
    iid = d.state.next_app_inbound_id()
    d.state.add_pending_inbound(
        iid, text, now, now, channel="app", client_msg_id=cmid, conversation_id=conv.id, agent=agent,
    )
    return Inbound(
        text=text, at=now, sent_at=now, update_ids=[iid], channel="app", client_msg_id=cmid,
        sink=sink if sink is not None else ListSink(), conversation_id=conv.id, agent=agent,
    )


def telegram_message(env, text, update_id):
    now = env.clock.now()
    env.parts.state.add_pending_inbound(update_id, text, now, now)
    return Inbound(text=text, at=now, sent_at=now, update_ids=[update_id])


def test_secretary_app_prompt_unchanged(tmp_path):
    brain = ClaudeBrain(lambda: None, tmp_path / "wd", max_turns=10)
    assert brain.system_prompt_for("app") == prompts.load("system.md") + "\n\n" + prompts.load("channel_app.md").strip()
    assert brain.system_prompt_for("telegram") == prompts.load("system.md")
    assert brain.system_prompt_for("app", "mate") == prompts.load("mate.md")


def test_mate_prompt_text_rules():
    text = prompts.load("mate.md")
    for word in BANNED:
        assert word not in text, word
    for name in ("ui_block", "ui_choice", "ui_summary_card", "`send`", "`open`"):
        assert name in text, name
    assert "두 개까지" in text and "비서" in text
    assert "complete" not in text and "pin_card" not in text


async def test_run_passes_mate_prompt(tmp_path, monkeypatch):
    brain, seen, _ = _capture_build(monkeypatch, tmp_path)
    await brain.run("안녕", session_id=None, run_ctx=RunContext(1, None, agent="mate", channel="app"))
    await brain.run("안녕", session_id=None, run_ctx=RunContext(2, None, channel="app"))
    assert seen[0]["system_prompt"] == prompts.load("mate.md")
    assert seen[1]["system_prompt"] == brain.system_prompt_for("app")


def test_mate_tool_list():
    assert tool_names_for(RunContext(None, None, agent="mate", channel="app")) == MATE_TOOLS
    assert MATE_TOOLS == [
        "get_mate_context", "save_body_note", "drop_body_note", "set_workout_plan", "log_workout",
        "update_workout_log", "delete_workout_log", "list_workouts",
        "record_condition", "find_conversations", "ui_block", "ui_choice", "ui_summary_card",
    ]
    assert tool_names_for(RunContext(None, None, kind="summary", agent="mate")) == []
    assert tool_names_for(RunContext(None, None, kind="photo_read", agent="mate")) == []
    assert tool_names_for(RunContext(None, None, kind="moments", agent="mate")) == MOMENTS_TOOLS
    secretary = tool_names_for(RunContext(None, None, channel="app"))
    assert "add_task" in secretary and not set(MATE_TOOLS[:8]) & set(secretary)  # 운동 도구는 메이트에만(5.3)
    assert set(MATE_TOOLS[8:]) <= set(secretary)


async def test_mate_prompt_parts(tmp_path):
    """메이트 첫 프롬프트: `chat.md` 없음, 비서 앞머리 없음, 기록된 컨디션 있음. 매 호출 `## 다른 곳에서 바뀐 것` 없음."""
    script = [FakeTurn([], f"답 {i}", session_id=f"s{i}") for i in range(5)]
    script[2] = FakeTurn([DENTIST], "넣었어요.", session_id="s2")
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        p = env.parts
        p.conditions.upsert(START.date(), 2, None)
        d = p.dispatcher
        d.submit_message(app_message(env, "비서 첫 말", "cm-s1"))
        await env.drain()
        d.submit_message(app_message(env, "오늘 뭐 할까?", "cm-m1", agent="mate"))
        await env.drain()
        env.clock.advance(timedelta(minutes=2))
        d.submit_message(telegram_message(env, "내일 치과", 701))  # 다른 통로의 변경
        await env.drain()
        env.clock.advance(timedelta(minutes=2))
        d.submit_message(app_message(env, "비서 둘째 말", "cm-s2"))
        await env.drain()
        d.submit_message(app_message(env, "가볍게 할래", "cm-m2", agent="mate"))
        await env.drain()
        calls = env.brain.calls
        convs = {r["id"]: r["agent"] for r in env.conn.execute("SELECT id, agent FROM conversations")}

    chat_first = prompts.load("chat.md").splitlines()[0]
    sec1, mate1, _, sec2, mate2 = calls
    assert chat_first in sec1["prompt"] and chat_first not in mate1["prompt"]
    assert "## 기록된 컨디션" in mate1["prompt"] and "2/5" in mate1["prompt"]
    assert "## 기록된 컨디션" in mate2["prompt"]
    assert "## 지금\n" in sec1["prompt"] and "## 지금\n" not in mate1["prompt"]  # 비서 앞머리 대신 메이트 앞머리(5.5)
    assert "## 오늘\n2026-10-31 (토), 논리적 날짜" in mate1["prompt"] and "## 지금 플랜\n아직 없음" in mate1["prompt"]
    assert "- 컨디션: 2" in mate1["prompt"] and "## 몸 메모" not in mate2["prompt"]  # 이어진 세션에는 앞머리 없음
    assert "## 다른 곳에서 바뀐 것" in sec2["prompt"]  # 비서는 그대로
    assert "## 다른 곳에서 바뀐 것" not in mate2["prompt"]
    assert [c["run_ctx"].agent for c in calls] == ["secretary", "mate", "secretary", "secretary", "mate"]
    assert convs[mate1["run_ctx"].conversation_id] == "mate" and convs[sec1["run_ctx"].conversation_id] == "secretary"
    assert mate2["session_id"] == "s1"  # 메이트 대화는 메이트 세션을 잇는다


async def test_mate_reply_transcribed_as_mate(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "가볍게 걸어요")]) as env:
        msg = app_message(env, "오늘 뭐 할까?", "cm-t1", agent="mate")
        env.parts.dispatcher.submit_message(msg)
        await env.drain()
        lines = env.parts.transcripts.messages(msg.conversation_id)
        day = env.parts.transcripts.path_for(START).read_text(encoding="utf-8")

    assert [(m.speaker, m.text) for m in lines] == [("사용자", "오늘 뭐 할까?"), ("운동메이트", "가볍게 걸어요")]
    heads = [line for line in day.splitlines() if line.startswith("### ")]
    assert all(h.endswith(" @app @mate") for h in heads) and len(heads) == 2


def test_mate_texts_have_no_banned_words():
    """`mate.md`(금지어 목록 블록 밖), 메이트 칩 지시문, 부록 A 문구에 앱 금지어·비율·"빠진"이 없다(전역 제약)."""
    import re

    from my_planner.tools import workout
    from my_planner.tools.confirmations import (
        confirm_workout_log_delete_summary,
        workout_line,
    )
    from my_planner.tools.ui import APP_BANNED_WORDS

    block = re.compile(r"<!-- banned-words:start -->.*?<!-- banned-words:end -->", re.DOTALL)
    texts = [block.sub("", prompts.load("mate.md"))]
    texts += [prompts.load(f"chip_mate_{k}.md") for k in ("today", "log", "plan")]
    texts += [workout.MSG_NOTES_FULL, workout.MSG_LOG_RANGE, confirm_workout_log_delete_summary("하체", START.date())]
    texts += [workout_line(k, {"title": "하체", "cleared": c}) for k, c in (
        ("workout_plan_set", False), ("workout_plan_set", True), ("workout_logged", False),
        ("workout_log_updated", False), ("body_note_dropped", False),
    )]
    for text in texts:
        for word in (*APP_BANNED_WORDS, "%", "빠진"):
            assert word not in text, (word, text)


def test_mate_banned_block_matches_system():
    """`mate.md`의 금지어 목록은 `system.md`의 블록 그대로다(정본은 `system.md`, `banned_words()`가 읽는다)."""
    import re

    block = re.compile(r"<!-- banned-words:start -->.*?<!-- banned-words:end -->", re.DOTALL)
    assert block.search(prompts.load("mate.md")).group(0) == block.search(prompts.load("system.md")).group(0)


def test_mate_prompt_safety_first():
    """9.4 안전이 맨 앞 "꼭 지킬 것" 묶음에 있다."""
    text = prompts.load("mate.md")
    first = text.index("## ")
    assert text[first:].startswith("## 꼭 지킬 것\n")
    head = text[first:text.index("\n## ", first + 1)]
    for phrase in ("날카로운 통증", "저림", "가슴", "어지럼", "진단"):
        assert phrase in head, phrase


def test_mate_chip_blocks():
    from my_planner.harness.dispatcher import chip_block

    for key in ("today", "log", "plan"):
        assert chip_block(f"mate_{key}") == f"## 버튼\n{prompts.load(f'chip_mate_{key}.md')}"
    assert prompts.load("chip_common.md") not in chip_block("mate_log")

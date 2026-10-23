import json
import logging

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

NOW = kst(2026, 10, 24, 10, 0)


def _env(tmp_path, conn, state, script, start=NOW):
    return Env(tmp_path, conn, state, script=script, start=start, with_tools=True)


def add(title, **kw):
    return ("add_task", {"title": title, "areas": ["health"], **kw})


async def test_confirmation_add_with_schedule(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([add("치과", scheduled_at="2026-10-25T14:00")], "추가했어요.")])
    await env.process(env.inbound("치과 내일 2시 추가해 줘"))
    assert "✓ 추가: 치과 (10/25 14:00)" in env.sender.sent[0].text


async def test_confirmation_move_to_tomorrow(tmp_path, conn, state):
    from my_planner.domain import RunContext

    env = _env(tmp_path, conn, state, [FakeTurn([("move_task", {"id": 1, "planned_for": "2026-10-25"})], "옮겼어요.")])
    env.tools.add_task(RunContext(None, None), title="운동", areas=["health"])
    await env.process(env.inbound("운동 내일로"))
    assert "✓ 옮김: 운동 → 내일" in env.sender.sent[0].text


async def test_confirmation_move_to_no_date(tmp_path, conn, state):
    from my_planner.domain import RunContext

    env = _env(tmp_path, conn, state, [FakeTurn([("move_task", {"id": 1, "planned_for": None})], "옮겼어요.")])
    env.tools.add_task(RunContext(None, None), title="운동", areas=["health"], planned_for="2026-10-25")
    await env.process(env.inbound("운동 날짜 빼 줘"))
    assert "✓ 옮김: 운동 → 날짜 없음" in env.sender.sent[0].text


async def test_no_tool_calls_no_confirmation_block(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], "안녕하세요.")])
    await env.process(env.inbound("안녕"))
    assert env.sender.sent[0].text == "안녕하세요."


async def test_confirmations_have_no_banned_words(tmp_path, conn, state):
    calls = [
        add("가", planned_for="2026-10-24"),
        add("나", scheduled_at="2026-10-25T09:00"),
        ("update_task", {"id": 1, "note": "메모"}),
        ("move_task", {"id": 1, "planned_for": "2026-11-02"}),
        ("complete_task", {"id": 1}),
        ("reopen_task", {"id": 1}),
        ("drop_task", {"id": 1}),
    ]
    env = _env(tmp_path, conn, state, [FakeTurn(calls, "정리했어요.")])
    await env.process(env.inbound("정리해 줘"))
    text = env.sender.sent[0].text
    for kind in ("추가", "바꿈", "옮김", "완료", "되돌림", "내려놓음"):
        assert f"✓ {kind}:" in text
    assert "→ 11/2" in text and "→ 오늘" in text
    for word in ("놓쳤어요", "밀렸어요", "늦었지만", "실패"):
        assert word not in text


async def test_confirmations_appended_below_reply(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([add("치과", scheduled_at="2026-10-25T14:00")], "추가했어요.")])
    await env.process(env.inbound("치과 추가"))
    assert env.sender.sent[0].text == "추가했어요.\n\n✓ 추가: 치과 (10/25 14:00)"
    day = env.day_file("2026-10-24").read_text(encoding="utf-8")
    assert "> 도구: add_task" in day
    assert day.index("### 10:00 비서") < day.index("> 도구: add_task")


async def test_preamble_lists_at_most_30_open_tasks_in_order(tmp_path, conn, state):
    from my_planner.domain import RunContext

    env = _env(tmp_path, conn, state, [FakeTurn([], "네")])
    c = RunContext(None, None)
    for i in range(33):
        env.tools.add_task(c, title=f"나중{i:02d}", areas=["career"], planned_for="2026-12-01")
    env.tools.add_task(c, title="이번주일", areas=["career"], planned_for="2026-10-26")
    env.tools.add_task(c, title="오늘일", areas=["career"], planned_for="2026-10-24")
    await env.process(env.inbound("안녕"))

    p = env.brain.prompts[0]
    section = p[p.index("## 열린 할 일"):]
    lines = [ln for ln in section.split("\n\n")[0].splitlines()[1:]]
    assert sum(ln.startswith("- #") for ln in lines) == 30
    assert "오늘일" in lines[0] and "이번주일" in lines[1] and "나중00" in lines[2]
    assert "나중27" in section and "나중28" not in section.split("\n\n")[0]
    assert p.index("## 지금") < p.index("## 열린 할 일")


async def test_preamble_today_schedule(tmp_path, conn, state):
    from my_planner.domain import RunContext

    env = _env(tmp_path, conn, state, [FakeTurn([], "네"), FakeTurn([], "네")])
    c = RunContext(None, None)
    env.tools.add_task(c, title="치과", areas=["health"], scheduled_at="2026-10-24T14:00")
    env.tools.add_task(c, title="점심", areas=["quality_of_life"], scheduled_at="2026-10-24T12:00")
    env.tools.add_task(c, title="내일일정", areas=["career"], scheduled_at="2026-10-25T09:00")
    await env.process(env.inbound("안녕", update_id=1))

    p = env.brain.prompts[0]
    sched = p[p.index("## 오늘 일정"):]
    assert sched.index("12:00 점심") < sched.index("14:00 치과") and "내일일정" not in sched
    assert "## 지금\n2026-10-24 (토) 10:00" in p

    await env.process(env.inbound("또", update_id=2))  # 이어지는 세션에는 앞머리가 없다
    assert "## 오늘 일정" not in env.brain.prompts[1]


async def test_max_turns_sends_confirmations_and_fixed_text(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([add("치과")], "", status="max_turns")])
    await env.process(env.inbound("정리해 줘"))
    text = env.sender.sent[0].text
    assert "✓ 추가: 치과" in text
    assert "정리하다가 길어졌어요. 이어서 말씀해 주시면 계속할게요." in text


async def test_brain_call_log_has_tool_names(tmp_path, conn, state):
    from my_planner.logging_setup import setup_logging

    env = _env(tmp_path, conn, state, [FakeTurn([add("비밀스러운제목")], "네")])
    log_path = setup_logging(env.settings.paths.state_dir, 30)
    await env.process(env.inbound("추가"))
    for h in logging.getLogger().handlers:
        h.flush()
    raw = log_path.read_text(encoding="utf-8")
    calls = [e for e in map(json.loads, raw.splitlines()) if e.get("msg") == "brain_call"]
    assert calls[0]["tool_names"] == ["add_task"]
    assert "비밀스러운제목" not in raw

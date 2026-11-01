"""셋째 대화 상대 라이프 매니저(`agent="manager"`, SP15 계획 Task 3): 앱 `/chat`으로 비서·메이트와 따로 돈다.

`BeEnv`(가짜 두뇌)로 앱 `/chat`을 보낸다. 원문 기록 꼬리표는 ` @manager`이고, 비서의 `read_transcript`는 그 줄을
읽지 않는다(스펙 13장).
"""

from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_api_read import get_json
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.harness.brain import ClaudeBrain

START = kst(2026, 11, 1, 14, 0)  # 일요일 오후


def _cid(resp) -> int:
    return int(resp.headers["x-conversation-id"])


def _ids(body) -> list[int]:
    return [i["id"] for i in body["items"]]


async def test_manager_conversation_separate_list(tmp_path):
    """비서·메이트·매니저에게 한 번씩: 매니저 목록에는 매니저 대화 하나뿐이고 다른 둘의 목록에는 없다(T1, 1장 1)."""
    script = [FakeTurn([], "네"), FakeTurn([], "좋아요"), FakeTurn([], "이번 주는 하나만 봐요.")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        sec, _ = await env.chat("비서에게")
        mate, _ = await env.chat("메이트에게", agent="mate")
        man, _ = await env.chat("매니저에게", agent="manager")
        managers = await get_json(env, "/conversations?agent=manager")
        secretaries = await get_json(env, "/conversations?agent=secretary")
        mates = await get_json(env, "/conversations?agent=mate")
        call = env.brain.calls[2]
    assert _ids(managers) == [_cid(man)]
    assert _cid(man) not in _ids(secretaries) + _ids(mates)
    assert _ids(secretaries) == [_cid(sec)] and _ids(mates) == [_cid(mate)]
    ctx = call["run_ctx"]
    assert ctx.agent == "manager"
    brain = ClaudeBrain(lambda: None, tmp_path / "wd", max_turns=10)
    assert brain.system_prompt_for(ctx.channel, ctx.agent) == prompts.load("manager.md")
    # 매니저 차례에는 비서의 대화 지시문(`chat.md`)을 붙이지 않는다(규칙은 모두 `manager.md`에)
    assert prompts.load("chat.md").strip() not in call["prompt"]


async def test_manager_30_minute_rule(tmp_path):
    """29분 뒤는 같은 대화, 31분 뒤는 새 대화. 그 사이 비서 메시지는 매니저 대화를 닫거나 잇지 않는다(T1)."""
    script = [FakeTurn([], f"답{i}") for i in range(5)]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        first, _ = await env.chat("하나", agent="manager")
        env.clock.advance(timedelta(minutes=10))
        sec, _ = await env.chat("비서에게")
        env.clock.advance(timedelta(minutes=19))  # 매니저 마지막 뒤 29분
        second, _ = await env.chat("둘", agent="manager")
        env.clock.advance(timedelta(minutes=31))
        third, _ = await env.chat("셋", agent="manager")
        sec_agent = env.conn.execute("SELECT agent FROM conversations WHERE id = ?", (_cid(sec),)).fetchone()[0]
    assert _cid(second) == _cid(first)
    assert _cid(sec) != _cid(first) and sec_agent == "secretary"
    assert _cid(third) not in (_cid(first), _cid(sec))


async def test_resume_other_agent_400(tmp_path):
    """매니저 요청에 메이트 대화 id를 `resume_conversation_id`로 → 400. 반대도 400(T1)."""
    script = [FakeTurn([], "좋아요"), FakeTurn([], "네")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        mate, _ = await env.chat("메이트에게", agent="mate")
        man, _ = await env.chat("매니저에게", agent="manager")
        env.parts.dispatcher.new_conversation("mate")
        env.parts.dispatcher.new_conversation("manager")
        to_manager = await env.post(
            "/chat", json=env.chat_body("이어서", resume_conversation_id=_cid(mate), agent="manager"),
        )
        to_mate = await env.post(
            "/chat", json=env.chat_body("이어서", resume_conversation_id=_cid(man), agent="mate"),
        )
        bodies = [await to_manager.json(), await to_mate.json()]
        calls = len(env.brain.calls)
    assert [to_manager.status, to_mate.status] == [400, 400]
    assert all(b["error"] == {"code": "invalid_request", "message": "이 대화는 다른 상대예요."} for b in bodies)
    assert calls == 2


async def test_manager_body_rules(tmp_path):
    async with BeEnv.start(tmp_path, start=START) as env:
        statuses = [
            (await env.post("/chat", json=env.chat_body("안녕", agent=agent, **kw))).status
            for agent, kw in (
                ("manager", {"checkin_id": 1}),
                ("secretary", {"chip": "manager_full"}),
                ("mate", {"chip": "manager_full"}),
                ("mate", {"chip": "manager_week"}),
                ("manager", {"chip": "mate_today"}),
                ("manager", {"chip": "todo"}),
            )
        ]
        bad = await env.get("/conversations?agent=bogus")
        bad_body = await bad.json()
        calls = len(env.brain.calls)
    assert statuses == [400] * 6 and calls == 0
    assert bad.status == 400
    assert bad_body["error"] == {"code": "invalid_request", "message": "agent는 secretary, mate, manager 가운데 하나예요."}


async def test_manager_chip_goes_to_brain(tmp_path):
    async with BeEnv.start(tmp_path, start=START, script=[FakeTurn([], "이번 주는 이것부터요.")]) as env:
        resp, _ = await env.chat("이번 주 뭐부터?", agent="manager", chip="manager_week")
        call = env.brain.calls[0]
    assert resp.status == 200
    assert f"## 버튼\n{prompts.load('chip_manager_week.md')}\n\n## 메시지" in call["prompt"]
    assert call["run_ctx"].chip == "manager_week"


async def test_manager_transcript_tag_and_secretary_cannot_read(tmp_path):
    """매니저 줄 머리글 끝이 ` @app @manager`, 화자 `라이프 매니저`. 비서 `read_transcript`에는 없다(스펙 13장)."""
    script = [FakeTurn([], "월급 이야기는 여기서만 해요."), FakeTurn([], "네")]
    async with BeEnv.start(tmp_path, start=START, script=script) as env:
        man, _ = await env.chat("통장 잔고가 걱정돼요", agent="manager")
        sec, _ = await env.chat("비서에게")
        cid = _cid(man)
        messages = await get_json(env, f"/conversations/{cid}/messages")
        raw = env.parts.transcripts.path_for(env.clock.now()).read_text(encoding="utf-8")
        day = env.clock.now().date().isoformat()
        tools = env.parts.tools
        app_read = tools.read_transcript(
            RunContext(conversation_id=_cid(sec), run_id=None, events=[], channel="app"), from_=day, to=day,
        )
        tg_read = tools.read_transcript(RunContext(conversation_id=None, run_id=None, events=[]), from_=day, to=day)
    headers = [line for line in raw.splitlines() if line.startswith("### ") and f"[{cid}]" in line]
    assert len(headers) == 2 and all(h.endswith(" @app @manager") for h in headers)
    assert " 라이프 매니저 " in headers[1] and " 사용자 " in headers[0]
    assert [m["speaker"] for m in messages["items"]] == ["user", "manager"]
    for got in (app_read, tg_read):
        assert "통장 잔고가 걱정돼요" not in got["text"]
        assert "월급 이야기는 여기서만 해요." not in got["text"]
    assert "비서에게" in app_read["text"]


def test_manager_tools_are_not_secretary_tools():
    """라이프 매니저 대화는 비서 도구를 받지 않는다. Task 7까지는 같은 상대의 지난 대화 찾기 하나뿐."""
    from my_planner.tools.mcp_adapter import tool_names_for

    ctx = RunContext(conversation_id=1, run_id=None, events=[], channel="app", agent="manager")
    assert tool_names_for(ctx) == ["find_conversations"]

from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    RateLimitInfo,
    ResultError,
    ResultMessage,
    TextBlock,
)

from my_planner.domain import RunContext
from my_planner.harness.brain import build_options, classify, detect_resume_failed
from my_planner.tools.mcp_adapter import allowed_tool_patterns, build_planner_server


def _options(tmp_path: Path, session_id=None):
    state_dir = tmp_path / "state"
    server = build_planner_server(None, RunContext(conversation_id=None, run_id=None, events=[]))
    opts = build_options(
        server=server,
        session_id=session_id,
        workdir=state_dir / "brain-workdir",
        max_turns=10,
        system_prompt="시스템",
    )
    return opts, server, state_dir


def test_build_options_locks_down_tools(tmp_path):
    opts, server, state_dir = _options(tmp_path)
    assert opts.tools == []
    assert opts.allowed_tools == ["mcp__planner__*"] == allowed_tool_patterns()
    assert opts.permission_mode == "dontAsk"
    assert opts.strict_mcp_config is True
    assert opts.extra_args == {}
    assert opts.mcp_servers == {"planner": server}
    assert server["name"] == "planner"
    assert opts.setting_sources == []
    assert opts.env == {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    }
    assert opts.max_turns == 10
    assert opts.system_prompt == "시스템"
    assert opts.cli_path is None
    cwd = Path(opts.cwd)
    assert cwd.is_absolute()
    assert cwd == (state_dir / "brain-workdir").resolve()
    assert str(cwd).endswith(str(Path("state") / "brain-workdir"))


def test_build_options_resume_passthrough(tmp_path):
    opts, _, _ = _options(tmp_path, session_id="sess-123")
    assert opts.resume == "sess-123"
    opts, _, _ = _options(tmp_path, session_id=None)
    assert opts.resume is None


# --- 오류 판별 (스펙 5.3 "오류 판별 규칙", S1). 실제 SDK 클래스로 만든 가짜 메시지 ---

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _assistant(error=None, text="답"):
    return AssistantMessage(content=[TextBlock(text=text)], model="claude", error=error)


def _result(subtype="success", is_error=False, terminal_reason=None, result=None):
    return ResultMessage(
        subtype=subtype,
        duration_ms=10,
        duration_api_ms=5,
        is_error=is_error,
        num_turns=1,
        session_id="s1",
        terminal_reason=terminal_reason,
        result=result,
    )


def _rate(status, resets_at=None):
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(status=status, resets_at=resets_at, rate_limit_type="five_hour"),
        uuid="u1",
        session_id="s1",
    )


def _result_error(**data):
    return ResultError("Claude Code returned an error result", data=data, exit_code=1)


def test_classify_auth_error():
    # S1 실제 순서: AssistantMessage(error) → ResultMessage(is_error) → ResultError 예외
    login = [
        _assistant(error="authentication_failed", text="Not logged in · Please run /login"),
        _result(is_error=True, terminal_reason="api_error"),
    ]
    exc = _result_error(subtype="success", is_error=True, terminal_reason="api_error")
    assert classify(login, exc, NOW) == ("auth_error", "login", None)

    billing = [_assistant(error="billing_error"), _result(is_error=True)]
    assert classify(billing, exc, NOW)[:2] == ("auth_error", "billing")


def test_classify_rate_limited():
    resets_at = 1792780200  # 2026-10-23 18:30 UTC (S1 실제 이벤트 값)
    msgs = [_rate("rejected", resets_at=resets_at), _result(is_error=True)]
    status, _error, retry_at = classify(msgs, _result_error(subtype="success"), NOW)
    assert status == "rate_limited"
    assert retry_at == datetime(2026, 10, 23, 18, 30, tzinfo=UTC)
    assert retry_at.tzinfo is not None and retry_at.utcoffset() == timedelta(0)

    # resets_at이 없으면 지금 + 1시간
    assert classify([_rate("rejected")], None, NOW) == ("rate_limited", None, NOW + timedelta(hours=1))
    # AssistantMessage.error == "rate_limit"도 한도
    assert classify([_assistant(error="rate_limit")], None, NOW) == (
        "rate_limited",
        None,
        NOW + timedelta(hours=1),
    )
    # 이미 지난 resets_at은 없는 것으로 본다
    past = int((NOW - timedelta(minutes=5)).timestamp())
    assert classify([_rate("rejected", resets_at=past)], None, NOW)[2] == NOW + timedelta(hours=1)

    # allowed_warning은 오류가 아니다
    assert classify([_rate("allowed_warning", resets_at=resets_at), _assistant(), _result()], None, NOW) == (
        "ok",
        None,
        None,
    )
    # billing_error는 한도가 아니라 계정 확인
    assert classify([_assistant(error="billing_error")], None, NOW) == ("auth_error", "billing", None)


def test_classify_max_turns_and_error():
    assert classify([_assistant(), _result(subtype="error_max_turns", is_error=True)], None, NOW) == (
        "max_turns",
        None,
        None,
    )
    # 예외의 subtype/terminal_reason으로도 max_turns
    assert classify([], _result_error(subtype="error_max_turns"), NOW)[0] == "max_turns"
    assert classify([], _result_error(subtype="success", terminal_reason="max_turns"), NOW)[0] == "max_turns"

    # 그 밖의 예외, is_error=True → error
    assert classify([_assistant()], RuntimeError("boom"), NOW)[0] == "error"
    assert (
        classify([_assistant(), _result(subtype="error_during_execution", is_error=True)], None, NOW)[0]
        == "error"
    )
    # 아니면 ok
    assert classify([_assistant(), _result()], None, NOW) == ("ok", None, None)


def test_detect_resume_failed():
    # resume을 시도했는데 두뇌가 한 턴도 돌기 전에 오류로 끝나면 resume 실패(세션 파일 없음 등)
    zero_turn = ResultMessage(
        subtype="error_during_execution",
        duration_ms=1,
        duration_api_ms=0,
        is_error=True,
        num_turns=0,
        session_id="new",
    )
    assert detect_resume_failed("s1", [], "error") is True
    assert detect_resume_failed("s1", [zero_turn], "error") is True
    # 새 세션이면 resume 실패가 아니다
    assert detect_resume_failed(None, [zero_turn], "error") is False
    # 두뇌가 답을 시작했으면 resume은 된 것이다
    assert detect_resume_failed("s1", [_assistant(), _result(is_error=True)], "error") is False
    turned = _result(is_error=True)
    assert turned.num_turns > 0
    assert detect_resume_failed("s1", [turned], "error") is False
    # 오류가 아닌 상태(로그인·한도·턴 상한·정상)는 resume 실패로 보지 않는다
    for status in ("ok", "auth_error", "rate_limited", "max_turns"):
        assert detect_resume_failed("s1", [], status) is False


async def test_claude_brain_sets_resume_failed(tmp_path, monkeypatch):
    # 원래 버그: ClaudeBrain이 resume_failed를 넘기지 않았다. 턴 없이 예외로 끝난 resume은 True.
    from my_planner.harness import brain as brain_mod

    async def failing_query(*, prompt, options):
        raise RuntimeError("process exited")
        yield  # pragma: no cover

    monkeypatch.setattr(brain_mod, "query", failing_query)
    monkeypatch.setattr(brain_mod, "build_planner_server", lambda tools, ctx: {"type": "sdk"})
    monkeypatch.setattr(brain_mod, "build_options", lambda **kw: None)
    b = brain_mod.ClaudeBrain(lambda: None, tmp_path, max_turns=10)
    ctx = RunContext(conversation_id=1, run_id=None, events=[])
    resumed = await b.run("hi", session_id="s1", run_ctx=ctx)
    assert resumed.status == "error"
    assert resumed.resume_failed is True
    fresh = await b.run("hi", session_id=None, run_ctx=ctx)
    assert fresh.resume_failed is False


def test_brain_result_carries_no_tool_events():
    # 도구 이벤트는 run_ctx.events 하나로만 읽는다(디스패처). BrainResult에 사본을 두지 않는다
    from dataclasses import fields

    from my_planner.harness.brain import BrainResult

    assert [f.name for f in fields(BrainResult)] == [
        "text", "session_id", "turns", "status", "error", "resume_failed", "retry_at",
    ]


def test_build_options_partial_messages_and_fork_off_by_default(tmp_path):
    """`build_options`의 기본은 부분 메시지 끄기(켜는 쪽은 `ClaudeBrain.run`이 스트림이 있을 때만, 06b)."""
    opts, _, _ = _options(tmp_path)
    assert opts.include_partial_messages is False
    assert opts.fork_session is False


def test_app_system_prompt_appends_channel_app(tmp_path):
    from my_planner.harness import prompts
    from my_planner.harness.brain import ClaudeBrain

    brain = ClaudeBrain(lambda: None, tmp_path / "wd", max_turns=10)
    assert brain.system_prompt_for("telegram") == prompts.load("system.md")
    app = brain.system_prompt_for("app")
    assert app.startswith(prompts.load("system.md"))
    assert app.endswith(prompts.load("channel_app.md"))


# --- 티켓 06b: 글 조각 스트리밍 (SP3-4 S11. 필드 경로는 SDK 소스 기준, 노트북 S11 시험으로 확인할 것) ---


def _stream_event(event: dict, parent_tool_use_id=None):
    from claude_agent_sdk import StreamEvent

    return StreamEvent(uuid="u", session_id="s1", event=event, parent_tool_use_id=parent_tool_use_id)


def _text_events(*pieces: str, index: int = 0) -> list:
    return [
        _stream_event({"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}),
        *[
            _stream_event({"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": p}})
            for p in pieces
        ],
        _stream_event({"type": "content_block_stop", "index": index}),
    ]


def _patch_query(monkeypatch, tmp_path, messages, seen_options=None):
    from my_planner.harness import brain as brain_mod

    real_build = brain_mod.build_options

    async def fake_query(*, prompt, options):
        if seen_options is not None:
            seen_options.append(options)
        for m in messages:
            yield m

    monkeypatch.setattr(brain_mod, "query", fake_query)
    monkeypatch.setattr(brain_mod, "build_planner_server", lambda tools, ctx: {"type": "sdk", "name": "planner"})
    monkeypatch.setattr(brain_mod, "build_options", real_build)
    return brain_mod.ClaudeBrain(lambda: None, tmp_path / "wd", max_turns=10)


async def test_stream_events_become_text_deltas(tmp_path, monkeypatch):
    from fakes import ListSink

    from my_planner.harness.stream import UiMessageWriter

    msgs = [*_text_events("내일 ", "치과를 ", "추가할게요."), _result(result="내일 치과를 추가할게요.")]
    brain = _patch_query(monkeypatch, tmp_path, msgs)
    sink = ListSink()
    writer = UiMessageWriter(sink, None)
    ctx = RunContext(conversation_id=1, run_id=None, events=[], channel="app", stream=writer)
    result = await brain.run("hi", session_id=None, run_ctx=ctx)

    assert sink.types == ["text-start", "text-delta", "text-delta", "text-delta", "text-end"]
    assert sink.text == "내일 치과를 추가할게요."
    assert len({c["id"] for c in sink.chunks}) == 1
    assert writer.streamed_text == "내일 치과를 추가할게요."
    assert result.status == "ok" and result.text == "내일 치과를 추가할게요."


async def test_stream_events_ignore_non_text_and_subagent_and_close_open_block(tmp_path, monkeypatch):
    from fakes import ListSink

    from my_planner.harness.stream import UiMessageWriter

    tool_block = [
        _stream_event({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "x"}}),
        _stream_event({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{"}}),
        _stream_event({"type": "content_block_stop", "index": 1}),
    ]
    sub = [_stream_event(e.event, parent_tool_use_id="toolu_1") for e in _text_events("하위")]
    open_block = _text_events("끊김")[:-1]  # content_block_stop이 오지 않았다
    msgs = [*tool_block, *sub, *open_block, _result(result="끊김")]
    brain = _patch_query(monkeypatch, tmp_path, msgs)
    sink = ListSink()
    ctx = RunContext(conversation_id=1, run_id=None, events=[], channel="app", stream=UiMessageWriter(sink, None))
    await brain.run("hi", session_id=None, run_ctx=ctx)

    assert sink.types == ["text-start", "text-delta", "text-end"]  # 도구·하위 에이전트 조각은 없고, 열린 블록은 닫는다
    assert sink.text == "끊김"


def test_text_stream_field_path():
    from my_planner.harness.brain import text_block_event

    assert text_block_event({"type": "content_block_start", "index": 2, "content_block": {"type": "text"}}) == ("start", 2, "")
    assert text_block_event({"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use"}}) is None
    assert text_block_event(
        {"type": "content_block_delta", "index": 2, "delta": {"type": "text_delta", "text": "가"}}
    ) == ("delta", 2, "가")
    assert text_block_event({"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta"}}) is None
    assert text_block_event({"type": "content_block_stop", "index": 2}) == ("stop", 2, "")
    assert text_block_event({"type": "message_start"}) is None
    assert text_block_event({}) is None


async def test_partial_messages_only_when_streaming(tmp_path, monkeypatch):
    from fakes import ListSink

    from my_planner.harness.stream import UiMessageWriter

    seen: list = []
    brain = _patch_query(monkeypatch, tmp_path, [_result(result="ok")], seen)
    plain = RunContext(conversation_id=1, run_id=None, events=[])
    await brain.run("hi", session_id=None, run_ctx=plain)
    streaming = RunContext(conversation_id=1, run_id=None, events=[], channel="app", stream=UiMessageWriter(ListSink(), None))
    await brain.run("hi", session_id=None, run_ctx=streaming)

    assert [o.include_partial_messages for o in seen] == [False, True]


async def test_two_text_blocks_around_tool_call_get_separate_ids(tmp_path, monkeypatch):
    from fakes import ListSink

    from my_planner.harness.stream import UiMessageWriter

    tool = [
        _stream_event({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "x"}}),
        _stream_event({"type": "content_block_stop", "index": 1}),
    ]
    msgs = [
        _stream_event({"type": "message_start"}),
        *_text_events("먼저 ", "할게요.", index=0),
        *tool,
        _stream_event({"type": "message_stop"}),
        _stream_event({"type": "message_start"}),
        *_text_events("끝났어요.", index=0),  # 새 메시지의 번호는 다시 0
        _stream_event({"type": "message_stop"}),
        _result(result="끝났어요."),
    ]
    brain = _patch_query(monkeypatch, tmp_path, msgs)
    sink = ListSink()
    writer = UiMessageWriter(sink, None)
    ctx = RunContext(conversation_id=1, run_id=None, events=[], channel="app", stream=writer)
    await brain.run("hi", session_id=None, run_ctx=ctx)

    assert sink.types == [
        "text-start", "text-delta", "text-delta", "text-end", "text-start", "text-delta", "text-end",
    ]
    ids = [c["id"] for c in sink.chunks if c["type"] == "text-start"]
    assert len(set(ids)) == 2
    assert [c["id"] for c in sink.chunks if c["type"] == "text-end"] == ids
    assert writer.streamed_reply == "먼저 할게요.\n\n끝났어요."


async def test_text_streamer_resets_on_message_start_even_if_stop_missing(tmp_path, monkeypatch):
    from fakes import ListSink

    from my_planner.harness.stream import UiMessageWriter

    msgs = [
        _stream_event({"type": "message_start"}),
        *_text_events("하나")[:-1],  # stop이 빠졌다
        _stream_event({"type": "message_start"}),
        *_text_events("둘"),
        _result(result="둘"),
    ]
    brain = _patch_query(monkeypatch, tmp_path, msgs)
    sink = ListSink()
    ctx = RunContext(conversation_id=1, run_id=None, events=[], channel="app", stream=UiMessageWriter(sink, None))
    await brain.run("hi", session_id=None, run_ctx=ctx)

    ids = [c["id"] for c in sink.chunks if c["type"] == "text-start"]
    assert len(set(ids)) == 2 and sink.types.count("text-end") == 2


# --- SP7-00 S12: 습관 도구를 더한 도구 수 (텔레그램 22+6=28, 앱 28+7=35). 가짜 도구, 실제 도구는 뒤 티켓 ---

FAKE_HABIT_TOOLS = ["add_habit", "update_habit", "set_habit_status", "check_habit", "uncheck_habit", "list_habits"]


def test_options_with_habit_tools_28_and_35(tmp_path):
    from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

    from my_planner.tools.mcp_adapter import SERVER_NAME, tool_names_for

    async def _ok(args):
        return {"content": [{"type": "text", "text": '{"ok": true}'}]}

    for channel, extra, expected in (
        ("telegram", FAKE_HABIT_TOOLS, 28),
        ("app", [*FAKE_HABIT_TOOLS, "ui_habit_check"], 35),
    ):
        # SP7-02부터 습관 도구는 실제 도구다: 이미 있는 이름은 다시 더하지 않는다(수는 그대로 28, 35)
        base = tool_names_for(RunContext(None, None, channel=channel))
        names = [*base, *(n for n in extra if n not in base)]
        assert len(names) == expected == len(set(names))
        tools = [
            SdkMcpTool(name=n, description=n, input_schema={"type": "object", "properties": {}}, handler=_ok)
            for n in names
        ]
        server = create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=tools)
        opts = build_options(
            server=server, session_id=None, workdir=tmp_path / "wd", max_turns=10, system_prompt="시스템"
        )
        assert opts.mcp_servers == {SERVER_NAME: server}
        assert opts.tools == [] and opts.max_turns == 10
        patterns = allowed_tool_patterns()
        assert opts.allowed_tools == patterns
        for n in names:
            full = f"mcp__{SERVER_NAME}__{n}"
            assert any(fnmatch(full, p) for p in patterns), full


# --- SP8-03: 순간 호출 (SP8 스펙 6.3) ---


def _capture_build(monkeypatch, tmp_path):
    """`ClaudeBrain.run`이 `build_options`에 넘긴 인자와 만든 옵션을 모은다(두뇌는 부르지 않는다)."""
    from my_planner.harness import brain as brain_mod

    real_build = brain_mod.build_options
    seen: list[dict] = []
    built: list = []

    def capture(**kw):
        seen.append(kw)
        built.append(real_build(**kw))
        return built[-1]

    async def fake_query(*, prompt, options):
        yield _result(result="ok")

    monkeypatch.setattr(brain_mod, "query", fake_query)
    monkeypatch.setattr(brain_mod, "build_planner_server", lambda tools, ctx: {"type": "sdk", "name": "planner"})
    monkeypatch.setattr(brain_mod, "build_options", capture)
    return brain_mod.ClaudeBrain(lambda: None, tmp_path / "wd", max_turns=10), seen, built


def _moments_ctx():
    from datetime import date

    return RunContext(None, None, kind="moments", activity_channel="scheduler", moments_date=date(2026, 10, 24))


async def test_moments_options_disable_session_persistence(tmp_path, monkeypatch):
    brain, _, built = _capture_build(monkeypatch, tmp_path)
    await brain.run("입력", session_id=None, run_ctx=_moments_ctx(), max_turns=3, persist_session=False)
    assert built[0].extra_args == {"no-session-persistence": None}
    assert built[0].resume is None


async def test_chat_options_keep_session(tmp_path, monkeypatch):
    brain, _, built = _capture_build(monkeypatch, tmp_path)
    await brain.run("안녕", session_id="s1", run_ctx=RunContext(conversation_id=1, run_id=None, events=[]))
    assert built[0].extra_args == {}
    assert built[0].max_turns == 10
    opts, _, _ = _options(tmp_path)
    assert opts.extra_args == {}


async def test_claude_brain_uses_given_system_prompt_and_max_turns(tmp_path, monkeypatch):
    from my_planner.harness import prompts
    from my_planner.harness.moments import moments_system_prompt

    brain, seen, _ = _capture_build(monkeypatch, tmp_path)
    await brain.run(
        "입력", session_id=None, run_ctx=_moments_ctx(), system_prompt=moments_system_prompt(), max_turns=3,
        persist_session=False,
    )
    assert seen[0]["max_turns"] == 3
    system = seen[0]["system_prompt"]
    assert system.startswith(prompts.load("moments.md"))
    assert prompts.load("system.md").splitlines()[0] not in system

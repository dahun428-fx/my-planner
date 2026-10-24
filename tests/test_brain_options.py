from datetime import UTC, datetime, timedelta
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


def _result(subtype="success", is_error=False, terminal_reason=None):
    return ResultMessage(
        subtype=subtype,
        duration_ms=10,
        duration_api_ms=5,
        is_error=is_error,
        num_turns=1,
        session_id="s1",
        terminal_reason=terminal_reason,
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
    """이 티켓의 두뇌는 부분 메시지를 켜지 않는다(SP3-4 06: 글 블록 하나, 조각 스트리밍은 06b)."""
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
    assert app.endswith(prompts.load("channel_app.md"))  # 지금은 빈 자리(티켓 09가 채운다)

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
    status, error, retry_at = classify(msgs, _result_error(subtype="success"), NOW)
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
    assert detect_resume_failed("s1", [_result(is_error=True)], "error") is False
    # 오류가 아닌 상태(로그인·한도·턴 상한·정상)는 resume 실패로 보지 않는다
    for status in ("ok", "auth_error", "rate_limited", "max_turns"):
        assert detect_resume_failed("s1", [], status) is False

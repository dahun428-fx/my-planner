"""두뇌: Brain 프로토콜과 Claude Agent SDK 구현 (스펙 4, 5.3)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    McpSdkServerConfig,
    RateLimitEvent,
    ResultError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

from my_planner.domain import RunContext, ToolEvent
from my_planner.harness import prompts
from my_planner.tools.mcp_adapter import (
    SERVER_NAME,
    allowed_tool_patterns,
    build_planner_server,
)

log = logging.getLogger(__name__)

BrainStatus = Literal["ok", "max_turns", "auth_error", "rate_limited", "error"]

# 스펙 5.3: claude.ai 커넥터와 auto memory는 setting_sources와 상관없이 로드되므로 env로 끈다.
BRAIN_ENV = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
}


@dataclass
class BrainResult:
    text: str
    session_id: str | None
    turns: int
    tool_events: list[ToolEvent]
    status: BrainStatus
    error: str | None = None  # auth_error면 "login" | "billing"
    resume_failed: bool = False
    retry_at: datetime | None = None  # rate_limited일 때 재개 시각(UTC)


class Brain(Protocol):
    async def run(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext
    ) -> BrainResult: ...


def build_options(
    *,
    server: McpSdkServerConfig,
    session_id: str | None,
    workdir: Path,
    max_turns: int,
    system_prompt: str,
    cli_path: str | Path | None = None,
) -> ClaudeAgentOptions:
    """스펙 5.3 두뇌 실행 설정. S2: strict MCP는 필드로, S3: cli_path는 기본 None(번들 CLI)."""
    return ClaudeAgentOptions(
        tools=[],
        mcp_servers={SERVER_NAME: server},
        allowed_tools=allowed_tool_patterns(),
        permission_mode="dontAsk",
        strict_mcp_config=True,
        setting_sources=[],
        cwd=str(Path(workdir).resolve()),
        max_turns=max_turns,
        system_prompt=system_prompt,
        resume=session_id,
        env=dict(BRAIN_ENV),
        cli_path=cli_path,
    )


# --- 오류 판별 (스펙 5.3 "오류 판별 규칙", S1 결과). 문자열 매칭은 쓰지 않는다. ---

RATE_LIMIT_FALLBACK = timedelta(hours=1)
_AUTH_ERRORS = {"authentication_failed": "login", "billing_error": "billing"}


def classify(
    messages: list[object], exc: BaseException | None, now: datetime
) -> tuple[BrainStatus, str | None, datetime | None]:
    """호출 중 받은 메시지 전부와 잡은 예외로 (status, error, retry_at)을 정한다."""
    assistant_errors = [m.error for m in messages if isinstance(m, AssistantMessage) and m.error]

    # 1. 로그인·결제: 뒤따르는 예외보다 우선
    for code in ("authentication_failed", "billing_error"):
        if code in assistant_errors:
            return "auth_error", _AUTH_ERRORS[code], None

    # 2. 사용 한도: rejected 이벤트의 resets_at(Unix 초), 없거나 이미 지났으면 지금 + 1시간
    rejected = [
        m.rate_limit_info
        for m in messages
        if isinstance(m, RateLimitEvent) and m.rate_limit_info.status == "rejected"
    ]
    if rejected or "rate_limit" in assistant_errors:
        retry_at = now + RATE_LIMIT_FALLBACK
        for info in rejected:
            if info.resets_at is not None:
                at = datetime.fromtimestamp(info.resets_at, UTC)
                if at > now:
                    retry_at = at
        return "rate_limited", None, retry_at

    results = [m for m in messages if isinstance(m, ResultMessage)]

    # 3. 턴 상한
    if any(r.subtype == "error_max_turns" or r.terminal_reason == "max_turns" for r in results):
        return "max_turns", None, None
    if isinstance(exc, ResultError) and (
        exc.subtype == "error_max_turns" or exc.terminal_reason == "max_turns"
    ):
        return "max_turns", None, None

    # 4. 그 밖의 예외나 is_error=True. error에는 로그용 종류만 담는다(본문 없음).
    if exc is not None:
        return "error", type(exc).__name__, None
    if any(r.is_error for r in results):
        return "error", "is_error", None

    return "ok", None, None


def detect_resume_failed(session_id: str | None, messages: list[object], status: BrainStatus) -> bool:
    """resume 호출이 한 턴도 돌기 전에 오류로 끝났는지(세션 파일 없음 등, 스펙 5.3).

    문자열 매칭 대신 모양으로 판단한다: AssistantMessage가 없고 num_turns>0인 결과도 없다.
    """
    if session_id is None or status != "error":
        return False
    if any(isinstance(m, AssistantMessage) for m in messages):
        return False
    return not any(isinstance(m, ResultMessage) and m.num_turns > 0 for m in messages)


# --- Agent SDK 구현 ---


class ClaudeBrain:
    """Claude Agent SDK로 두뇌를 부른다. 호출마다 `planner` 서버를 새로 만든다.

    `cli_path`는 번들 CLI가 망가졌을 때를 위한 비상용 인자다. 설정 파일에는 두지 않고,
    `app.py`도 넘기지 않는다(S3: 번들 CLI 사용).
    """

    def __init__(
        self,
        tools_factory: Callable[[], Any],
        workdir: Path,
        max_turns: int,
        cli_path: str | Path | None = None,
    ) -> None:
        self._tools_factory = tools_factory
        self._workdir = Path(workdir).resolve()
        self._workdir.mkdir(parents=True, exist_ok=True)
        self._max_turns = max_turns
        self._cli_path = cli_path
        self._system_prompt = prompts.load("system.md")

    async def run(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext
    ) -> BrainResult:
        server = build_planner_server(self._tools_factory(), run_ctx)
        options = build_options(
            server=server,
            session_id=session_id,
            workdir=self._workdir,
            max_turns=self._max_turns,
            system_prompt=self._system_prompt,
            cli_path=self._cli_path,
        )
        messages: list[object] = []
        exc: Exception | None = None
        try:
            async for message in query(prompt=prompt, options=options):
                messages.append(message)
        except Exception as e:  # ResultError/ProcessError 등. CancelledError는 그대로 올린다.
            exc = e

        status, error, retry_at = classify(messages, exc, datetime.now(UTC))
        _log_rate_warnings(messages)
        result = next((m for m in reversed(messages) if isinstance(m, ResultMessage)), None)
        return BrainResult(
            text=_reply_text(messages, result) if status == "ok" else "",
            session_id=_session_id(messages, result) or session_id,
            turns=result.num_turns if result else 0,
            tool_events=list(run_ctx.events),
            status=status,
            error=error,
            resume_failed=detect_resume_failed(session_id, messages, status),
            retry_at=retry_at,
        )


def _reply_text(messages: list[object], result: ResultMessage | None) -> str:
    if result is not None and result.result:
        return result.result.strip()
    parts = [
        block.text
        for m in messages
        if isinstance(m, AssistantMessage) and m.parent_tool_use_id is None
        for block in m.content
        if isinstance(block, TextBlock)
    ]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def _session_id(messages: list[object], result: ResultMessage | None) -> str | None:
    if result is not None and result.session_id:
        return result.session_id
    for m in messages:
        if isinstance(m, SystemMessage) and m.subtype == "init":
            sid = m.data.get("session_id")
            if isinstance(sid, str):
                return sid
    return None


def _log_rate_warnings(messages: list[object]) -> None:
    for m in messages:
        if isinstance(m, RateLimitEvent) and m.rate_limit_info.status == "allowed_warning":
            info = m.rate_limit_info
            log.info(
                "rate_limit_warning",
                extra={"rate_limit_type": info.rate_limit_type, "utilization": info.utilization},
            )

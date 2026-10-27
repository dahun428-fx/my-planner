"""두뇌: Brain 프로토콜과 Claude Agent SDK 구현 (스펙 4, 5.3)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
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
    StreamEvent,
    SystemMessage,
    TextBlock,
    query,
)

from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.harness.photo_reader import UserContent
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
    status: BrainStatus
    error: str | None = None  # auth_error면 "login" | "billing"
    resume_failed: bool = False
    retry_at: datetime | None = None  # rate_limited일 때 재개 시각(UTC)


# 세션 저장을 끄는 CLI 플래그(SP8 6.3). SDK는 값이 None인 열쇠를 `--<flag>`로 그대로 넘긴다
NO_SESSION_PERSISTENCE = {"no-session-persistence": None}


class Brain(Protocol):
    """`fork_session=True`: `session_id`를 이어 가되 새 세션으로 갈라 시작한다(회차 대화 가르기, SP3-4 7.2).

    `system_prompt`·`max_turns`가 있으면 기본 지시문(`system.md`)·설정값 대신 쓰고, `persist_session=False`면
    세션 파일을 쓰지 않는다(하루 끝 순간 호출, SP8 6.3). 디스패처는 기본값이 아닐 때만 이 인자들을 넘긴다
    (SP1의 두뇌 구현은 받지 않아도 된다).

    `prompt`가 글·이미지 블록 목록(`UserContent`)이면 SDK 스트리밍 입력의 사용자 메시지 하나로 보낸다(SP10 5.4·5.5,
    스파이크 S1). 글이면 지금 경로 그대로다.
    """

    async def run(
        self, prompt: str | UserContent, *, session_id: str | None, run_ctx: RunContext, fork_session: bool = False,
        system_prompt: str | None = None, max_turns: int | None = None, persist_session: bool = True,
    ) -> BrainResult: ...


def build_options(
    *,
    server: McpSdkServerConfig,
    session_id: str | None,
    workdir: Path,
    max_turns: int,
    system_prompt: str,
    cli_path: str | Path | None = None,
    include_partial_messages: bool = False,
    fork_session: bool = False,
    extra_args: dict[str, str | None] | None = None,
) -> ClaudeAgentOptions:
    """스펙 5.3 두뇌 실행 설정. S2: strict MCP는 필드로, S3: cli_path는 기본 None(번들 CLI).

    `include_partial_messages`: 글 조각 스트리밍(SP3-4 S11, 티켓 06b). `fork_session`: 회차 대화 가르기(7.2, 티켓 07).
    `extra_args`: CLI 플래그(순간 호출의 `no-session-persistence`, SP8 6.3). 없으면 빈 dict.
    """
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
        include_partial_messages=include_partial_messages,
        fork_session=fork_session,
        extra_args=dict(extra_args or {}),
    )


def user_message_stream(content: UserContent, session_id: str | None) -> AsyncIterator[dict[str, Any]]:
    """SDK 스트리밍 입력: 사용자 메시지 하나(스파이크 S1에서 `build_options()` 그대로 되는 모양). `resume`과 함께 된다."""

    async def stream() -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None,
            "session_id": session_id or "default",
        }

    return stream()


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
        # 앱 통로는 `system.md` 뒤에 `channel_app.md`(화면 도구·카드 도구 지시)를 붙인다(SP3-4 6.4.7)
        app_part = prompts.load("channel_app.md").strip()
        self._app_system_prompt = f"{self._system_prompt}\n\n{app_part}" if app_part else self._system_prompt

    def system_prompt_for(self, channel: str) -> str:
        return self._app_system_prompt if channel == "app" else self._system_prompt

    async def run(
        self, prompt: str | UserContent, *, session_id: str | None, run_ctx: RunContext, fork_session: bool = False,
        system_prompt: str | None = None, max_turns: int | None = None, persist_session: bool = True,
    ) -> BrainResult:
        server = build_planner_server(self._tools_factory(), run_ctx)
        # 앱 채팅(스트림 쓰개가 있음)만 글 조각을 받는다(SP3-4 S11, 6.4.1). 조각이 안 오면 06처럼 끝난 뒤 글 블록 하나
        options = build_options(
            server=server,
            session_id=session_id,
            workdir=self._workdir,
            max_turns=max_turns if max_turns is not None else self._max_turns,
            system_prompt=system_prompt if system_prompt is not None else self.system_prompt_for(run_ctx.channel),
            cli_path=self._cli_path,
            include_partial_messages=run_ctx.stream is not None,
            # S11: `resume=<원래 세션>` + `fork_session=True`면 CLI가 새 세션 id로 갈라 시작한다(결과의 session_id).
            # 가르기가 안 되면(세션 파일 없음 등) resume 실패와 같은 모양이라 디스패처가 SP1 대체 경로로 간다
            fork_session=fork_session and session_id is not None,
            # 하루 끝 순간 호출은 이어 쓰지 않으므로 세션 jsonl을 쓰지 않는다(SP8 6.3, 디스패처가 호출 뒤 한 번 더 지운다)
            extra_args=None if persist_session else NO_SESSION_PERSISTENCE,
        )
        messages: list[object] = []
        text_stream = _TextStreamer(run_ctx.stream) if run_ctx.stream is not None else None
        exc: Exception | None = None
        try:
            # 글·이미지 블록이면 스트리밍 입력으로(5.4·5.5), 글이면 지금처럼 문자열 그대로
            sdk_prompt = prompt if isinstance(prompt, str) else user_message_stream(prompt, session_id)
            async for message in query(prompt=sdk_prompt, options=options):
                if run_ctx.brain_session_id is None:  # 끝나기 전에 끊겨도 디스패처가 그 세션을 알게(SP8 6.3)
                    run_ctx.brain_session_id = _message_session_id(message)
                if isinstance(message, StreamEvent):  # 부분 메시지는 분류와 답 글에 쓰지 않는다
                    if text_stream is not None and message.parent_tool_use_id is None:
                        text_stream.feed(message.event)
                    continue
                messages.append(message)
        except Exception as e:  # noqa: BLE001 - ResultError/ProcessError 등을 classify가 판정한다. CancelledError는 그대로 올린다.
            exc = e
        finally:
            if text_stream is not None:
                text_stream.close()  # 끊기거나 오류로 끝나도 열린 글 블록은 닫는다

        status, error, retry_at = classify(messages, exc, datetime.now(UTC))
        _log_rate_warnings(messages)
        result = next((m for m in reversed(messages) if isinstance(m, ResultMessage)), None)
        return BrainResult(
            text=_reply_text(messages, result) if status == "ok" else "",
            session_id=_session_id(messages, result) or session_id,
            turns=result.num_turns if result else 0,
            status=status,
            error=error,
            resume_failed=detect_resume_failed(session_id, messages, status),
            retry_at=retry_at,
        )


def text_block_event(event: dict[str, Any]) -> tuple[Literal["start", "delta", "stop"], int, str] | None:
    """`StreamEvent.event`(원본 Anthropic 스트리밍 이벤트)에서 글 블록 조각을 읽는다. 글 조각이 아니면 None.

    S11 필드 경로는 모두 여기에만 있다(SDK 소스 `types.StreamEvent`와 Anthropic 스트리밍 규격에서 가져온 것이고,
    노트북 S11 시험으로 확인하거나 고칠 것, docs/spikes/2026-11-sp3-4.md):
    - 시작: `type == "content_block_start"`, `content_block.type == "text"`, 번호 `index`
    - 조각: `type == "content_block_delta"`, `delta.type == "text_delta"`, 글 `delta.text`, 번호 `index`
    - 끝: `type == "content_block_stop"`, 번호 `index`
    돌려주는 값: `(종류, index, 글)`. 시작과 끝의 글은 빈 문자열이다.
    """
    kind = event.get("type")
    index = event.get("index")
    if not isinstance(index, int):
        return None
    if kind == "content_block_start":
        block = event.get("content_block")
        if isinstance(block, dict) and block.get("type") == "text":
            return "start", index, ""
    elif kind == "content_block_delta":
        delta = event.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
            return "delta", index, delta["text"]
    elif kind == "content_block_stop":
        return "stop", index, ""
    return None


class _TextStreamer:
    """글 블록 조각을 `UiMessageWriter`의 `text-start/delta/end`로 옮긴다. 블록 번호(`index`)마다 글 id 하나."""

    def __init__(self, writer: Any) -> None:
        self._writer = writer
        self._open: dict[int, str] = {}

    def feed(self, event: dict[str, Any]) -> None:
        if event.get("type") in ("message_start", "message_stop"):
            self.close()  # 새 메시지의 블록 번호는 0부터다. 빠진 stop 때문에 옛 id를 쓰지 않게
            return
        parsed = text_block_event(event)
        if parsed is None:
            return
        kind, index, text = parsed
        if kind == "start":
            if index not in self._open:
                self._open[index] = self._writer.next_text_id()
                self._writer.text_start(self._open[index])
        elif kind == "delta":
            if index not in self._open:  # 시작을 못 받았어도 글은 잃지 않는다
                self._open[index] = self._writer.next_text_id()
                self._writer.text_start(self._open[index])
            if text:
                self._writer.text_delta(self._open[index], text)
        elif index in self._open:
            self._writer.text_end(self._open.pop(index))

    def close(self) -> None:
        for index in list(self._open):
            self._writer.text_end(self._open.pop(index))


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


def _message_session_id(message: object) -> str | None:
    """메시지 하나가 실은 세션 id(init `SystemMessage`, 스트림 조각, 결과). 없으면 None."""
    if isinstance(message, SystemMessage) and message.subtype == "init":
        sid = message.data.get("session_id")
        return sid if isinstance(sid, str) and sid else None
    sid = getattr(message, "session_id", None) if isinstance(message, (StreamEvent, ResultMessage)) else None
    return sid if isinstance(sid, str) and sid else None


def _log_rate_warnings(messages: list[object]) -> None:
    for m in messages:
        if isinstance(m, RateLimitEvent) and m.rate_limit_info.status == "allowed_warning":
            info = m.rate_limit_info
            log.info(
                "rate_limit_warning",
                extra={"rate_limit_type": info.rate_limit_type, "utilization": info.utilization},
            )

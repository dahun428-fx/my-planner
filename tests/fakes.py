"""테스트용 가짜: 두뇌, 전송, sleep, 설정."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from my_planner.clock import FakeClock
from my_planner.config import PathsConfig, Settings, VapidConfig
from my_planner.domain import RunContext
from my_planner.harness.brain import BrainResult
from my_planner.harness.dispatcher import Outbound
from my_planner.tools.mcp_adapter import call_tool


@dataclass
class FakeTurn:
    """두뇌 호출 한 번의 시나리오. `tool_calls`는 `(도구 이름, 인자 dict)` 목록이다."""

    tool_calls: list[tuple[str, dict[str, Any]]]
    text: str
    status: str = "ok"
    session_id: str | None = "s1"
    error: str | None = None
    retry_at: Any = None
    resume_failed: bool = False
    delay: float = 0.0  # 이 초만큼 걸린 것처럼 한다(FakeClock이 그만큼 움직일 때까지 기다린다)
    hang: bool = False  # 도구를 부른 뒤 영영 돌아오지 않는다(두뇌 호출 시간 상한 시험)
    gate: asyncio.Event | None = None  # 도구를 부른 뒤 이 이벤트가 설 때까지 기다린다(처리 중 시험)
    deltas: list[str] | None = None  # 앱 채팅에서 도구 호출 전에 이 조각들로 글 블록을 스트리밍한다(06b)


class FakeBrain:
    def __init__(self, script: list[FakeTurn], tools: Any = None, *, clock: FakeClock | None = None):
        self.script = list(script)
        self.tools = tools
        self.clock = clock
        self.calls: list[dict[str, Any]] = []

    @property
    def prompts(self) -> list[str]:
        return [c["prompt"] for c in self.calls]

    @property
    def session_ids(self) -> list[str | None]:
        return [c["session_id"] for c in self.calls]

    @property
    def forks(self) -> list[bool]:
        """호출마다 `fork_session`(회차 대화 가르기, SP3-4 16장 "가르기 호출을 기록한다")."""
        return [c["fork_session"] for c in self.calls]

    async def run(
        self, prompt: str, *, session_id: str | None, run_ctx: RunContext, fork_session: bool = False
    ) -> BrainResult:
        self.calls.append(
            {"prompt": prompt, "session_id": session_id, "run_ctx": run_ctx, "fork_session": fork_session}
        )
        if not self.script:
            raise AssertionError("FakeBrain: 시나리오가 더 없다")
        turn = self.script.pop(0)
        if turn.deltas and run_ctx.stream is not None:
            w = run_ctx.stream
            text_id = w.next_text_id()
            w.text_start(text_id)
            for d in turn.deltas:
                w.text_delta(text_id, d)
            w.text_end(text_id)
        for name, args in turn.tool_calls:
            if self.tools is None:
                raise AssertionError(f"FakeBrain: 도구 {name}를 부를 tools가 없다")
            if run_ctx.stream is not None:  # 앱 채팅: MCP 처리기와 같은 길(도구 조각, SP3-4 6.4.1)
                call_tool(self.tools, run_ctx, name, args)
                continue
            out = getattr(self.tools, name)(run_ctx, **args)
            if inspect.isawaitable(out):
                await out
        if turn.gate is not None:
            await turn.gate.wait()
        if turn.hang:
            await asyncio.Event().wait()
        if turn.delay:
            assert self.clock is not None, "delay에는 clock이 필요하다"
            until = self.clock.now() + timedelta(seconds=turn.delay)
            while self.clock.now() < until:
                await asyncio.sleep(0)
        return BrainResult(
            text=turn.text,
            session_id=turn.session_id,
            turns=1 + len(turn.tool_calls),
            status=turn.status,  # type: ignore[arg-type]
            error=turn.error,
            resume_failed=turn.resume_failed,
            retry_at=turn.retry_at,
        )


# 꾸며 낸 VAPID 값(실제 키가 아니다). 시험은 `make_settings(tmp_path, vapid=FAKE_VAPID)`로 푸시를 켠다
FAKE_VAPID = VapidConfig(
    public_key="BFakePublicKeyForTestsOnly000000000000000000000000000000000000000000000000000000000000",
    private_key=SecretStr("fake-private-key-for-tests-only"),
    subject="mailto:test@example.invalid",
)


def _fake_browser_keys() -> tuple[str, str]:
    """꾸며 낸 브라우저 구독 키: 고정한 작은 비밀값에서 만든 P-256 공개점(65바이트)과 auth 16바이트(base64url)."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    point = ec.derive_private_key(12345, ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    return b64(point), b64(bytes(range(16)))


FAKE_P256DH, FAKE_AUTH = _fake_browser_keys()


@dataclass
class PushCall:
    endpoint: str
    payload: dict[str, Any]
    ttl: int
    topic: str | None


class FakePushSender:
    """`PushSender`의 가짜(동기). `results[endpoint]`에서 차례로 꺼내 상태 코드를 돌려주거나 예외를 올린다.

    목록이 비었거나 없으면 201. `.sent`에는 보낸 시도 하나마다 `PushCall`(받지 못한 시도도 적는다).
    """

    def __init__(self, results: dict[str, list[int | Exception]] | None = None) -> None:
        self.results = {k: list(v) for k, v in (results or {}).items()}
        self.sent: list[PushCall] = []

    def send(self, sub: Any, payload: dict[str, Any], *, ttl: int, topic: str | None) -> int:
        self.sent.append(PushCall(sub.endpoint, payload, ttl, topic))
        queue = self.results.get(sub.endpoint)
        r = queue.pop(0) if queue else 201
        if isinstance(r, Exception):
            raise r
        return r

    def always(self, endpoint: str, status: int, n: int = 100) -> None:
        """그 구독은 앞으로 `n`번 `status`를 돌려준다."""
        self.results[endpoint] = [status] * n


class FakeSender:
    """`send`는 버튼(초안, 확인, 컨디션)이 붙은 메시지면 가짜 메시지 id(1부터)를 돌려준다(`TelegramSender`와 같다).

    `cleared`: 버튼을 거둔 메시지 id(`clear_buttons`). `clear_fail`이면 거두기가 예외를 올린다.
    """

    def __init__(self, *, fail: bool = False, clear_fail: bool = False):
        self.sent: list[Outbound] = []
        self.message_ids: list[int | None] = []
        self.cleared: list[int] = []
        self.typing_count = 0
        self.fail = fail
        self.clear_fail = clear_fail
        self._next_id = 1

    async def send(self, out: Outbound) -> int | None:
        if self.fail:
            raise ConnectionError("fake send failure")
        self.sent.append(out)
        mid = None
        if (
            out.draft_task_ids or out.draft_milestone_ids or out.draft_chapter_ids
            or out.ask_condition_for is not None or out.confirms or out.ladder is not None
        ):
            mid, self._next_id = self._next_id, self._next_id + 1
        self.message_ids.append(mid)
        return mid

    async def clear_buttons(self, message_id: int) -> None:
        if self.clear_fail:
            raise ConnectionError("fake clear failure")
        self.cleared.append(message_id)

    async def typing(self) -> None:
        self.typing_count += 1


def fake_sleep(clock: FakeClock, *, real: float = 0.0):
    """실제로 기다리지 않는 sleep: 시계만 움직이고 한 번 양보한다.

    `real`초는 실제로 기다린다. 실제 시간 상한(두뇌 호출 시간 상한)을 기다리는 동안 '입력 중' 루프가
    가짜 시계를 몇 시간씩 앞으로 돌리지 않게 할 때 쓴다.
    """

    async def sleep(seconds: float) -> None:
        clock.advance(timedelta(seconds=seconds))
        await asyncio.sleep(real)

    return sleep


def make_settings(root: Path, **overrides: Any) -> Settings:
    return Settings(
        telegram_bot_token="123:test-token",
        owner_telegram_id=42,
        paths=PathsConfig.for_root(root),
        **overrides,
    )


class RepoApplier:
    """즉시 갈래(`Dispatcher.apply_action`)의 가짜: 하루 한 번 작업 `expire_drafts`만 저장소에 그대로 넘긴다."""

    def __init__(self, tasks: Any) -> None:
        self.tasks = tasks
        self.requests: list[Any] = []

    def apply_action(self, req: Any) -> Any:
        from my_planner.tools.actions import ActionResult

        self.requests.append(req)
        assert req.action == "expire_drafts" and (req.actor, req.channel) == ("secretary", "scheduler")
        ids = self.tasks.expire_drafts(req.args["older_than"])
        return ActionResult("applied", 200, {"status": "applied", "result": {"expired_ids": ids}})


class ListSink:
    """조각을 목록에 모으는 시험용 `StreamSink`(HTTP 없이 스트림 형식을 본다, SP3-4 16장)."""

    def __init__(self) -> None:
        self.chunks: list[dict[str, Any]] = []
        self.pings = 0
        self.closed = False
        self.disconnected = False

    def emit(self, chunk: dict[str, Any]) -> None:
        self.chunks.append(chunk)

    def ping(self) -> None:
        self.pings += 1

    def close(self) -> None:
        self.closed = True

    @property
    def types(self) -> list[str]:
        return [c["type"] for c in self.chunks]

    @property
    def text(self) -> str:
        return "".join(c["delta"] for c in self.chunks if c["type"] == "text-delta")


class ManualSleep:
    """부를 때마다 멈춰 있다가 `fire()`로 깨운다(`/chat`의 15초 `: ping` 시험). 받은 초를 적는다."""

    def __init__(self) -> None:
        self.seconds: list[float] = []
        self._waiting: list[asyncio.Future[None]] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)
        f: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiting.append(f)
        await f

    @property
    def pending(self) -> int:
        return sum(1 for f in self._waiting if not f.done())

    def fire(self) -> None:
        for f in self._waiting:
            if not f.done():
                f.set_result(None)
        self._waiting.clear()

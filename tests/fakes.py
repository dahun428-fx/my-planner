"""테스트용 가짜: 두뇌, 전송, sleep, 설정."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from my_planner.clock import FakeClock
from my_planner.config import PathsConfig, Settings
from my_planner.domain import RunContext
from my_planner.harness.brain import BrainResult
from my_planner.harness.dispatcher import Outbound


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

    async def run(self, prompt: str, *, session_id: str | None, run_ctx: RunContext) -> BrainResult:
        self.calls.append({"prompt": prompt, "session_id": session_id, "run_ctx": run_ctx})
        if not self.script:
            raise AssertionError("FakeBrain: 시나리오가 더 없다")
        turn = self.script.pop(0)
        for name, args in turn.tool_calls:
            if self.tools is None:
                raise AssertionError(f"FakeBrain: 도구 {name}를 부를 tools가 없다")
            out = getattr(self.tools, name)(run_ctx, **args)
            if inspect.isawaitable(out):
                await out
        if turn.delay:
            assert self.clock is not None, "delay에는 clock이 필요하다"
            until = self.clock.now() + timedelta(seconds=turn.delay)
            while self.clock.now() < until:
                await asyncio.sleep(0)
        return BrainResult(
            text=turn.text,
            session_id=turn.session_id,
            turns=1 + len(turn.tool_calls),
            tool_events=list(run_ctx.events),
            status=turn.status,  # type: ignore[arg-type]
            error=turn.error,
            resume_failed=turn.resume_failed,
            retry_at=turn.retry_at,
        )


class FakeSender:
    def __init__(self, *, fail: bool = False):
        self.sent: list[Outbound] = []
        self.typing_count = 0
        self.fail = fail

    async def send(self, out: Outbound) -> None:
        if self.fail:
            raise ConnectionError("fake send failure")
        self.sent.append(out)

    async def typing(self) -> None:
        self.typing_count += 1


def fake_sleep(clock: FakeClock):
    """실제로 기다리지 않는 sleep: 시계만 움직이고 한 번 양보한다."""

    async def sleep(seconds: float) -> None:
        clock.advance(timedelta(seconds=seconds))
        await asyncio.sleep(0)

    return sleep


def make_settings(root: Path, **overrides: Any) -> Settings:
    return Settings(
        telegram_bot_token="123:test-token",
        owner_telegram_id=42,
        paths=PathsConfig.for_root(root),
        **overrides,
    )

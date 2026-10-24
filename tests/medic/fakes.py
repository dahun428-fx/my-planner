"""medic 시험용 가짜. 파일시스템은 tmp_path를 쓴다."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, minutes: float = 0, seconds: float = 0, hours: float = 0) -> None:
        self._now += timedelta(hours=hours, minutes=minutes, seconds=seconds)


@dataclass
class FakeResponse:
    status: int = 200
    body: Any = None


@dataclass
class FakeRequest:
    method: str
    path: str
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)


class FakeHttp:
    """(메서드, 경로)별 응답 큐. 큐가 비면 마지막 응답을 되풀이하고, 없으면 404."""

    def __init__(self) -> None:
        self._queues: dict[tuple[str, str], deque[FakeResponse | Exception]] = defaultdict(deque)
        self._last: dict[tuple[str, str], FakeResponse | Exception] = {}
        self.requests: list[FakeRequest] = []

    def queue(self, method: str, path: str, *responses: FakeResponse | Exception) -> None:
        self._queues[(method.upper(), path)].extend(responses)

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        key = (method.upper(), path)
        self.requests.append(FakeRequest(key[0], path, body, dict(headers or {})))
        q = self._queues[key]
        item = q.popleft() if q else self._last.get(key, FakeResponse(404))
        self._last[key] = item
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class ShellCall:
    args: list[str]
    cwd: Path
    timeout: int
    env: dict[str, str] | None


class FakeShell:
    """명령(앞부분 일치) -> (returncode, stdout) 규칙. 규칙 없으면 (0, "").

    규칙에 결과 목록을 주면 호출마다 하나씩 꺼내고 마지막 값을 되풀이한다.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[tuple[str, ...], list[tuple[int, str]]]] = []
        self.calls: list[ShellCall] = []

    @property
    def commands(self) -> list[list[str]]:
        return [c.args for c in self.calls]

    def on(
        self,
        *prefix: str,
        returns: tuple[int, str] | list[tuple[int, str]] = (0, ""),
    ) -> None:
        results = returns if isinstance(returns, list) else [returns]
        self.rules.append((prefix, list(results)))

    def missing(self, exe: str) -> None:
        """실행 파일이 없는 것처럼 127을 돌려준다."""
        self.on(exe, returns=(127, f"{exe} not found"))

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        self.calls.append(ShellCall(list(args), cwd, timeout, env))
        for prefix, results in reversed(self.rules):
            if tuple(args[: len(prefix)]) == prefix:
                return results.pop(0) if len(results) > 1 else results[0]
        return 0, ""


SCHEDULE = {
    "morning_brief": {"weekday": "09:00", "weekend": "10:00"},
    "evening_checkin": {"weekday": "17:30", "weekend": "18:00"},
    "review": {"week": {"day": "sun", "time": "18:00"}},
}


def make_config(root: Path | None = None, **overrides: Any) -> Any:
    """config.toml의 실제 [schedule] 모양을 가진 MedicConfig."""
    from datetime import time

    from my_planner_medic.config import MedicConfig

    values: dict[str, Any] = {
        "root": root or Path("/repo"),
        "enabled": True,
        "api_base": "http://127.0.0.1:8787/api/v1",
        "api_enabled": True,
        "api_token": None,
        "github_token": None,
        "telegram_token": None,
        "owner_telegram_id": None,
        "timezone": "Asia/Seoul",
        "day_boundary": time(4, 0),
        "schedule": SCHEDULE,
    }
    values.update(overrides)
    return MedicConfig(**values)

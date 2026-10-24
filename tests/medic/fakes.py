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


class FakeShell:
    """명령(앞부분 일치) -> (returncode, stdout) 규칙. 규칙 없으면 (0, "")."""

    def __init__(self) -> None:
        self.rules: list[tuple[tuple[str, ...], tuple[int, str]]] = []
        self.calls: list[list[str]] = []

    def on(self, *prefix: str, returns: tuple[int, str] = (0, "")) -> None:
        self.rules.append((prefix, returns))

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        self.calls.append(list(args))
        for prefix, result in reversed(self.rules):
            if tuple(args[: len(prefix)]) == prefix:
                return result
        return 0, ""

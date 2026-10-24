"""medic 실행 루프 (스펙 5장). 가짜 시계와 가짜 부품으로 간격·종료 코드를 본다."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from my_planner_medic import main as main_mod
from my_planner_medic.main import Parts, run

from .fakes import FakeClock, make_config

T0 = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)


class RecWatcher:
    def __init__(self, events: list[tuple[str, float]], clock: FakeClock, boom: bool = False) -> None:
        self.events, self.clock, self.boom = events, clock, boom

    def _at(self) -> float:
        return (self.clock.now() - T0).total_seconds()

    def tick(self) -> None:
        self.events.append(("watcher", self._at()))
        if self.boom:
            raise RuntimeError("secret ghp_TOPSECRET in message")

    def heartbeat(self) -> None:
        self.events.append(("heartbeat", self._at()))


class RecUpdater:
    def __init__(self, events: list[tuple[str, float]], clock: FakeClock, update_at: float | None = None) -> None:
        self.events, self.clock, self.update_at = events, clock, update_at
        self.self_updated = False

    def _at(self) -> float:
        return (self.clock.now() - T0).total_seconds()

    def recover_on_start(self) -> None:
        self.events.append(("recover", self._at()))

    def tick(self) -> None:
        self.events.append(("updater", self._at()))
        if self.update_at is not None and self._at() >= self.update_at:
            self.self_updated = True


def harness(tmp_path: Path, *, enabled: bool = True, update_at: float | None = None, boom: bool = False,
            horizon: float = 600) -> tuple[Any, FakeClock, list[tuple[str, float]], Any]:
    clock = FakeClock(T0)
    events: list[tuple[str, float]] = []
    cfg = make_config(tmp_path, enabled=enabled)
    parts = Parts(RecWatcher(events, clock, boom), RecUpdater(events, clock, update_at), lambda: None)

    def go() -> int:
        return run(
            cfg, clock=clock, sleep=lambda s: clock.advance(seconds=s),
            stop=lambda: (clock.now() - T0).total_seconds() >= horizon, build=lambda c, k: parts,
        )

    return go, clock, events, cfg


def test_run_calls_recover_first_then_ticks_on_intervals(tmp_path: Path) -> None:
    go, _, events, _ = harness(tmp_path)
    assert go() == 0
    assert events[0] == ("recover", 0)
    assert [t for n, t in events if n == "watcher"] == [0, 120, 240, 360, 480]
    assert [t for n, t in events if n == "updater"] == [0, 300]


def test_run_exits_3_after_medic_self_update(tmp_path: Path) -> None:
    go, _, events, _ = harness(tmp_path, update_at=300)
    assert go() == 3
    assert [t for n, t in events if n == "updater"] == [0, 300]
    assert max(t for _, t in events) == 300  # 끝낸 뒤에는 더 돌지 않는다


def test_disabled_only_heartbeats(tmp_path: Path) -> None:
    go, _, events, _ = harness(tmp_path, enabled=False)
    assert go() == 0
    assert {n for n, _ in events} <= {"recover", "heartbeat"}
    assert ("heartbeat", 0) in events


def test_tick_errors_are_swallowed_and_message_not_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    go, _, events, _ = harness(tmp_path, boom=True)
    with caplog.at_level("INFO"):
        assert go() == 0
    assert [t for n, t in events if n == "updater"] == [0, 300]  # watcher가 죽어도 루프는 산다
    assert "RuntimeError" in caplog.text and "TOPSECRET" not in caplog.text


def test_single_instance_lock(tmp_path: Path) -> None:
    first = main_mod.acquire_lock(tmp_path / "state" / "medic.lock")
    assert first is not None
    try:
        assert main_mod.acquire_lock(tmp_path / "state" / "medic.lock") is None
    finally:
        first.close()
    again = main_mod.acquire_lock(tmp_path / "state" / "medic.lock")
    assert again is not None
    again.close()


def test_run_returns_0_without_ticking_when_lock_is_held(tmp_path: Path) -> None:
    go, _, events, cfg = harness(tmp_path)
    held = main_mod.acquire_lock(cfg.root / "state" / "medic.lock")
    try:
        assert go() == 0
    finally:
        assert held is not None
        held.close()
    assert events == []


def test_build_fills_deployed_sha_from_git_head(tmp_path: Path) -> None:
    from my_planner_medic.store import MedicStore

    from .fakes import FakeShell

    sha = "c" * 40
    shell = FakeShell()
    shell.on("git", "rev-parse", "HEAD", returns=(0, sha + "\n"))
    cfg = make_config(tmp_path, github_token="ghp_TOPSECRET")
    parts = main_mod.build(cfg, FakeClock(T0), shell=shell)
    assert MedicStore(tmp_path / "state" / "medic.db").kv_get("deployed_sha") == sha
    parts.close()


def test_build_keeps_existing_deployed_sha(tmp_path: Path) -> None:
    from my_planner_medic.store import MedicStore

    from .fakes import FakeShell

    store = MedicStore(tmp_path / "state" / "medic.db")
    store.kv_set("deployed_sha", "a" * 40)
    store.close()
    shell = FakeShell()
    shell.on("git", "rev-parse", "HEAD", returns=(0, "c" * 40 + "\n"))
    main_mod.build(make_config(tmp_path), FakeClock(T0), shell=shell).close()
    assert MedicStore(tmp_path / "state" / "medic.db").kv_get("deployed_sha") == "a" * 40

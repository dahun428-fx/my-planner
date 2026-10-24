from __future__ import annotations

import logging
from pathlib import Path

import pytest

from my_planner_medic.http import UrllibHttp
from my_planner_medic.notify import Notifier
from my_planner_medic.store import MedicStore

from .fakes import FakeClock, make_config
from .test_notify import MON

SECRET = "TG-SECRET-123"


def test_failed_request_never_logs_a_path_secret(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        status, _, _ = UrllibHttp().request("POST", f"http://127.0.0.1:1/bot{SECRET}/sendMessage", json={"a": 1})
    assert status == 0
    assert "http_failed" in caplog.text  # 실패는 남기되
    assert SECRET not in caplog.text  # 토큰은 없다


def test_notifier_with_real_http_leaks_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import my_planner_medic.notify as notify_mod

    monkeypatch.setattr(notify_mod, "TELEGRAM", "http://127.0.0.1:1/bot{token}/sendMessage")
    cfg = make_config(
        tmp_path, api_enabled=False, telegram_token=SECRET, owner_telegram_id="42"
    )
    store = MedicStore(tmp_path / "state" / "medic.db")
    n = Notifier(cfg, store, UrllibHttp(), FakeClock(MON))
    with caplog.at_level(logging.DEBUG):
        n.gave_up("fp", False, "u", direct=True)
        n.fixed("t", "u")
    assert SECRET not in caplog.text
    assert all(SECRET not in t for _, t in store.spilled_notices())
    assert SECRET not in repr(cfg)

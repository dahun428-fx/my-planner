from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from my_planner_medic.notify import Notifier
from my_planner_medic.store import MedicStore

from .fakes import FakeClock, FakeHttp, FakeResponse, make_config

BE = "/api/v1/internal/notify"
TG = "/botTG-SECRET/sendMessage"
MON = datetime(2026, 10, 26, 1, 0, tzinfo=UTC)  # 월 10:00 KST (논리적 날짜 10-26)


def make(tmp_path: Path, **cfg: object) -> tuple[Notifier, FakeHttp, FakeClock, MedicStore]:
    clock = FakeClock(MON)
    http = FakeHttp()
    http.queue("POST", BE, FakeResponse(200, {"channel": "app"}))
    http.queue("POST", TG, FakeResponse(200, {"ok": True}))
    values: dict[str, object] = {
        "api_token": "a" * 43, "telegram_token": "TG-SECRET", "owner_telegram_id": "42",
    }
    values.update(cfg)
    config = make_config(tmp_path, **values)
    store = MedicStore(tmp_path / "state" / "medic.db")
    return Notifier(config, store, http, clock), http, clock, store


def test_fixed_goes_through_be_once(tmp_path: Path) -> None:
    n, http, _, _ = make(tmp_path)
    n.fixed("할 일 목록 오류 고침", "https://github.com/o/r/pull/7")
    sent = http.calls("POST", BE)
    assert len(sent) == 1
    assert sent[0].json == {
        "text": "🔧 자동으로 고쳤어요: 할 일 목록 오류 고침. https://github.com/o/r/pull/7",
        "kind": "recovery",
    }
    assert sent[0].headers["Authorization"] == "Bearer " + "a" * 43
    assert http.calls("POST", TG) == []


def test_be_down_falls_back_to_telegram(tmp_path: Path) -> None:
    n, http, _, _ = make(tmp_path)
    http.clear("POST", BE)
    http.queue("POST", BE, FakeResponse(0))
    n.gave_up("be:KeyError x.py:f", True, "https://github.com/o/r/issues/3")
    assert len(http.calls("POST", BE)) == 1
    tg = http.calls("POST", TG)
    assert len(tg) == 1
    assert tg[0].json == {
        "chat_id": "42",
        "text": "⚠️ 자동으로 못 고쳤어요: be:KeyError x.py:f. 지금은 이전 버전으로 돌려 둠. https://github.com/o/r/issues/3",
    }


def test_be_503_also_falls_back(tmp_path: Path) -> None:
    n, http, _, _ = make(tmp_path)
    http.clear("POST", BE)
    http.queue("POST", BE, FakeResponse(503, {"error": {"code": "unavailable"}}))
    n.fixed("t", "u")
    assert len(http.calls("POST", TG)) == 1


def test_direct_skips_be(tmp_path: Path) -> None:
    n, http, _, _ = make(tmp_path)
    n.gave_up("deploy:health", False, "https://github.com/o/r/issues/4", direct=True)
    assert http.calls("POST", BE) == []
    assert http.calls("POST", TG)[0].json["text"] == (
        "⚠️ 자동으로 못 고쳤어요: deploy:health. 지금은 그대로. https://github.com/o/r/issues/4"
    )


def test_undeliverable_never_raises_and_logs_no_secret(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    n, http, _, store = make(tmp_path)
    http.outage = 0
    with caplog.at_level(logging.DEBUG):
        n.fixed("t", "u")
        n.daily("더러운 작업 폴더", "dirty_tree")
    assert store.spilled_notices() == [(1, "🔧 자동으로 고쳤어요: t. u")]  # daily는 쌓지 않고 다음에 다시
    assert "TG-SECRET" not in caplog.text and "a" * 43 not in caplog.text


def test_no_telegram_config_spills_when_be_down(tmp_path: Path) -> None:
    n, http, _, store = make(tmp_path, telegram_token=None, owner_telegram_id=None)
    http.clear("POST", BE)
    http.queue("POST", BE, FakeResponse(0))
    n.fixed("t", "u")
    assert http.calls("POST", TG) == []
    assert len(store.spilled_notices()) == 1


def test_sixth_notice_spills_and_flushes_after_morning_run(tmp_path: Path) -> None:
    n, http, clock, store = make(tmp_path)
    for i in range(5):
        n.fixed(f"고침{i}", f"u{i}")
    assert len(http.calls("POST", BE)) == 5
    n.fixed("고침5", "u5")  # 6번째: 쌓인다
    n.gave_up("fp7", False, "u7")  # 7번째도
    assert len(http.calls("POST", BE)) == 5
    assert len(store.spilled_notices()) == 2
    n.flush_spill()  # 월 10:00: 아직 아침 회차 전(화 09:00)
    assert len(http.calls("POST", BE)) == 5
    clock.advance(hours=22, minutes=30)  # 화 08:30 KST
    n.flush_spill()
    assert len(http.calls("POST", BE)) == 5
    clock.advance(minutes=31)  # 화 09:01 KST
    n.flush_spill()
    sent = http.calls("POST", BE)
    assert len(sent) == 6
    text = sent[-1].json["text"]
    assert text.startswith("자동 복구 알림 2개: ")
    assert "고침5" in text and "fp7" in text and "\n" not in text
    assert len(text) <= 500
    n.flush_spill()
    assert len(http.calls("POST", BE)) == 6
    assert store.spilled_notices() == []


def test_spill_waits_for_weekend_morning(tmp_path: Path) -> None:
    n, http, clock, _ = make(tmp_path)
    clock.advance(hours=4 * 24 + 0)  # 금 10:00 KST (10-30)
    for i in range(6):
        n.fixed(f"t{i}", "u")
    clock.advance(hours=23)  # 토 09:00 KST: 주말 아침은 10:00
    n.flush_spill()
    assert len(http.calls("POST", BE)) == 5
    clock.advance(minutes=61)
    n.flush_spill()
    assert len(http.calls("POST", BE)) == 6


def test_daily_key_once_per_logical_date(tmp_path: Path) -> None:
    n, http, clock, _ = make(tmp_path)
    n.daily("작업 폴더가 더러워요", "dirty_tree")
    n.daily("작업 폴더가 더러워요", "dirty_tree")
    n.daily("다른 알림", "ff_failed")
    assert len(http.calls("POST", BE)) == 2
    clock.advance(hours=17, minutes=59)  # 화 03:59 KST: 아직 월요일
    n.daily("작업 폴더가 더러워요", "dirty_tree")
    assert len(http.calls("POST", BE)) == 2
    clock.advance(minutes=2)  # 화 04:01 KST
    n.daily("작업 폴더가 더러워요", "dirty_tree")
    assert len(http.calls("POST", BE)) == 3


def test_daily_counts_toward_cap(tmp_path: Path) -> None:
    n, http, _, store = make(tmp_path)
    for i in range(6):
        n.daily(f"알림{i}", f"k{i}")
    assert len(http.calls("POST", BE)) == 5
    assert [t for _, t in store.spilled_notices()] == ["알림5"]
    n.daily("알림5", "k5")  # 쌓인 키도 오늘은 다시 쌓지 않는다
    assert len(store.spilled_notices()) == 1


def test_daily_retries_after_delivery_failure(tmp_path: Path) -> None:
    n, http, _, _ = make(tmp_path)
    http.outage = 0
    n.daily("x", "k")
    http.outage = None
    n.daily("x", "k")
    assert len(http.calls("POST", BE)) == 2  # 첫 시도(실패), 다시 시도(성공)


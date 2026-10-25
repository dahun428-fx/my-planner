"""일정 정리 알림 판정·보내기 (SP9b 스펙 1~4장, 8장, 계획 D1a). 가짜 시계, 내용은 꾸며 낸 것이다.

시험 날짜 2026-10-26(월)~2026-10-28(수). 시각은 모두 KST(`kst`)로 쓴다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime, time, timedelta

import pytest
from fakes import FakePushSender, FakeSender, make_settings
from test_dispatcher_messages import kst
from test_event_reminders import LONG_AGO, _delivery, make

from my_planner.clock import FakeClock
from my_planner.config import DigestConfig, ScheduleConfig, load_settings
from my_planner.loop.digests import (
    DIGEST_KINDS,
    DIGEST_LATE_MAX,
    RANGES,
    STEP_MIN,
    DigestSetting,
    PendingDigest,
    digest_text,
    judge_digests,
    parse_digest_settings,
    send_digests,
    validate_digest_time,
)
from my_planner.store.repos.events import EventsRepo
from my_planner.store.repos.state import DIGEST_LAST_KEY, DIGEST_SETTINGS_KEY, StateRepo

TZ = "Asia/Seoul"
MON = date(2026, 10, 26)
TUE = date(2026, 10, 27)
WED = date(2026, 10, 28)
BOUNDARY = time(4, 0)
DEFAULTS = DigestConfig()
ON = {"morning": DigestSetting(True, time(7, 30)), "night": DigestSetting(True, time(21, 30))}


@pytest.fixture
def events(conn):
    return EventsRepo(conn, FakeClock(LONG_AGO), TZ)


@pytest.fixture
def st(conn):
    return StateRepo(conn, FakeClock(LONG_AGO))


def settings(**kw):
    out = dict(ON)
    for k, v in kw.items():
        out[k] = v
    return out


def judge(events, st, last_seen, now, s=None):
    return judge_digests(last_seen_at=last_seen, now=now, settings=s or ON, events=events, state=st, tz=TZ,
                         day_boundary=BOUNDARY)


def tick(at, gap=timedelta(minutes=1)):
    """`at`을 지나는 1분 tick: (last_seen, now)."""
    return at - gap + timedelta(seconds=30), at + timedelta(seconds=30)


# --- 판정: 정시, 늦게, 너무 늦게 ---


def test_on_time_gap_1m_sends_morning(events, st):
    make(events, title="팀 회의", d=MON, at="09:00")
    make(events, title="치과", d=MON, at="14:00")
    make(events, title="휴가", d=MON, all_day=True)
    (p,) = judge(events, st, *tick(kst(2026, 10, 26, 7, 30)))
    assert (p.kind, p.date, p.title) == ("morning", MON, "오늘 일정 3개")
    assert p.body == "하루 종일 휴가\n09:00 팀 회의\n14:00 치과"
    assert p.url == "/schedule/?date=2026-10-26"
    assert p.until == kst(2026, 10, 27, 4, 0).astimezone(UTC)  # 판정한 now의 다음 04:00
    assert st.get_digest_last() == {"morning": MON, "night": None}


def test_on_time_night_carries_tomorrow(events, st):
    make(events, title="치과", d=TUE, at="10:00")
    make(events, title="오늘 것", d=MON, at="22:00")
    (p,) = judge(events, st, *tick(kst(2026, 10, 26, 21, 30)))
    assert (p.kind, p.date, p.title, p.body) == ("night", TUE, "내일 일정 1개", "10:00 치과")
    assert p.url == "/schedule/?date=2026-10-27"
    assert st.get_digest_last()["night"] == MON  # 슬롯 날짜(보낸 날)


def test_wake_1h_late_drops_started_and_counts_after(events, st, caplog):
    make(events, title="이른 회의", d=MON, at="08:00")
    make(events, title="점심", d=MON, at="12:00")
    make(events, title="휴가", d=MON, all_day=True)
    caplog.set_level(logging.INFO, logger="my_planner.loop.digests")
    (p,) = judge(events, st, kst(2026, 10, 26, 6, 0), kst(2026, 10, 26, 8, 30))
    assert p.title == "오늘 일정 2개" and p.body == "하루 종일 휴가\n12:00 점심"
    rec = [r for r in caplog.records if r.getMessage() == "digest_judged"]
    assert [(r.kind, r.date, r.count, r.outcome) for r in rec] == [("morning", "2026-10-26", 2, "late")]
    assert "점심" not in caplog.text and "휴가" not in caplog.text  # 제목은 로그에 남기지 않는다


def test_wake_3h_late_not_sent_but_recorded(events, st, caplog):
    make(events, title="점심", d=MON, at="12:00")
    caplog.set_level(logging.INFO, logger="my_planner.loop.digests")
    assert judge(events, st, kst(2026, 10, 26, 6, 0), kst(2026, 10, 26, 10, 30)) == []
    assert st.get_digest_last()["morning"] == MON
    assert [r.outcome for r in caplog.records if r.getMessage() == "digest_judged"] == ["too_late"]


def test_review_focus_1_night_wake_70m_late_130m_not(events, st):
    make(events, title="치과", d=TUE, at="10:00")
    (p,) = judge(events, st, kst(2026, 10, 26, 21, 20), kst(2026, 10, 26, 22, 40))  # 21:30 슬롯 70분 늦음
    assert p.kind == "night" and p.title == "내일 일정 1개"
    st.set(DIGEST_LAST_KEY, None)
    assert judge(events, st, kst(2026, 10, 26, 21, 20), kst(2026, 10, 26, 23, 40)) == []  # 130분 > 2시간
    assert DIGEST_LATE_MAX == timedelta(hours=2)


def test_late_limit_is_inclusive_2h(events, st):
    make(events, title="치과", d=TUE, at="10:00")
    assert len(judge(events, st, kst(2026, 10, 26, 21, 0), kst(2026, 10, 26, 23, 30))) == 1


def test_review_focus_2_night_23_slept_2250_woke_0030(events, st):
    make(events, title="새벽 기차", d=TUE, at="00:10")  # 시작이 지났다: 빠진다
    make(events, title="치과", d=TUE, at="10:00")
    s = settings(night=DigestSetting(True, time(23, 0)))
    (p,) = judge(events, st, kst(2026, 10, 26, 22, 50), kst(2026, 10, 27, 0, 30), s)
    assert (p.kind, p.date, p.title, p.body) == ("night", TUE, "내일 일정 1개", "10:00 치과")
    assert st.get_digest_last()["night"] == MON  # d - 1 슬롯
    assert p.until == kst(2026, 10, 27, 4, 0).astimezone(UTC)  # 00:30은 아직 논리적 어제


def test_review_focus_3_same_minute_twice_sends_once(events, st):
    make(events, title="치과", d=MON, at="14:00")
    last, now = tick(kst(2026, 10, 26, 7, 30))
    assert len(judge(events, st, last, now)) == 1
    assert judge(events, st, last, now) == []  # 재시작 직후 같은 창을 다시 봄
    assert judge(events, st, last + timedelta(seconds=10), now + timedelta(seconds=10)) == []


def test_review_focus_4_time_moved_later_today_sends_at_new_time(events, st):
    make(events, title="치과", d=MON, at="14:00")
    # 06:00에 아침 알림을 07:30 → 08:00으로 바꿨다
    s = settings(morning=DigestSetting(True, time(8, 0)))
    assert judge(events, st, *tick(kst(2026, 10, 26, 7, 30)), s) == []
    assert len(judge(events, st, *tick(kst(2026, 10, 26, 8, 0)), s)) == 1


def test_review_focus_4_already_judged_then_moved_later_not_sent(events, st):
    make(events, title="치과", d=MON, at="14:00")
    assert len(judge(events, st, *tick(kst(2026, 10, 26, 7, 30)))) == 1
    s = settings(morning=DigestSetting(True, time(9, 0)))
    assert judge(events, st, *tick(kst(2026, 10, 26, 9, 0)), s) == []


def test_review_focus_5_all_skipped_not_sent(events, st, caplog):
    e = make(events, title="치과", d=MON, at="14:00")
    events.skip(e.id, MON)
    caplog.set_level(logging.INFO, logger="my_planner.loop.digests")
    assert judge(events, st, *tick(kst(2026, 10, 26, 7, 30))) == []
    assert st.get_digest_last()["morning"] == MON  # 날짜는 적는다
    assert [r.outcome for r in caplog.records if r.getMessage() == "digest_judged"] == ["empty"]


def test_skipped_occurrence_not_counted(events, st):
    e = make(events, title="운동", d=MON, at="06:00", repeat="daily")
    make(events, title="치과", d=TUE, at="14:00")
    events.skip(e.id, TUE)
    (p,) = judge(events, st, *tick(kst(2026, 10, 26, 21, 30)))
    assert p.title == "내일 일정 1개" and p.body == "14:00 치과"


def test_no_events_not_sent(events, st):
    assert judge(events, st, *tick(kst(2026, 10, 26, 7, 30))) == []
    assert st.get_digest_last()["morning"] == MON


def test_off_not_sent_and_not_recorded(events, st):
    make(events, title="치과", d=MON, at="14:00")
    s = settings(morning=DigestSetting(False, time(7, 30)))
    assert judge(events, st, *tick(kst(2026, 10, 26, 7, 30)), s) == []
    assert st.get_digest_last()["morning"] is None


def test_clock_backwards_or_same_time_not_judged(events, st):
    make(events, title="치과", d=MON, at="14:00")
    now = kst(2026, 10, 26, 7, 30)
    assert judge(events, st, now + timedelta(minutes=5), now) == []
    assert judge(events, st, now, now) == []
    assert st.get_digest_last() == {"morning": None, "night": None}


def test_slot_not_in_window_not_judged(events, st):
    make(events, title="치과", d=MON, at="14:00")
    assert judge(events, st, *tick(kst(2026, 10, 26, 7, 29))) == []  # 07:30 슬롯이 아직 창 밖
    assert judge(events, st, kst(2026, 10, 26, 7, 30), kst(2026, 10, 26, 7, 31)) == []  # at == last_seen: 이미 지난 tick
    assert st.get_digest_last()["morning"] is None


def test_late_night_after_midnight_title_still_tomorrow(events, st):
    make(events, title="휴가", d=TUE, all_day=True)  # 하루 종일은 남는다
    s = settings(night=DigestSetting(True, time(23, 50)))
    (p,) = judge(events, st, kst(2026, 10, 26, 23, 40), kst(2026, 10, 27, 1, 0), s)
    assert (p.title, p.body, p.date) == ("내일 일정 1개", "하루 종일 휴가", TUE)


def test_both_kinds_same_tick(events, st):
    make(events, title="치과", d=MON, at="14:00")
    make(events, title="기차", d=TUE, at="09:00")
    s = settings(morning=DigestSetting(True, time(11, 50)), night=DigestSetting(True, time(18, 0)))
    got = judge(events, st, kst(2026, 10, 26, 11, 0), kst(2026, 10, 26, 18, 0), s)
    assert [p.kind for p in got] == ["night"]  # 아침은 6시간 넘게 늦음
    assert st.get_digest_last() == {"morning": MON, "night": MON}


# --- 본문 ---


def _occ(events, d):
    return events.occurrences(d, d)


def test_text_three_lines_then_more(events):
    for i, at in enumerate(("09:00", "10:00", "11:00", "12:00", "13:00")):
        make(events, title=f"일정{i}", d=MON, at=at)
    title, body = digest_text("morning", MON, _occ(events, MON), now=kst(2026, 10, 26, 7, 30), late=False, tz=TZ)
    assert title == "오늘 일정 5개"
    assert body == "09:00 일정0\n10:00 일정1\n11:00 일정2\n외 2개"


def test_text_exactly_three_has_no_more_line(events):
    for i, at in enumerate(("09:00", "10:00", "11:00")):
        make(events, title=f"일정{i}", d=MON, at=at)
    _, body = digest_text("morning", MON, _occ(events, MON), now=kst(2026, 10, 26, 7, 30), late=False, tz=TZ)
    assert body.count("\n") == 2 and "외" not in body


def test_text_all_day_first_and_title_cut_at_20(events):
    make(events, title="가" * 21, d=MON, at="08:00")
    make(events, title="나" * 20, d=MON, all_day=True)
    _, body = digest_text("morning", MON, _occ(events, MON), now=kst(2026, 10, 26, 7, 30), late=False, tz=TZ)
    assert body == f"하루 종일 {'나' * 20}\n08:00 {'가' * 20}…"


def test_text_none_when_empty_or_all_started(events):
    make(events, title="치과", d=MON, at="08:00")
    assert digest_text("morning", MON, [], now=kst(2026, 10, 26, 7, 30), late=False, tz=TZ) is None
    assert digest_text("morning", MON, _occ(events, MON), now=kst(2026, 10, 26, 9, 0), late=True, tz=TZ) is None
    # 정시에는 빼지 않는다
    assert digest_text("morning", MON, _occ(events, MON), now=kst(2026, 10, 26, 9, 0), late=False, tz=TZ) is not None


def test_text_ignores_other_days_and_skipped(events):
    make(events, title="어제", d=date(2026, 10, 25), at="09:00")
    e = make(events, title="건너뜀", d=MON, at="10:00")
    events.skip(e.id, MON)
    occs = events.occurrences(date(2026, 10, 25), MON, include_skipped=True)
    assert digest_text("morning", MON, occs, now=kst(2026, 10, 26, 7, 30), late=False, tz=TZ) is None


def test_digest_copy_has_no_banned_words(events):
    from my_planner.tools.ui import banned_words

    for i, at in enumerate(("09:00", "10:00", "11:00", "12:00")):
        make(events, title=f"일정{i}", d=MON, at=at)
    make(events, title="휴가", d=MON, all_day=True)
    copy = []
    for kind in DIGEST_KINDS:
        title, body = digest_text(kind, MON, _occ(events, MON), now=kst(2026, 10, 26, 7, 30), late=False, tz=TZ)
        copy += [title, body]
    words = banned_words()
    assert [(c, w) for c in copy for w in words if w in c] == []


# --- 시각 검사와 저장 ---


def test_validate_digest_time():
    assert validate_digest_time("morning", "04:00") == time(4, 0)
    assert validate_digest_time("morning", "11:50") == time(11, 50)
    assert validate_digest_time("night", "18:00") == time(18, 0)
    assert validate_digest_time("night", "23:50") == time(23, 50)
    assert validate_digest_time("night", time(21, 30)) == time(21, 30)
    for kind, v in (("morning", "03:50"), ("morning", "12:00"), ("morning", "07:35"), ("night", "17:50"),
                    ("night", "7:30"), ("night", "21:30:00"), ("night", 2130), ("night", None), ("morning", "ab:cd"),
                    ("night", "24:00"), ("morning", time(7, 30, 1)), ("noon", "12:00")):
        assert validate_digest_time(kind, v) is None, (kind, v)
    assert RANGES == {"morning": (time(4, 0), time(11, 50)), "night": (time(18, 0), time(23, 50))}
    assert STEP_MIN == 10


def test_parse_settings_defaults_and_fallbacks():
    want = {"morning": DigestSetting(True, time(7, 30)), "night": DigestSetting(True, time(21, 30))}
    for raw in (None, "", "not json", "[]", "3", json.dumps({"morning": "x"})):
        assert parse_digest_settings(raw, DEFAULTS) == want
    raw = json.dumps({"morning": {"on": False, "time": "08:00"}, "night": {"on": "yes", "time": "17:00"}})
    assert parse_digest_settings(raw, DEFAULTS) == {
        "morning": DigestSetting(False, time(8, 0)), "night": DigestSetting(True, time(21, 30)),
    }
    cfg = DigestConfig(morning=time(6, 0), night_on=False)
    assert parse_digest_settings(None, cfg) == {
        "morning": DigestSetting(True, time(6, 0)), "night": DigestSetting(False, time(21, 30)),
    }


def test_review_focus_6_broken_settings_in_runner_state(st):
    st.set(DIGEST_SETTINGS_KEY, "{broken")
    assert st.get_digest_settings(DEFAULTS) == {
        "morning": DigestSetting(True, time(7, 30)), "night": DigestSetting(True, time(21, 30)),
    }


def test_state_roundtrip(st):
    s = {"morning": DigestSetting(False, time(8, 10)), "night": DigestSetting(True, time(23, 0))}
    st.set_digest_settings(s)
    assert json.loads(st.get(DIGEST_SETTINGS_KEY)) == {
        "morning": {"on": False, "time": "08:10"}, "night": {"on": True, "time": "23:00"},
    }
    assert st.get_digest_settings(DEFAULTS) == s
    assert st.get_digest_last() == {"morning": None, "night": None}
    st.set_digest_last("night", MON)
    assert st.get_digest_last() == {"morning": None, "night": MON}
    st.set_digest_last("morning", TUE)
    assert json.loads(st.get(DIGEST_LAST_KEY)) == {"night": "2026-10-26", "morning": "2026-10-27"}
    st.set(DIGEST_LAST_KEY, json.dumps({"morning": "bad", "night": 3}))
    assert st.get_digest_last() == {"morning": None, "night": None}
    st.set(DIGEST_LAST_KEY, "{broken")
    assert st.get_digest_last() == {"morning": None, "night": None}
    st.set_digest_last("morning", WED)  # 깨진 값 위에도 적는다
    assert st.get_digest_last() == {"morning": WED, "night": None}


def test_digest_config_checks_range_and_step():
    assert DigestConfig() == DigestConfig(morning=time(7, 30), night=time(21, 30), morning_on=True, night_on=True)
    for kw in ({"morning": time(7, 35)}, {"morning": time(12, 0)}, {"night": time(17, 50)}, {"night": time(3, 0)}):
        with pytest.raises(ValueError):
            DigestConfig(**kw)
    assert ScheduleConfig().digest == DigestConfig()


def test_config_toml_has_schedule_digest(tmp_path, monkeypatch):
    from pathlib import Path

    for k in ("TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID"):
        monkeypatch.delenv(k, raising=False)
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "config.toml").write_text((repo / "config.toml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=123:fake\nOWNER_TELEGRAM_ID=42\n", encoding="utf-8")
    s = load_settings(tmp_path)
    assert s.schedule.digest == DigestConfig(morning=time(7, 30), night=time(21, 30), morning_on=True, night_on=True)
    assert "[schedule.digest]" in (repo / "config.toml").read_text(encoding="utf-8")


# --- 보내기 ---


def _pending(until=None, body="하루 종일 휴가\n09:00 팀 회의"):
    return PendingDigest("morning", MON, "오늘 일정 2개", body, "/schedule/?date=2026-10-26",
                         until or kst(2026, 10, 27, 4, 0).astimezone(UTC))


class _Flaky:
    def __init__(self, results, now):
        self.results, self.calls = list(results), []
        self.clock = FakeClock(now)

    async def deliver_digest(self, kind, day, title, body, url, *, ttl_s):
        self.calls.append((kind, day, title, body, url, ttl_s))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _sleeper(d, sleeps):
    async def sleep(s):
        sleeps.append(s)
        d.clock.advance(seconds=s)

    return sleep


async def test_send_ttl_is_until_minus_now_clamped():
    d = _Flaky(["app"], kst(2026, 10, 26, 7, 30))
    await send_digests([_pending()], d)
    assert d.calls == [("morning", MON, "오늘 일정 2개", "하루 종일 휴가\n09:00 팀 회의", "/schedule/?date=2026-10-26",
                        int(timedelta(hours=20, minutes=30).total_seconds()))]
    d = _Flaky(["app"], kst(2026, 10, 27, 3, 50))  # 10분 남음 → 1시간
    await send_digests([_pending()], d)
    assert d.calls[0][-1] == 60 * 60
    d = _Flaky(["app"], kst(2026, 10, 25, 3, 0))  # 이틀 가까이 → 하루
    await send_digests([_pending()], d)
    assert d.calls[0][-1] == 24 * 60 * 60


async def test_send_retries_then_succeeds():
    d = _Flaky([None, RuntimeError("down"), "telegram"], kst(2026, 10, 26, 7, 30))
    sleeps: list[float] = []
    await send_digests([_pending()], d, sleep=_sleeper(d, sleeps))
    assert len(d.calls) == 3 and sleeps == [20.0, 60.0]


async def test_send_gives_up_with_digest_failed_log(caplog):
    d = _Flaky([None, None, None], kst(2026, 10, 26, 7, 30))
    sleeps: list[float] = []
    caplog.set_level(logging.INFO, logger="my_planner.loop.digests")
    await send_digests([_pending()], d, sleep=_sleeper(d, sleeps))
    assert len(d.calls) == 3
    (rec,) = [r for r in caplog.records if r.getMessage() == "digest_failed"]
    assert (rec.kind, rec.date) == ("morning", "2026-10-26")
    assert "팀 회의" not in caplog.text


async def test_no_retry_after_until():
    d = _Flaky([None, "app"], kst(2026, 10, 27, 3, 59) + timedelta(seconds=50))
    sleeps: list[float] = []
    await send_digests([_pending()], d, sleep=_sleeper(d, sleeps))
    assert len(d.calls) == 1 and sleeps == [20.0]


async def test_cancelled_send_reraises():
    started = asyncio.Event()

    class Slow:
        clock = FakeClock(kst(2026, 10, 26, 7, 30))

        async def deliver_digest(self, *a, **k):
            started.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(send_digests([_pending()], Slow()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_send_through_real_delivery_push_and_fallback(tmp_path, conn):
    push = FakePushSender()
    delivery, tg = _delivery(tmp_path, conn, push=push)
    await send_digests([_pending()], delivery)
    assert [c.payload for c in push.sent] == [{
        "type": "digest", "checkin_id": None, "title": "오늘 일정 2개", "body": "하루 종일 휴가\n09:00 팀 회의",
        "url": "/schedule/?date=2026-10-26", "tag": "digest:morning:2026-10-26",
    }]
    assert tg.sent == []
    push.always("https://push.example.invalid/sub/rem-fake", 410)
    delivery, tg = _delivery(tmp_path, conn, push=push)
    await send_digests([_pending()], delivery)
    assert [o.text for o in tg.sent] == ["오늘 일정 2개\n하루 종일 휴가\n09:00 팀 회의"]


async def test_judge_then_send_not_counted_anywhere(tmp_path, conn, events, st):
    make(events, title="치과", d=MON, at="14:00")
    pending = judge(events, st, *tick(kst(2026, 10, 26, 7, 30)))
    delivery, tg = _delivery(tmp_path, conn, telegram=FakeSender(), primary="telegram")
    await send_digests(pending, delivery)
    assert [o.text for o in tg.sent] == ["오늘 일정 1개\n14:00 치과"]
    usage = st.usage(MON)
    assert (usage.proactive_messages, usage.brain_calls) == (0, 0)
    assert conn.execute("SELECT COUNT(*) FROM event_reminders").fetchone()[0] == 0


def test_pending_until_is_utc(events, st):
    make(events, title="치과", d=MON, at="14:00")
    (p,) = judge(events, st, *tick(kst(2026, 10, 26, 7, 30)))
    assert p.until.tzinfo is UTC and isinstance(p.until, datetime)


def test_default_settings_have_digest(tmp_path):
    # config.toml 없이 만든 Settings에도 schedule.digest가 있다(러너가 tick마다 읽는다)
    assert make_settings(tmp_path).schedule.digest == DigestConfig()

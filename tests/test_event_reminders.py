"""일정 알림 1분 tick (SP9 스펙 5.3, 티켓 SP9-06). 가짜 시계, 내용은 꾸며 낸 것이다.

시험 날짜 2026-10-26(월)~2026-11-01(일). 시각은 모두 KST(`kst`)로 쓴다.
"""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from fakes import (
    FAKE_AUTH,
    FAKE_P256DH,
    FAKE_VAPID,
    FakePushSender,
    FakeSender,
    make_settings,
)
from test_dispatcher_messages import kst
from test_event_tools import Env as ToolEnv

from my_planner.clock import FakeClock, to_iso
from my_planner.config import LimitsConfig
from my_planner.harness.delivery import Delivery, reminder_payload
from my_planner.loop.reminders import (
    ReminderOutcome,
    remind_events,
    reminder_text,
    send_reminders,
)
from my_planner.loop.runner import Runner
from my_planner.store.repos.events import EventsRepo
from my_planner.store.repos.push import PushRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.state import NOTIFY_PRIMARY_KEY, PAUSE_UNTIL_KEY, StateRepo
from my_planner.tools.events import today_missed_reminders

TZ = "Asia/Seoul"
MON = date(2026, 10, 26)
TUE = date(2026, 10, 27)
LIMITS = LimitsConfig()
LONG_AGO = kst(2026, 10, 20, 9, 0)  # 일정을 만든 때: 모든 `remind_at`보다 앞이라 `updated_at` 규칙에 걸리지 않는다


@pytest.fixture
def events(conn):
    return EventsRepo(conn, FakeClock(LONG_AGO), TZ)


def make(events, *, title="치과", d=MON, at="14:00", remind=10, created=LONG_AGO, **kw):
    fields = {"title": title, "start_date": d, "origin": "user", "remind_min": remind, **kw}
    if kw.get("all_day"):
        fields["start_time"] = None
    else:
        fields["start_time"] = time.fromisoformat(at)
    return events.create(fields, created)


def rows(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT event_id, occurrence_date, outcome FROM event_reminders ORDER BY occurrence_date, event_id"
    )]


def judge(events, last_seen, now, limits=LIMITS):
    return remind_events(last_seen_at=last_seen, now=now, events=events, limits=limits)


def texts(pending):
    return [(p.title, p.body) for p in pending]


# --- R1 ---


def test_r1_on_time_gap_under_3m(conn, events):
    e = make(events)
    pending = judge(events, kst(2026, 10, 26, 13, 49) + timedelta(seconds=30), kst(2026, 10, 26, 13, 50) + timedelta(seconds=30))
    assert texts(pending) == [("치과", "14:00 (10분 뒤)")]
    assert pending[0].url == "/schedule/?date=2026-10-26"
    assert pending[0].outcome == ReminderOutcome(e.id, MON, "sent")
    assert rows(conn) == [(e.id, "2026-10-26", "sent")]


def test_gap_exactly_3m_is_not_wake(conn, events):
    make(events)
    pending = judge(events, kst(2026, 10, 26, 13, 47), kst(2026, 10, 26, 13, 50))
    assert [p.outcome.outcome for p in pending] == ["sent"]  # 늦은 알림("분 남았어요")이 아니다
    assert texts(pending) == [("치과", "14:00 (10분 뒤)")]


def test_remind_text_per_minutes(events):
    for remind, word in ((0, "지금이에요"), (10, "10분 뒤"), (30, "30분 뒤"), (60, "60분 뒤"), (1440, "내일")):
        e = make(events, remind=remind)
        (o,) = [o for o in events.occurrences(MON, MON) if o.event_id == e.id]
        assert reminder_text(o, kst(2026, 10, 26, 8, 0), False) == ("치과", f"14:00 ({word})")
    e = make(events, all_day=True, remind=0, d=TUE)
    (o,) = [o for o in events.occurrences(TUE, TUE) if o.event_id == e.id]
    assert reminder_text(o, kst(2026, 10, 27, 9, 0), False) == ("치과", "하루 종일 (오늘)")


# --- R2, R3, R4, R5 ---


def test_r2_gap_25m_sends_15_min_left(conn, events):
    make(events, remind=30)  # remind_at 13:30
    pending = judge(events, kst(2026, 10, 26, 13, 20), kst(2026, 10, 26, 13, 45))
    assert texts(pending) == [("치과", "14:00 (15분 남았어요)")]
    assert [p.outcome.outcome for p in pending] == ["late_sent"]
    assert rows(conn)[0][2] == "late_sent"


def test_r3_gap_50m_missed_no_push(conn, events):
    e = make(events)  # remind_at 13:50, 시작 14:00
    pending = judge(events, kst(2026, 10, 26, 13, 20), kst(2026, 10, 26, 14, 10))
    assert pending == []
    assert rows(conn) == [(e.id, "2026-10-26", "missed")]


def test_all_day_missed_only_after_the_day(conn, events):
    a = make(events, all_day=True, remind=0, d=MON)  # 09:00
    b = make(events, all_day=True, remind=0, d=TUE, title="휴가")
    # 월요일 낮에 깨어남: 월요일 하루 종일은 아직 안 지났다(늦은 알림), 화요일 것은 remind_at이 앞으로다
    pending = judge(events, kst(2026, 10, 26, 8, 0), kst(2026, 10, 26, 13, 0))
    assert [p.outcome.event_id for p in pending] == [a.id]
    # 화요일 아침에 깨어남: 월요일 것은 이미 판정했고, 화요일 것은 R2
    pending = judge(events, kst(2026, 10, 27, 8, 0), kst(2026, 10, 27, 9, 30))
    assert [(p.outcome.event_id, p.outcome.outcome) for p in pending] == [(b.id, "late_sent")]
    # 수요일 낮에 깨어나 화요일 것을 처음 본다면 missed(그날이 지났다)
    c = make(events, all_day=True, remind=0, d=date(2026, 10, 28), title="출장")
    pending = judge(events, kst(2026, 10, 28, 8, 0), kst(2026, 10, 29, 10, 0))
    assert pending == [] and (c.id, "2026-10-28", "missed") in rows(conn)


def _delivery(tmp_path, conn, *, push=None, telegram=None, primary="app", subscribe=True):
    clock = FakeClock(kst(2026, 10, 26, 14, 0))
    state = StateRepo(conn, clock)
    pushes = PushRepo(conn, clock)
    if subscribe:
        pushes.upsert("https://push.example.invalid/sub/rem-fake", FAKE_P256DH, FAKE_AUTH, None)
    state.set(NOTIFY_PRIMARY_KEY, primary)
    tg = telegram or FakeSender()

    async def inline(fn, *a, **k):
        return fn(*a, **k)

    d = Delivery(telegram=tg, push=push or FakePushSender(), pushes=pushes, state=state, clock=clock,
                 settings=make_settings(tmp_path, vapid=FAKE_VAPID), to_thread=inline)
    return d, tg


async def test_r4_failed(tmp_path, conn, events):
    e = make(events)
    pending = judge(events, kst(2026, 10, 26, 13, 49), kst(2026, 10, 26, 13, 50))
    push = FakePushSender()
    push.always("https://push.example.invalid/sub/rem-fake", 410)
    # 푸시를 받은 구독이 없으면 텔레그램으로 대신 간다: 보낸 것이다
    delivery, tg = _delivery(tmp_path, conn, push=push)
    await send_reminders(pending, delivery, events)
    assert [o.text for o in tg.sent] == ["치과 · 14:00 (10분 뒤)"]
    assert rows(conn) == [(e.id, "2026-10-26", "sent")]

    # 텔레그램도 안 되면 failed
    class Down(FakeSender):
        async def send(self, out):
            raise RuntimeError("down")

    delivery, tg = _delivery(tmp_path, conn, push=push, telegram=Down())
    await send_reminders(pending, delivery, events)
    assert rows(conn) == [(e.id, "2026-10-26", "failed")]


def test_r5_fourth_late_skipped(conn, events):
    for i, at in enumerate(("15:00", "15:10", "15:20", "15:30")):
        make(events, title=f"일정{i}", at=at, remind=60)  # remind_at 14:00, 14:10, 14:20, 14:30
    pending = judge(events, kst(2026, 10, 26, 13, 50), kst(2026, 10, 26, 14, 35))
    assert [p.title for p in pending] == ["일정0", "일정1", "일정2"]  # 가장 가까운 시작 순
    assert [r[2] for r in rows(conn)] == ["late_sent"] * 3 + ["skipped"]


def test_daily_cap_30_skipped(conn, events):
    cap = LimitsConfig(daily_event_reminders=30)
    for i in range(32):
        make(events, title=f"일정{i:02d}", at="14:00")  # 모두 13:50에 정시 알림
    pending = judge(events, kst(2026, 10, 26, 13, 49), kst(2026, 10, 26, 13, 50), cap)
    assert len(pending) == 30
    assert [r[2] for r in rows(conn)].count("skipped") == 2
    # 상한은 하루치다: 이미 보낸 수를 센다
    make(events, title="늦은 일정", at="15:00")
    assert judge(events, kst(2026, 10, 26, 14, 49), kst(2026, 10, 26, 14, 50), cap) == []
    assert rows(conn)[-1][2] == "skipped"


# --- updated_at 규칙, 7일, 하루 중복 ---


def test_one_day_before_late_says_hours(conn, events):
    make(events, d=TUE, remind=1440)  # remind_at 월 14:00, 시작 화 14:00
    pending = judge(events, kst(2026, 10, 26, 13, 0), kst(2026, 10, 27, 12, 0))
    assert texts(pending) == [("치과", "14:00 (2시간 남았어요)")]


def test_created_inside_gap_not_sent(conn, events):
    make(events, remind=30, created=kst(2026, 10, 26, 13, 40))  # remind_at 13:30이 만들기 전이다
    assert judge(events, kst(2026, 10, 26, 13, 20), kst(2026, 10, 26, 13, 50)) == []
    assert rows(conn) == []


def test_edit_just_before_remind_at_uses_new_time(conn, events):
    e = make(events, remind=30)  # 14:00, remind_at 14:30 아님: 13:30
    events.update(e.id, {"start_time": time(15, 0)}, kst(2026, 10, 26, 13, 29))
    assert judge(events, kst(2026, 10, 26, 13, 29), kst(2026, 10, 26, 13, 30)) == []  # 옛 시각으로 보내지 않는다
    assert rows(conn) == []
    pending = judge(events, kst(2026, 10, 26, 14, 29), kst(2026, 10, 26, 14, 30))
    assert texts(pending) == [("치과", "15:00 (30분 뒤)")]


def test_edit_after_decision_rejudges_new_time(conn, events):
    e = make(events, remind=30)
    judge(events, kst(2026, 10, 26, 13, 29), kst(2026, 10, 26, 13, 30))  # 13:30에 보냈다
    assert [r[2] for r in rows(conn)] == ["sent"]
    events.update(e.id, {"start_time": time(16, 0)}, kst(2026, 10, 26, 13, 40))  # 앞으로의 행을 지운다
    assert rows(conn) == []
    assert texts(judge(events, kst(2026, 10, 26, 15, 29), kst(2026, 10, 26, 15, 30))) == [("치과", "16:00 (30분 뒤)")]


def test_nine_day_gap_judges_seven_days_pushes_at_most_three(conn, events):
    daily = make(events, title="약", at="09:00", d=date(2026, 10, 20), repeat="daily")
    for i, at in enumerate(("14:00", "14:10", "14:20", "14:30")):
        make(events, title=f"오늘{i}", at=at, d=date(2026, 11, 4), remind=60, created=kst(2026, 10, 21, 9, 0))
    now = kst(2026, 11, 4, 13, 35)
    pending = judge(events, now - timedelta(days=9), now)
    got = rows(conn)
    missed = [r for r in got if r[2] == "missed"]
    assert [r[1] for r in missed] == [f"2026-10-{d}" for d in (29, 30, 31)] + ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
    assert all(r[0] == daily.id for r in missed)  # 10/28 이전은 판정도 기록도 없다
    assert len(pending) == 3 and {r[2] for r in got} == {"missed", "late_sent", "skipped"}
    assert [r[2] for r in got].count("skipped") == 1


def test_no_double_send_same_day(conn, events):
    make(events)
    first = judge(events, kst(2026, 10, 26, 13, 49), kst(2026, 10, 26, 13, 50))
    again = judge(events, kst(2026, 10, 26, 13, 49), kst(2026, 10, 26, 13, 50))
    wider = judge(events, kst(2026, 10, 26, 13, 0), kst(2026, 10, 26, 14, 30))
    assert len(first) == 1 and again == [] and wider == []
    assert len(rows(conn)) == 1


def test_skipped_day_and_deleted_event_not_sent(conn, events):
    a = make(events)
    b = make(events, title="지움")
    events.skip(a.id, MON)
    events.delete(b.id, kst(2026, 10, 26, 9, 0))
    assert judge(events, kst(2026, 10, 26, 13, 49), kst(2026, 10, 26, 13, 50)) == []


# --- 러너 ---


class _Dispatcher:
    def submit_run(self, run, merged, *, carried_ids=()):
        pass


def _runner(tmp_path, conn, now, last_seen, *, checkins=True, delivery=None):
    clock = FakeClock(now)
    state = StateRepo(conn, clock)
    state.set("installed_at", to_iso(LONG_AGO))
    state.set("last_seen_at", to_iso(last_seen))
    ev = EventsRepo(conn, clock, TZ)
    runner = Runner(clock=clock, settings=make_settings(tmp_path), runs=RunsRepo(conn, clock), state=state,
                    dispatcher=_Dispatcher(), checkins=checkins, events=ev, reminder_delivery=delivery)
    return runner, ev, state


async def test_sends_while_paused(tmp_path, conn):
    now = kst(2026, 10, 26, 13, 50)
    push = FakePushSender()
    delivery, _ = _delivery(tmp_path, conn, push=push)
    runner, ev, state = _runner(tmp_path, conn, now, now - timedelta(minutes=1), delivery=delivery)
    state.set(PAUSE_UNTIL_KEY, to_iso(now + timedelta(days=2)))
    make(ev)
    runner.tick()
    await _drain(runner)
    assert [c.payload["type"] for c in push.sent] == ["reminder"]
    assert push.sent[0].payload["url"] == "/schedule/?date=2026-10-26"
    assert rows(conn)[0][2] == "sent"


async def _drain(runner):
    import asyncio

    await asyncio.gather(*runner.reminder_tasks)


async def test_not_counted_in_proactive_limit(tmp_path, conn):
    now = kst(2026, 10, 26, 13, 50)
    delivery, _ = _delivery(tmp_path, conn)
    runner, ev, state = _runner(tmp_path, conn, now, now - timedelta(minutes=1), delivery=delivery)
    for i in range(4):
        make(ev, title=f"일정{i}")
    runner.tick()
    await _drain(runner)
    assert len(rows(conn)) == 4
    usage = state.usage(date(2026, 10, 26))
    assert usage.proactive_messages == 0 and usage.brain_calls == 0


async def test_runner_judges_before_checkin_early_return(tmp_path, conn):
    now = kst(2026, 10, 26, 13, 50)
    push = FakePushSender()
    delivery, _ = _delivery(tmp_path, conn, push=push)
    runner, ev, state = _runner(tmp_path, conn, now, now - timedelta(minutes=1), checkins=False, delivery=delivery)
    make(ev)
    runner.tick()
    await _drain(runner)
    assert len(push.sent) == 1 and state.get("last_seen_at") == to_iso(now)


async def test_send_failure_marks_failed(tmp_path, conn):
    now = kst(2026, 10, 26, 13, 50)

    class Nowhere:
        async def deliver_reminder(self, title, body, url):
            return None

    runner, ev, _ = _runner(tmp_path, conn, now, now - timedelta(minutes=1), delivery=Nowhere())
    make(ev)
    runner.tick()
    assert rows(conn)[0][2] == "sent"  # 판정은 먼저 적는다
    await _drain(runner)
    assert rows(conn)[0][2] == "failed"


# --- 오늘 화면 ---


def test_today_missed_reminders_only_today_and_not_dismissed(tmp_path, conn):
    env = ToolEnv(tmp_path, conn)
    ev = env.events
    day = date(2026, 10, 26)
    ids = {}
    for name, d, at in (("놓침", day, "08:00"), ("못함", day, "09:30"), ("건너뜀", day, "10:00"), ("닫음", day, "11:00"),
                        ("보냄", day, "12:00"), ("어제", day - timedelta(days=1), "10:00"), ("새벽", day + timedelta(days=1), "01:00")):
        ids[name] = make(ev, title=name, d=d, at=at).id
    now = env.clock.now()
    for name, outcome in (("놓침", "missed"), ("못함", "failed"), ("건너뜀", "skipped"), ("닫음", "missed"),
                          ("보냄", "sent"), ("어제", "missed"), ("새벽", "failed")):
        ev.record_reminder(ids[name], ev.get(ids[name]).start_date, now, outcome, now)
    out = env.tools.dismiss_missed_reminder(env.user(), event_id=ids["닫음"], date="2026-10-26")
    assert out == {"event_id": ids["닫음"], "date": "2026-10-26", "dismissed": True}
    got = today_missed_reminders(ev, day, time(4, 0))
    # 00:00~03:59의 일정은 전날(논리적 날짜)에 든다: 10/27 01:00은 오늘(10/26)이다
    assert [(g["title"], g["outcome"]) for g in got] == [("놓침", "missed"), ("못함", "failed"), ("건너뜀", "skipped"), ("새벽", "failed")]
    assert got[0]["start"] == kst(2026, 10, 26, 8, 0) and got[0]["date"] == "2026-10-26"


# --- 푸시 모양과 문구 ---


def test_reminder_payload_has_title_and_schedule_url():
    p = reminder_payload("치과", "14:00 (10분 뒤)", "/schedule/?date=2026-10-26")
    assert p == {"type": "reminder", "checkin_id": None, "title": "치과", "body": "14:00 (10분 뒤)",
                 "url": "/schedule/?date=2026-10-26"}


def test_reminder_copy_has_no_banned_words(events):
    from my_planner.tools.ui import banned_words

    copy = []
    for remind in (0, 10, 30, 60, 1440):
        e = make(events, remind=remind)
        (o,) = [o for o in events.occurrences(MON, MON) if o.event_id == e.id]
        for late, left in ((False, 0), (True, 15), (True, 120)):
            copy.append(reminder_text(o, o.start - timedelta(minutes=left or 1), late)[1])
    for rem in (0, 1440):
        e = make(events, all_day=True, remind=rem, d=TUE)
        (o,) = [o for o in events.occurrences(TUE, TUE) if o.event_id == e.id]
        copy.append(reminder_text(o, kst(2026, 10, 27, 9, 0), False)[1])
    assert len(set(copy)) >= 8
    words = banned_words()
    assert [(c, w) for c in copy for w in words if w in c] == []

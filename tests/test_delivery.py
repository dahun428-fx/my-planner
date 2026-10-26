"""회차 전달 D1~D8 (SP3-4 스펙 7.3, 6.4.8): 주 통로, 웹 푸시, 텔레그램 대체. 구독 주소와 키는 꾸며 낸 값이다."""

import asyncio
import threading
from datetime import date, timedelta

from be_env import BeEnv
from fakes import (
    FAKE_AUTH,
    FAKE_P256DH,
    FAKE_VAPID,
    FakePushSender,
    FakeSender,
    FakeTurn,
    fake_sleep,
    make_settings,
)
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock, to_iso
from my_planner.domain import LoopKey, RunStatus
from my_planner.harness.delivery import (
    Delivery,
    effective_channel,
    notice_payload,
    push_payload,
)
from my_planner.harness.dispatcher import BILLING_NOTICE, Outbound
from my_planner.store.repos.push import PushRepo
from my_planner.store.repos.runs import RunsRepo
from my_planner.store.repos.state import NOTIFY_PRIMARY_KEY, PAUSE_UNTIL_KEY, StateRepo

SAT_1000 = kst(2026, 10, 24, 10, 0)  # 토요일 아침 브리핑(주말 10:00)
SAT_1200 = kst(2026, 10, 24, 12, 0)  # 아침 답장 창 끝
SAT = date(2026, 10, 24)
EP_A = "https://push.example.invalid/sub/aaa-fake"
EP_B = "https://push.example.invalid/sub/bbb-fake"
EP_C = "https://push.example.invalid/sub/ccc-fake"
BRIEF = "좋은 아침이에요. 오늘은 산책 하나만 해 봐요.\n첫 걸음: 신발 꺼내 두기."


def _start(at=SAT_1000):
    return at + timedelta(seconds=30)


async def tick_at(env, at):
    """그 시각의 tick. 직전 tick이 1분 전이었던 것으로 둔다(긴 공백의 복귀 인사가 끼지 않게)."""
    env.clock.set(at)
    env.parts.state.set("last_seen_at", to_iso(at - timedelta(minutes=1)))
    await env.tick()


def deliveries(env, run_id):
    """`run_deliveries` 줄(통로 순). BE를 닫은 뒤에도 읽도록 새 연결을 연다."""
    import sqlite3

    c = sqlite3.connect(env.db_path)
    try:
        rows = c.execute(
            "SELECT channel, mode, status, push_ok, push_failed FROM run_deliveries WHERE run_id = ? ORDER BY channel",
            (run_id,),
        ).fetchall()
    finally:
        c.close()
    return [tuple(r) for r in rows]


def sub_row(env, sid):
    return env.conn.execute("SELECT * FROM push_subscriptions WHERE id = ?", (sid,)).fetchone()


def morning(env):
    (run,) = [r for r in env.parts.runs.with_status(RunStatus.done) if r.loop is LoopKey.morning_brief]
    return run


# --- D1a, D2, D3 ---


async def test_default_app_without_subscription_goes_telegram(tmp_path):
    push = FakePushSender()
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        before = await (await env.get("/settings/notify")).json()
        await env.tick()
        health = await (await env.get("/health")).json()
        run = morning(env)

    assert before == {"primary": "app", "effective": "telegram", "push_subscriptions": 0}
    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert push.sent == []
    assert deliveries(env, run.id) == [("telegram", "full", "sent", 0, 0)]
    assert health["notify"] == {"primary": "app", "effective": "telegram"}
    assert health["runs_today"][0]["delivered_via"] == ["telegram"]


async def test_primary_telegram_full_telegram_no_push(tmp_path):
    push = FakePushSender()
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        await env.subscribe(EP_A)
        resp = await env.put("/settings/notify", json={"primary": "telegram"})
        await env.tick()
        run = morning(env)
        conv = env.parts.convs.get(run.conversation_id)

    assert resp.status == 200
    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert push.sent == []
    assert deliveries(env, run.id) == [("telegram", "full", "sent", 0, 0)]
    assert conv.channel == "telegram"


async def test_primary_app_push_ok_no_telegram(tmp_path):
    push = FakePushSender()
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        sid = await env.subscribe(EP_A)
        await env.tick()
        sent_at = env.clock.now()
        run = morning(env)
        health = await (await env.get("/health")).json()
        row = sub_row(env, sid)

    assert env.sender.sent == []
    (call,) = push.sent
    assert call.endpoint == EP_A
    assert call.payload == {
        "type": "checkin", "checkin_id": run.id, "title": "아침 브리핑",
        "body": "좋은 아침이에요. 오늘은 산책 하나만 해 봐요.", "url": f"/checkins/{run.id}",
    }
    assert call.ttl == int((SAT_1200 - sent_at).total_seconds()) == 7170
    assert call.topic is None  # 애플이 `run-<id>` Topic을 400으로 거절했다
    assert deliveries(env, run.id) == [("app", "full", "sent", 1, 0)]
    assert health["runs_today"][0]["delivered_via"] == ["app"]
    assert health["notify"] == {"primary": "app", "effective": "app"}
    assert health["proactive"]["sent_today"] == 1
    assert row["last_success_at"] is not None and row["failure_count"] == 0


# --- D4 ---


async def test_all_push_fail_falls_back_to_telegram(tmp_path):
    push = FakePushSender({EP_A: [500] * 3, EP_B: [ConnectionError("fake")] * 3})
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        a, b = await env.subscribe(EP_A), await env.subscribe(EP_B, label=None)
        await env.tick()
        run = morning(env)
        rows = [sub_row(env, a), sub_row(env, b)]
        conv = env.parts.convs.get(run.conversation_id)
        proactive = env.parts.state.usage(SAT).proactive_messages

    assert [c.endpoint for c in push.sent] == [EP_A] * 3 + [EP_B] * 3  # 구독마다 바로 3회
    assert [o.text for o in env.sender.sent] == [BRIEF]
    assert deliveries(env, run.id) == [("app", "full", "not_sent", 0, 2), ("telegram", "fallback", "sent", 0, 0)]
    assert [(r["failure_count"], r["disabled_at"]) for r in rows] == [(1, None), (1, None)]
    assert proactive == 1
    assert conv.channel == "telegram"  # D5: 전체 본문은 텔레그램이 받았다


async def test_404_410_disable_without_retry(tmp_path):
    push = FakePushSender({EP_A: [404], EP_B: [410]})
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        a = await env.subscribe(EP_A)
        b = await env.subscribe(EP_B)
        c = await env.subscribe(EP_C)
        await env.tick()
        run = morning(env)
        rows = {s: sub_row(env, s) for s in (a, b, c)}
        settings = await (await env.get("/settings/notify")).json()

    assert [x.endpoint for x in push.sent] == [EP_A, EP_B, EP_C]  # 404/410은 다시 보내지 않는다
    assert rows[a]["disabled_at"] is not None and rows[b]["disabled_at"] is not None
    assert rows[c]["disabled_at"] is None
    assert env.sender.sent == []
    assert deliveries(env, run.id) == [("app", "full", "sent", 1, 2)]
    assert settings["push_subscriptions"] == 1


async def test_five_consecutive_failures_disable_then_next_run_starts_telegram(tmp_path):
    push = FakePushSender()
    push.always(EP_A, 503)
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        sid = await env.subscribe(EP_A)
        delivery = env.parts.delivery
        counts = []
        for i in range(5):  # 회차 다섯 번이 끝내 안 됨(회차마다 바로 3회)
            fake = env.parts.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 19 + i, 17, 30))
            out = await delivery.deliver_run(fake, Outbound(text="꾸민 본문"), reply_until=SAT_1200)
            assert (out.channel, out.mode) == ("telegram", "fallback")
            counts.append(sub_row(env, sid)["failure_count"])
        disabled = sub_row(env, sid)["disabled_at"]
        tried = len(push.sent)
        effective = delivery.effective()
        await env.tick()  # 다음 회차는 처음부터 텔레그램(D1a)
        run = morning(env)

    assert counts == [1, 2, 3, 4, 5] and disabled is not None
    assert tried == 15 and len(push.sent) == 15  # 다음 회차는 푸시를 해 보지도 않는다
    assert effective == "telegram"
    assert deliveries(env, run.id) == [("telegram", "full", "sent", 0, 0)]


async def test_success_resets_consecutive_failures(tmp_path):
    push = FakePushSender({EP_A: [500, 500, 500, 201]})
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        sid = await env.subscribe(EP_A)
        delivery = env.parts.delivery
        r1 = env.parts.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 22, 17, 30))
        await delivery.deliver_run(r1, Outbound(text="꾸민 본문"), reply_until=SAT_1200)
        after_fail = sub_row(env, sid)["failure_count"]
        r2 = env.parts.runs.ensure(LoopKey.evening_checkin, kst(2026, 10, 23, 17, 30))
        ok = await delivery.deliver_run(r2, Outbound(text="꾸민 본문"), reply_until=SAT_1200)
        after_ok = sub_row(env, sid)["failure_count"]

    assert (after_fail, after_ok) == (1, 0)
    assert (ok.channel, ok.mode, ok.push_ok) == ("app", "full", 1)


# --- D5, D6, D7, D8, 멈춤 ---


async def test_proactive_counter_once_per_run(tmp_path):
    # 푸시가 모두 안 되고 텔레그램으로 대체돼도(D4) 회차 하나는 하나로 센다
    push = FakePushSender()
    push.always(EP_A, 500)
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        await env.subscribe(EP_A)
        await env.tick()
        health = await (await env.get("/health")).json()

    assert len(push.sent) == 3 and len(env.sender.sent) == 1
    assert health["proactive"]["sent_today"] == 1
    assert health["runs_today"][0]["delivered_via"] == ["telegram"]


async def test_resend_after_5_minutes_only_if_nothing_delivered(tmp_path):
    # 푸시도 텔레그램도 안 됨 → failed → 5분 뒤 같은 순서(D2~D4)로 한 번(이번에는 푸시가 받는다)
    push = FakePushSender({EP_A: [500, 500, 500]})
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        await env.subscribe(EP_A)
        env.sender.fail = True
        await env.tick()
        (run,) = env.parts.runs.with_status(RunStatus.failed)
        first = deliveries(env, run.id)
        for _ in range(10_000):
            await asyncio.sleep(0)
            if env.parts.runs.get(run.id).resent:
                break
        await env.drain()
        after = env.parts.runs.get(run.id)
        last = deliveries(env, run.id)
        sent_today = env.parts.state.usage(SAT).proactive_messages

    assert first == [("app", "full", "not_sent", 0, 1), ("telegram", "fallback", "not_sent", 0, 0)]
    assert len(push.sent) == 4  # 처음 3회 + 재전송 1회
    assert push.sent[-1].topic is None
    assert after.status is RunStatus.done and after.resent == 1
    assert ("app", "full", "sent", 1, 0) in last
    assert sent_today == 1
    assert len(env.brain.calls) == 1


async def test_resend_skips_delivered_run(tmp_path):
    # 이미 전달된(done) 회차는 다시 보내지 않는다(D7)
    push = FakePushSender()
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        await env.subscribe(EP_A)
        await env.tick()
        run = morning(env)
        env.parts.dispatcher.submit_resend(run)
        await env.drain()

    assert len(push.sent) == 1 and env.sender.sent == []


async def test_run_conversation_channel_follows_full_body(tmp_path):
    push = FakePushSender()
    script = [FakeTurn([], BRIEF, session_id="s-run"), FakeTurn([], "텔레그램에서 이어 가요", session_id="s-tg")]
    async with BeEnv.start(tmp_path, start=_start(), script=script, push=push) as env:
        await env.subscribe(EP_A)
        await env.tick()
        run = morning(env)
        conv = env.parts.convs.get(run.conversation_id)
        # 원문 기록: 앱 줄은 ` @app`(7.4)
        text = (env.settings.paths.data_dir / "transcripts" / "2026" / "10" / "2026-10-24.md").read_text("utf-8")
        # 텔레그램에서 그 회차에 답하면 텔레그램 쪽 회차 대화를 갈라 연다(7.2 가르기)
        env.clock.advance(minutes=10)
        await env.telegram("꾸민 텔레그램 답")
        tg = env.parts.convs.run_conversation(run.id, "telegram")

    assert (conv.kind.value, conv.channel) == ("run", "app")
    assert f"비서 [{conv.id}] (morning_brief) @app" in text
    assert tg is not None and tg.forked_from == conv.id
    second = env.brain.calls[1]
    # 앱 쪽 회차 대화에서 갈라 연 텔레그램 쪽은 앱 세션을 잇지 않고 회차 본문으로 새로 시작한다(SP8 6.7, 11장)
    assert (second["session_id"], second["fork_session"]) == (None, False)
    assert f"## 회차 메시지\n{BRIEF}" in second["prompt"]


async def test_notice_goes_to_effective_channel_and_safe_mode_telegram_only(tmp_path, monkeypatch):
    # 로그인·결제 안내(D8): 실제 통로가 app이면 notice 푸시. 아무도 못 받으면 텔레그램
    script = [FakeTurn([], "", status="auth_error", error="billing")]
    push = FakePushSender()
    async with BeEnv.start(tmp_path, start=_start(), script=script, push=push) as env:
        await env.subscribe(EP_A)
        await env.tick()
        notice = list(push.sent)
        telegram = list(env.sender.sent)

    assert telegram == []
    (call,) = notice
    assert call.payload == notice_payload(BILLING_NOTICE)
    assert call.payload["type"] == "notice" and call.payload["title"] == "알림"

    # 푸시가 안 되면 텔레그램
    push2 = FakePushSender()
    push2.always(EP_A, 500)
    async with BeEnv.start(tmp_path / "b", start=_start(), script=list(script), push=push2) as env:
        await env.subscribe(EP_A)
        await env.tick()
        fallback = [o.text for o in env.sender.sent]
    assert len(push2.sent) == 1 and fallback == [BILLING_NOTICE]

    # 안전 모드 안내는 텔레그램으로만(푸시 구독을 읽지 않는다)
    from my_planner import app

    async def no_wait():
        return None

    monkeypatch.setattr(app, "_wait_for_shutdown", no_wait)
    safe = FakeSender()
    (tmp_path / "safe").mkdir()
    await app.enter_safe_mode(tmp_path / "safe", safe)
    assert [o.text for o in safe.sent] == [app.INTEGRITY_NOTICE]


async def test_paused_runs_silent_on_both_channels(tmp_path):
    push = FakePushSender()
    async with BeEnv.start(tmp_path, start=_start(), script=[FakeTurn([], BRIEF)], push=push) as env:
        await env.subscribe(EP_A)
        env.parts.state.set(PAUSE_UNTIL_KEY, to_iso(kst(2026, 10, 25, 4, 0)))
        await env.tick()
        runs = [(r.loop, r.status, r.skip_reason) for r in env.parts.runs.with_status(RunStatus.skipped)]

    assert push.sent == [] and env.sender.sent == []
    assert [(loop, status) for loop, status, _ in runs] == [(LoopKey.morning_brief, RunStatus.skipped)]
    assert runs[0][2].value == "paused"


# --- 순수 함수와 스레드 ---


def test_effective_channel_rules():
    assert effective_channel("app", 1, True) == "app"
    assert effective_channel("app", 0, True) == "telegram"  # D1a
    assert effective_channel("app", 2, False) == "telegram"  # VAPID 없음
    assert effective_channel("telegram", 2, True) == "telegram"


def test_push_payload_titles_and_body(tmp_path, conn):
    clock = FakeClock(SAT_1000)
    runs = RunsRepo(conn, clock)
    titles = {}
    for loop, at in ((LoopKey.morning_brief, SAT_1000), (LoopKey.evening_checkin, kst(2026, 10, 24, 18, 0)),
                     (LoopKey.review, kst(2026, 10, 25, 18, 0)), (LoopKey.return_, kst(2026, 10, 24, 11, 0))):
        r = runs.ensure(loop, at)
        payload, _ = push_payload(r, "\n\n" + "가" * 200, reply_until=SAT_1200, now=SAT_1000)
        titles[loop] = payload["title"]
        assert len(payload["body"]) == 120 and payload["body"].endswith("…")
    assert titles == {LoopKey.morning_brief: "아침 브리핑", LoopKey.evening_checkin: "저녁 체크인",
                      LoopKey.review: "주간 회고", LoopKey.return_: "다시 이어서"}
    _, ttl = push_payload(runs.get(1), "x", reply_until=SAT_1000, now=SAT_1200)
    assert ttl == 0  # 창이 지났으면 0
    import pytest

    with pytest.raises(TypeError):  # `now`는 주입한 시계로만(벽시계 기본값이 없다)
        push_payload(runs.get(1), "x", reply_until=SAT_1200)


async def test_push_sent_in_worker_thread_recorded_on_loop_thread(tmp_path, conn):
    clock = FakeClock(_start())
    settings = make_settings(tmp_path, vapid=FAKE_VAPID)
    state = StateRepo(conn, clock)
    pushes = PushRepo(conn, clock)
    sid = pushes.upsert(EP_A, FAKE_P256DH, FAKE_AUTH, None)
    threads = []

    class ThreadPush(FakePushSender):
        def send(self, sub, payload, *, ttl, topic):
            threads.append(threading.get_ident())
            return super().send(sub, payload, ttl=ttl, topic=topic)

    delivery = Delivery(telegram=FakeSender(), push=ThreadPush(), pushes=pushes, state=state, clock=clock,
                        settings=settings, sleep=fake_sleep(clock))  # 기본 to_thread = asyncio.to_thread
    run = RunsRepo(conn, clock).ensure(LoopKey.morning_brief, SAT_1000)
    out = await delivery.deliver_run(run, Outbound(text=BRIEF), reply_until=SAT_1200)

    assert threads and threads[0] != threading.get_ident()
    assert out.push_ok == 1 and pushes.get(sid).last_success_at is not None


def test_no_vapid_means_push_disabled(tmp_path, conn):
    clock = FakeClock(_start())
    state = StateRepo(conn, clock)
    pushes = PushRepo(conn, clock)
    pushes.upsert(EP_A, FAKE_P256DH, FAKE_AUTH, None)
    state.set(NOTIFY_PRIMARY_KEY, "app")
    delivery = Delivery(telegram=FakeSender(), push=FakePushSender(), pushes=pushes, state=state, clock=clock,
                        settings=make_settings(tmp_path))
    assert delivery.push_enabled is False and delivery.effective() == "telegram"


def _browser_keys():
    """꾸며 낸 브라우저 구독 키(P-256 공개점, auth 16바이트). 실제 기기 값이 아니다."""
    import base64
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return b64(pub), b64(os.urandom(16))


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.reason = "fake"
        self.text = ""
        self.headers = {}


def test_web_push_sender_encrypts_signs_and_maps_status(tmp_path, monkeypatch, conn):
    import requests

    from my_planner import cli
    from my_planner.config import VapidConfig
    from my_planner.harness.delivery import WebPushSender
    from my_planner.store.repos.push import PushSubscription

    public, private = cli.gen_vapid()
    vapid = VapidConfig(public_key=public, private_key=private, subject="mailto:test@example.invalid")
    p256dh, auth = _browser_keys()
    sub = PushSubscription(id=1, endpoint=EP_A, p256dh=p256dh, auth=auth, label=None, created_at=SAT_1000,
                           last_success_at=None, failure_count=0, disabled_at=None)
    calls, statuses = [], [201, 410]

    def fake_post(url, *, timeout, data, headers):
        calls.append((url, data, headers))
        status = statuses.pop(0)
        if status == "boom":
            raise requests.ConnectionError(f"failed to reach {url}")
        return _Resp(status)

    monkeypatch.setattr(requests, "post", fake_post)
    sender = WebPushSender(vapid)
    assert sender.send(sub, {"type": "checkin", "body": "꾸민 본문"}, ttl=7170, topic="run-7") == 201
    assert sender.send(sub, {"type": "notice"}, ttl=60, topic=None) == 410  # 실패 응답은 상태 코드로
    url, data, headers = calls[0]
    assert url == EP_A
    assert headers["ttl"] == "7170" and headers["Topic"] == "run-7"
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["Authorization"].startswith("vapid t=") and public in headers["Authorization"]
    assert "꾸민".encode() not in data  # 본문은 암호화되어 간다(RFC 8291)
    assert "Topic" not in calls[1][2]
    assert "SECRET" not in repr(sub) and EP_A not in repr(sub)  # 구독 repr에 주소·키가 없다

    statuses.append("boom")
    try:
        sender.send(sub, {"type": "notice"}, ttl=60, topic=None)
    except requests.ConnectionError as e:  # 네트워크 오류는 그대로 올린다(종류만 남긴다)
        assert type(e).__name__ == "ConnectionError"
    else:
        raise AssertionError("예외가 나야 한다")


# --- SP8 계획 결정 10: 회고가 텔레그램 대체로 가도 순간의 글은 없다 ---


async def test_review_fallback_to_telegram_has_no_moment_text(tmp_path):
    """앱 통로 회고에서 푸시가 모두 실패하면 본문 전체가 텔레그램으로 간다(D4). 그래서 회고 앞머리에는 순간의 글을
    두지 않는다: 두뇌에 준 프롬프트에도, 텔레그램으로 간 본문에도, 푸시 본문에도 시험 글이 없다."""
    secret = "꾸며 낸 순간: 일요일 아침에 빵을 구웠어요"
    reply = "한 주 수고했어요. 이번 주에 이룬 순간이 이틀 있었어요."
    push = FakePushSender({EP_A: [500] * 3})
    sun_review = kst(2026, 10, 25, 18, 0)
    async with BeEnv.start(tmp_path, start=_start(sun_review), script=[FakeTurn([], reply)], push=push) as env:
        await env.subscribe(EP_A)
        now = env.clock.now()
        env.parts.moments.save_day(date(2026, 10, 24), [(secret, "quality_of_life", ["chat"])], now)
        env.parts.moments.save_day(date(2026, 10, 22), [("꾸며 낸 순간: 목요일 일", None, ["chat"])], now)
        await env.tick()
        prompt = env.brain.prompts[0]
        done = env.parts.runs.with_status(RunStatus.done)

    assert LoopKey.review in {r.loop for r in done}  # 저녁 체크인과 합친 주간 회고
    sent = [d for r in done for d in deliveries(env, r.id)]
    assert sent == [("app", "full", "not_sent", 0, 1), ("telegram", "fallback", "sent", 0, 0)]
    assert [o.text for o in env.sender.sent] == [reply]
    assert "## 이번 주 이룬 순간\n- 10/22 1개\n- 10/24 1개" in prompt
    for text in (prompt, *(o.text for o in env.sender.sent), *(str(c.payload) for c in push.sent)):
        assert "꾸며 낸" not in text


async def test_telegram_reply_to_app_review_has_no_moment_text(tmp_path):
    """SP8 6.7, 11장: 푸시로 간 회차에 앱에서 답하며 두뇌가 `get_status`로 순간의 글을 받았다. 같은 회차에 텔레그램으로
    답하면 텔레그램 쪽은 앱 세션을 갈라 잇지 않고(`fork_session` 없음), 앱 대화의 원문(가르기 대체 경로)도 붙이지 않는다."""
    secret = "꾸며 낸 순간: 금요일에 화분을 옮겼어요"
    push = FakePushSender()
    script = [
        FakeTurn([], BRIEF, session_id="s-run"),
        FakeTurn([("get_status", {})], f"어제 남긴 순간이 있어요. {secret}", session_id="s-run"),
        FakeTurn([], "텔레그램에서 이어 가요", session_id="s-tg"),
        FakeTurn([], "또 이어 가요", session_id="s-tg"),
    ]
    async with BeEnv.start(tmp_path, start=_start(), script=script, push=push) as env:
        await env.subscribe(EP_A)
        env.parts.moments.save_day(date(2026, 10, 23), [(secret, None, ["chat"])], env.clock.now())
        await env.tick()
        run = morning(env)
        env.clock.advance(minutes=5)
        resp, raw = await env.chat("어제 뭐 했지?", checkin_id=run.id)
        env.clock.advance(minutes=5)
        await env.telegram("꾸민 텔레그램 답")
        env.clock.advance(minutes=2)
        await env.telegram("꾸민 텔레그램 답 둘")
        tg = env.parts.convs.run_conversation(run.id, "telegram")
        transcript = (env.settings.paths.data_dir / "transcripts" / "2026" / "10" / "2026-10-24.md").read_text("utf-8")

    assert resp.status == 200 and secret in raw.decode("utf-8")  # 앱 통로에서는 글을 받는다
    assert secret in transcript  # 원래(앱) 대화의 비서 줄에 남았다: 대체 경로가 붙이면 텔레그램으로 샌다
    assert tg is not None and tg.forked_from == run.conversation_id
    tele = env.brain.calls[2:]
    assert [(c["session_id"], c["fork_session"]) for c in tele] == [(None, False), ("s-tg", False)]
    assert all(c["run_ctx"].channel == "telegram" for c in tele)
    assert f"## 회차 메시지\n{BRIEF}" in tele[0]["prompt"]
    for c in tele:
        assert secret not in c["prompt"] and "꾸며 낸" not in c["prompt"]
    assert all("꾸며 낸" not in o.text for o in env.sender.sent)


# --- 일정 정리 알림 (SP9b 2.1) ---


def _digest_delivery(tmp_path, conn, *, push=None, telegram=None, primary="app", subs=(EP_A,)):
    clock = FakeClock(kst(2026, 10, 26, 7, 30))
    state = StateRepo(conn, clock)
    pushes = PushRepo(conn, clock)
    for ep in subs:
        pushes.upsert(ep, FAKE_P256DH, FAKE_AUTH, None)
    state.set(NOTIFY_PRIMARY_KEY, primary)
    tg = telegram or FakeSender()

    async def inline(fn, *a, **k):
        return fn(*a, **k)

    d = Delivery(telegram=tg, push=push or FakePushSender(), pushes=pushes, state=state, clock=clock,
                 settings=make_settings(tmp_path, vapid=FAKE_VAPID), to_thread=inline, sleep=fake_sleep(clock))
    return d, tg


DIGEST_BODY = "하루 종일 휴가\n09:00 팀 회의\n14:00 치과"


def test_digest_payload_keeps_newlines_and_tag():
    from my_planner.harness.delivery import digest_payload

    p = digest_payload("morning", date(2026, 10, 27), "오늘 일정 3개", DIGEST_BODY, "/schedule/?date=2026-10-27")
    assert p == {"type": "digest", "checkin_id": None, "title": "오늘 일정 3개", "body": DIGEST_BODY,
                 "url": "/schedule/?date=2026-10-27", "tag": "digest:morning:2026-10-27"}
    long = "\n".join(["09:00 " + "가" * 20 + "…"] * 3 + ["외 9개"])
    assert digest_payload("night", date(2026, 10, 28), "내일 일정 12개", long, "/x")["body"] == long  # 자르지 않는다
    assert digest_payload("night", date(2026, 10, 28), "t", "b", "/x")["tag"] == "digest:night:2026-10-28"


async def test_deliver_digest_push_each_subscription_with_ttl(tmp_path, conn):
    push = FakePushSender()
    d, tg = _digest_delivery(tmp_path, conn, push=push, subs=(EP_A, EP_B))
    ch = await d.deliver_digest("morning", date(2026, 10, 26), "오늘 일정 3개", DIGEST_BODY,
                                "/schedule/?date=2026-10-26", ttl_s=5000)
    assert ch == "app" and tg.sent == []
    assert [(c.endpoint, c.ttl, c.topic, c.payload["type"]) for c in push.sent] == [
        (EP_A, 5000, None, "digest"), (EP_B, 5000, None, "digest"),
    ]


async def test_deliver_digest_falls_back_to_telegram_multiline(tmp_path, conn):
    push = FakePushSender()
    push.always(EP_A, 500)
    d, tg = _digest_delivery(tmp_path, conn, push=push)
    ch = await d.deliver_digest("morning", date(2026, 10, 26), "오늘 일정 3개", DIGEST_BODY, "/x", ttl_s=3600)
    assert ch == "telegram" and len(push.sent) == 1  # 구독마다 한 번
    assert [o.text for o in tg.sent] == ["오늘 일정 3개\n" + DIGEST_BODY]


async def test_deliver_digest_primary_telegram_and_nowhere(tmp_path, conn):
    push = FakePushSender()
    d, tg = _digest_delivery(tmp_path, conn, push=push, primary="telegram")
    assert await d.deliver_digest("night", date(2026, 10, 27), "내일 일정 1개", "10:00 치과", "/x", ttl_s=3600) == "telegram"
    assert push.sent == [] and [o.text for o in tg.sent] == ["내일 일정 1개\n10:00 치과"]
    d, _ = _digest_delivery(tmp_path, conn, primary="telegram", telegram=FakeSender(fail=True))
    assert await d.deliver_digest("night", date(2026, 10, 27), "내일 일정 1개", "10:00 치과", "/x", ttl_s=3600) is None


def test_push_reject_reason_keeps_only_short_alnum_reason():
    from my_planner.harness.delivery import push_reject_reason

    class R:
        def __init__(self, body):
            self.body = body

        def json(self):
            if isinstance(self.body, Exception):
                raise self.body
            return self.body

    assert push_reject_reason(R({"reason": "BadWebPushTopic"})) == "BadWebPushTopic"
    assert push_reject_reason(R({"reason": "https://web.push.apple.com/abc"})) is None  # 주소는 남기지 않는다
    assert push_reject_reason(R(ValueError("not json"))) is None
    assert push_reject_reason(R({})) is None

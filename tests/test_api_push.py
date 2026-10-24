"""웹 푸시 경로 `/push/*`(SP3-4 스펙 6.4.8)와 `/settings/notify`(6.4.9). 구독 주소와 키는 꾸며 낸 값이다."""

import json
import logging
import sqlite3
from datetime import timedelta

import jsonschema
from be_env import BeEnv
from fakes import FAKE_AUTH, FAKE_P256DH, FAKE_VAPID, FakePushSender, FakeTurn
from test_delivery import EP_A, EP_B, _start
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.logging_setup import setup_logging

SECRET_EP = "https://push.example.invalid/sub/SECRET-ENDPOINT-fake-0123"


def _point(n):
    """꾸며 낸 P-256 공개점(base64url 65바이트). `n`은 작은 비밀값."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    raw = ec.derive_private_key(n, ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64(raw):
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


SECRET_P256 = _point(777)
SECRET_AUTH = _b64(b"SECRET-AUTH-16by")
NEW_P256 = _point(4242)


def _valid(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def _sub_body(endpoint, *, p256dh=FAKE_P256DH, auth=FAKE_AUTH, label="폰"):
    return {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": p256dh, "auth": auth}, "label": label}


def _rows(env, sql, *args):
    c = sqlite3.connect(env.db_path)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


async def test_vapid_public_key(tmp_path):
    async with BeEnv.start(tmp_path, start=_start(), push=FakePushSender()) as env:
        resp = await env.get("/push/vapid-public-key")
        body = await resp.json()
        unauth = await env.get("/push/vapid-public-key", token=None)

    assert resp.status == 200 and body == {"public_key": FAKE_VAPID.public_key}
    _valid("VapidPublicKey", body)
    assert unauth.status == 401
    assert "private" not in json.dumps(body)


async def test_subscribe_same_endpoint_same_id(tmp_path):
    async with BeEnv.start(tmp_path, start=_start(), push=FakePushSender()) as env:
        first = await env.post("/push/subscriptions", json=_sub_body(EP_A))
        first_body = await first.json()
        again = await env.post("/push/subscriptions", json=_sub_body(EP_A, p256dh=NEW_P256, label="새 폰"))
        again_body = await again.json()
        other = await (await env.post("/push/subscriptions", json=_sub_body(EP_B, label=None))).json()
        bad = await env.post("/push/subscriptions", json={"endpoint": EP_A, "keys": {"p256dh": "x"}})
        bad_text = await bad.text()
        not_https = await env.post("/push/subscriptions", json=_sub_body("http://push.example.invalid/x"))
        rows = _rows(env, "SELECT id, p256dh, label FROM push_subscriptions ORDER BY id")
        kinds = [(r["kind"], r["actor"], r["channel"], r["summary"], r["undo_json"]) for r in env.activity()]

    assert first.status == 201 and again.status == 201
    _valid("PushSubscribed", first_body)
    assert again_body == first_body and other["id"] != first_body["id"]
    assert [(r["id"], r["p256dh"], r["label"]) for r in rows] == [
        (first_body["id"], NEW_P256, "새 폰"), (other["id"], FAKE_P256DH, None)]
    assert bad.status == 400 and EP_A not in bad_text
    assert not_https.status == 400
    assert kinds == [
        ("push_subscribed", "user", "app", "푸시 알림을 켰어요: 폰", None),
        ("push_subscribed", "user", "app", "푸시 알림을 켰어요: 새 폰", None),
        ("push_subscribed", "user", "app", "푸시 알림을 켰어요", None),
    ]


async def test_delete_subscription_204_then_404(tmp_path):
    async with BeEnv.start(tmp_path, start=_start(), push=FakePushSender()) as env:
        sid = await env.subscribe(EP_A)
        gone = await env.delete(f"/push/subscriptions/{sid}")
        again = await env.delete(f"/push/subscriptions/{sid}")
        junk = await env.delete("/push/subscriptions/abc")
        again_body = await again.json()
        settings = await (await env.get("/settings/notify")).json()
        last = env.activity()[-1]

    assert gone.status == 204
    assert again.status == 404 and again_body["error"]["code"] == "not_found"
    assert junk.status == 404
    assert settings["push_subscriptions"] == 0 and settings["effective"] == "telegram"
    assert (last["kind"], last["summary"], last["undo_json"]) == ("push_unsubscribed", "푸시 알림을 껐어요: 폰", None)


async def test_push_test_not_counted_in_daily_cap(tmp_path):
    push = FakePushSender({EP_B: [410]})
    async with BeEnv.start(tmp_path, start=_start(), push=push) as env:
        a = await env.subscribe(EP_A)
        b = await env.subscribe(EP_B)
        before = len(env.activity())
        resp = await env.post("/push/test")
        body = await resp.json()
        health = await (await env.get("/health")).json()
        rows = {r["id"]: r for r in _rows(env, "SELECT * FROM push_subscriptions")}
        after = len(env.activity())

    assert resp.status == 200 and body == {"ok": 1, "failed": 1}
    _valid("PushTestResult", body)
    assert [c.payload["type"] for c in push.sent] == ["notice", "notice"]
    assert {c.topic for c in push.sent} == {None}
    assert health["proactive"]["sent_today"] == 0  # 하루 3회 상한에 세지 않는다
    assert rows[a]["last_success_at"] is not None and rows[a]["disabled_at"] is None
    assert rows[b]["disabled_at"] is not None  # 410: 끈다
    assert health["push"]["subscriptions"] == 1
    assert after == before  # 시험은 활동을 남기지 않는다


async def test_settings_notify_get_put_effective(tmp_path):
    async with BeEnv.start(tmp_path, start=_start(), push=FakePushSender()) as env:
        default = await (await env.get("/settings/notify")).json()
        await env.subscribe(EP_A)
        subscribed = await (await env.get("/settings/notify")).json()
        put = await env.put("/settings/notify", json={"primary": "telegram"})
        put_body = await put.json()
        bad = await env.put("/settings/notify", json={"primary": "email"})
        health = await (await env.get("/health")).json()
        back = await (await env.put("/settings/notify", json={"primary": "app"})).json()
        rows = [(r["kind"], r["summary"], r["undo_json"]) for r in env.activity() if r["kind"] == "notify_changed"]

    assert default == {"primary": "app", "effective": "telegram", "push_subscriptions": 0}
    _valid("NotifySettings", default)
    assert subscribed == {"primary": "app", "effective": "app", "push_subscriptions": 1}
    assert put.status == 200 and put_body == {"primary": "telegram", "effective": "telegram", "push_subscriptions": 1}
    assert bad.status == 400
    assert health["notify"] == {"primary": "telegram", "effective": "telegram"}
    assert back == {"primary": "app", "effective": "app", "push_subscriptions": 1}
    assert rows == [("notify_changed", "주 통로: 텔레그램", None), ("notify_changed", "주 통로: 앱", None)]


async def test_push_routes_404_without_vapid(tmp_path):
    async with BeEnv.start(tmp_path, start=_start()) as env:  # VAPID 없음
        key = await env.get("/push/vapid-public-key")
        key_body = await key.json()
        sub = await env.post("/push/subscriptions", json=_sub_body(EP_A))
        delete = await env.delete("/push/subscriptions/1")
        test = await env.post("/push/test")
        notify = await env.put("/settings/notify", json={"primary": "app"})
        notify_body = await notify.json()
        count = _rows(env, "SELECT COUNT(*) AS n FROM push_subscriptions")[0]["n"]

    assert [r.status for r in (key, sub, delete, test)] == [404, 404, 404, 404]
    assert key_body["error"]["code"] == "not_found"
    assert count == 0
    assert notify.status == 200 and notify_body == {"primary": "app", "effective": "telegram", "push_subscriptions": 0}


async def test_push_endpoint_never_logged_or_in_activity(tmp_path):
    secrets = (SECRET_EP, SECRET_P256, SECRET_AUTH, "SECRET-ENDPOINT")
    push = FakePushSender({SECRET_EP: [500, ConnectionError(SECRET_EP), 503, 500, 500, 500, 404]})
    script = [FakeTurn([], "좋은 아침이에요")]
    async with BeEnv.start(tmp_path, start=_start(), script=script, push=push) as env:
        setup_logging(env.settings.paths.state_dir, 30)
        resp = await env.post("/push/subscriptions", json=_sub_body(SECRET_EP, p256dh=SECRET_P256, auth=SECRET_AUTH))
        sid = (await resp.json())["id"]
        await env.tick()  # 3회 모두 안 됨 → 텔레그램 대체
        test = await (await env.post("/push/test")).text()  # 500
        bad = await (await env.post("/push/subscriptions", json={"endpoint": SECRET_EP, "keys": {}})).text()
        env.clock.set(kst(2026, 10, 24, 18, 0) + timedelta(seconds=30))
        env.parts.state.set("last_seen_at", "2026-10-24T08:59:00.000000+00:00")
        env.brain.script.append(FakeTurn([], "저녁이에요"))
        await env.tick()  # 500, 500 → 404: 끈다
        reads = [await (await env.get(p)).text() for p in ("/settings/notify", "/health", "/activity?order=desc")]
        gone = await (await env.delete(f"/push/subscriptions/{sid}")).text()
        for h in logging.getLogger().handlers:
            h.flush()
        log_text = (env.settings.paths.state_dir / "logs" / "my-planner.jsonl").read_text(encoding="utf-8")
        activity = json.dumps([dict(r) for r in env.activity()], ensure_ascii=False)
        transcripts = "".join(
            p.read_text(encoding="utf-8") for p in (env.settings.paths.data_dir / "transcripts").rglob("*.md")
        )

    assert '"msg": "push_send_error"' in log_text  # 실패는 남는다(구독 id, 상태, 예외 종류만)
    assert '"msg": "push_subscription_disabled"' in log_text
    for blob in (log_text, activity, test, bad, gone, transcripts, *reads):
        for s in secrets:
            assert s not in blob


def test_settings_vapid_only_when_all_three(tmp_path, monkeypatch):
    from my_planner.config import load_settings

    for k in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT", "TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID"):
        monkeypatch.delenv(k, raising=False)
    base = "TELEGRAM_BOT_TOKEN=123:fake\nOWNER_TELEGRAM_ID=42\n"
    full = base + "VAPID_PUBLIC_KEY=BFakePub\nVAPID_PRIVATE_KEY=SECRET-PRIVATE-fake\nVAPID_SUBJECT=mailto:a@example.invalid\n"
    (tmp_path / ".env").write_text(full, encoding="utf-8")
    s = load_settings(tmp_path)
    assert s.vapid is not None and s.vapid.public_key == "BFakePub"
    assert s.vapid.private_key.get_secret_value() == "SECRET-PRIVATE-fake"
    assert "SECRET-PRIVATE-fake" not in repr(s) and "SECRET-PRIVATE-fake" not in str(s.model_dump())

    (tmp_path / ".env").write_text(base + "VAPID_PUBLIC_KEY=BFakePub\nVAPID_PRIVATE_KEY=\n", encoding="utf-8")
    assert load_settings(tmp_path).vapid is None


async def test_subscribe_rejects_malformed_keys(tmp_path):
    """`p256dh`는 비압축 P-256 점 65바이트, `auth`는 16바이트(base64url). 그 밖은 400이고 값은 답에 없다."""
    bad_keys = [
        {"p256dh": "not base64!", "auth": FAKE_AUTH},
        {"p256dh": _b64(b"\x04" + b"\x01" * 64), "auth": FAKE_AUTH},  # 65바이트지만 곡선 위의 점이 아니다
        {"p256dh": _b64(b"\x02" + b"\x01" * 32), "auth": FAKE_AUTH},  # 압축 점
        {"p256dh": FAKE_P256DH[:-4], "auth": FAKE_AUTH},  # 짧다
        {"p256dh": FAKE_P256DH, "auth": _b64(b"x" * 15)},
        {"p256dh": FAKE_P256DH, "auth": _b64(b"x" * 32)},
        {"p256dh": FAKE_P256DH, "auth": "a"},  # base64url 길이가 틀렸다
    ]
    async with BeEnv.start(tmp_path, start=_start(), push=FakePushSender()) as env:
        results = []
        for keys in bad_keys:
            resp = await env.post("/push/subscriptions", json={"endpoint": EP_A, "keys": keys})
            results.append((resp.status, await resp.json()))
        ok = await env.post("/push/subscriptions", json=_sub_body(EP_A))
        count = _rows(env, "SELECT COUNT(*) AS n FROM push_subscriptions")[0]["n"]

    for status, body in results:
        assert status == 400 and body["error"]["code"] == "invalid_request"
        assert EP_A not in json.dumps(body) and FAKE_P256DH[:20] not in json.dumps(body)
    assert ok.status == 201 and count == 1


def test_secrets_hidden_from_repr():
    from pydantic import ValidationError

    from my_planner.api.models import PushSubscribeBody
    from my_planner.tools.actions import ActionRequest

    body = PushSubscribeBody.model_validate(_sub_body(SECRET_EP, p256dh=SECRET_P256, auth=SECRET_AUTH))
    req = ActionRequest("push_subscribe", {"endpoint": SECRET_EP, "p256dh": SECRET_P256, "auth": SECRET_AUTH},
                        actor="user", channel="app", endpoint="push")
    try:
        PushSubscribeBody.model_validate({"endpoint": SECRET_EP, "keys": {"p256dh": SECRET_AUTH, "auth": SECRET_P256}})
    except ValidationError as e:
        err = str(e)
    else:
        raise AssertionError("검증이 실패해야 한다")
    for text in (repr(body), str(body), repr(body.keys), repr(req), err):
        for secret in (SECRET_EP, SECRET_P256, SECRET_AUTH):
            assert secret not in text
    assert "push_subscribe" in repr(req) and "label" in repr(body)


async def test_push_test_failures_do_not_count_but_notices_do(tmp_path):
    push = FakePushSender({EP_B: [410]})
    push.always(EP_A, 503)
    async with BeEnv.start(tmp_path, start=_start(), push=push) as env:
        a = await env.subscribe(EP_A)
        b = await env.subscribe(EP_B)
        bodies = [await (await env.post("/push/test")).json() for _ in range(6)]  # 일시 장애 중에 여러 번 눌러도
        after_tests = {r["id"]: r for r in _rows(env, "SELECT * FROM push_subscriptions")}
        tries_before_notice = len(push.sent)
        got = await env.parts.delivery.deliver_notice("꾸민 안내")  # 고정 안내: 전달 하나에 실패 하나
        after_notice = _rows(env, "SELECT failure_count, disabled_at FROM push_subscriptions WHERE id = ?", a)[0]

    assert bodies[0] == {"ok": 0, "failed": 2} and bodies[1:] == [{"ok": 0, "failed": 1}] * 5
    assert (after_tests[a]["failure_count"], after_tests[a]["disabled_at"]) == (0, None)
    assert after_tests[b]["disabled_at"] is not None  # 410은 시험이어도 끈다
    assert got == "telegram" and len(push.sent) == tries_before_notice + 1  # 재시도 없이 한 번
    assert (after_notice["failure_count"], after_notice["disabled_at"]) == (1, None)

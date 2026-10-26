"""일정 정리 알림 설정 API, 활동, 되돌리기 (SP9b 스펙 5장, 7장, 8장 API 줄). 시험 날짜 2026-10-26(월)."""

from datetime import date, time

import pytest
from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.loop.digests import DigestSetting
from my_planner.store.repos.state import DIGEST_SETTINGS_KEY

MON_0800 = kst(2026, 10, 26, 8, 0)
DEFAULTS = {"morning": {"on": True, "time": "07:30"}, "night": {"on": True, "time": "21:30"}}


@pytest.fixture(autouse=True)
def _not_windows(monkeypatch):
    # Windows CI에서도 진짜 깨우기 작업을 건드리지 않는다
    from my_planner.platform import windows

    monkeypatch.setattr(windows, "IS_WINDOWS", False)


@pytest.fixture
def wake_calls(monkeypatch):
    """`refresh_wake`가 부른 깨우기 작업 다시 등록(root)들."""
    from my_planner.platform import windows

    calls: list[object] = []

    async def fake(timeout_s=20, *, root=None):
        calls.append(root)
        return True

    monkeypatch.setattr(windows, "refresh_wake_task", fake)
    return calls


def _validate(model, body):
    import jsonschema

    from my_planner.api.models import schema_bundle

    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


async def _put(env, kind, on, t):
    resp = await env.put("/settings/digests", json={"kind": kind, "on": on, "time": t})
    return resp.status, await resp.json()


async def _undo(env, activity_id):
    resp = await env.post(f"/activity/{activity_id}/undo", json={"client_msg_id": f"u-{activity_id}"})
    assert resp.status == 200, await resp.text()
    return await resp.json()


def _digest_rows(env):
    return [r for r in env.activity() if r["kind"] == "digest_set"]


async def test_get_defaults(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        resp = await env.get("/settings/digests")
        body = await resp.json()
    assert resp.status == 200
    _validate("DigestSettings", body)
    assert body == {**DEFAULTS, "wake_updated": True}


async def test_get_broken_json_uses_config(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        env.parts.state.set(DIGEST_SETTINGS_KEY, "{not json")
        resp = await env.get("/settings/digests")
        body = await resp.json()
    assert resp.status == 200
    assert body == {**DEFAULTS, "wake_updated": True}


async def test_put_one_kind_records_activity_and_refreshes_wake(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, "night", True, "22:00")
        (row,) = _digest_rows(env)
        got = env.parts.state.get_digest_settings(env.settings.schedule.digest)
    assert status == 200, body
    _validate("DigestSettingsUpdated", body)
    assert body["morning"] == DEFAULTS["morning"] and body["night"] == {"on": True, "time": "22:00"}
    assert body["applies"] == "today" and body["wake_updated"] is True
    assert body["undo_id"] == row["id"] == body["activity_id"]
    assert (row["target"], row["risk"], row["actor"]) == ("digest:night", "low", "user")
    assert row["summary"] == "✓ 일정 정리 알림 바꿈: 밤 21:30 → 22:00"
    assert got["night"] == DigestSetting(True, time(22, 0)) and got["morning"] == DigestSetting(True, time(7, 30))
    assert wake_calls == [env.settings.paths.root]


async def test_activity_lines_off_and_on(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        await _put(env, "morning", True, "08:00")
        await _put(env, "night", False, "21:30")
        await _put(env, "night", True, "21:30")
        rows = _digest_rows(env)
    assert [r["summary"] for r in rows] == [
        "✓ 일정 정리 알림 바꿈: 아침 07:30 → 08:00",
        "✓ 일정 정리 알림 바꿈: 밤 끔",
        "✓ 일정 정리 알림 바꿈: 밤 켬 21:30",
    ]
    assert len(wake_calls) == 3


async def test_same_value_put_writes_nothing(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, "morning", True, "07:30")
        rows = _digest_rows(env)
        raw = env.parts.state.get(DIGEST_SETTINGS_KEY)
    assert status == 200, body
    _validate("DigestSettingsUpdated", body)
    assert (body["applies"], body["activity_id"], body["undo_id"]) == (None, None, None)
    assert rows == [] and raw is None and wake_calls == []


@pytest.mark.parametrize(("kind", "t"), [
    ("morning", "03:50"), ("morning", "12:00"), ("night", "17:50"), ("night", "00:00"),  # 범위 밖
    ("morning", "07:35"), ("night", "23:55"),  # 10분 단위 아님
    ("morning", "7:30"), ("night", "25:00"),  # 모양이 틀림
    ("noon", "12:00"), ("", "07:30"),  # 모르는 종류
])
async def test_put_invalid_422(tmp_path, wake_calls, kind, t):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, kind, True, t)
        rows = _digest_rows(env)
    assert status == 422
    assert body["error"] == {
        "code": "digest_time_invalid",
        "message": "일정 정리 알림 시간은 아침 04:00~11:50, 밤 18:00~23:50 사이에서 10분 단위로 정할 수 있어요.",
    }
    assert rows == [] and wake_calls == []


async def test_range_edges_accepted(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        got = [(await _put(env, k, True, t))[0] for k, t in (
            ("morning", "04:00"), ("morning", "11:50"), ("night", "18:00"), ("night", "23:50"),
        )]
    assert got == [200, 200, 200, 200]


@pytest.mark.parametrize("body", [
    {"kind": "morning", "on": True},  # time 없음
    {"kind": "morning", "on": "yes", "time": "08:00"},  # on이 bool이 아님
    {"kind": "morning", "on": True, "time": 800},
    {"kind": "morning", "on": True, "time": "08:00", "extra": 1},
    {"kind": 1, "on": True, "time": "08:00"},
])
async def test_put_bad_body_400(tmp_path, wake_calls, body):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        resp = await env.put("/settings/digests", json=body)
        got = await resp.json()
    assert resp.status == 400 and got["error"]["code"] == "invalid_request"
    assert wake_calls == []


async def test_put_reports_wake_updated_false_on_failure(tmp_path, monkeypatch):
    from my_planner.platform import windows

    async def failing(timeout_s=20, *, root=None):
        return False

    monkeypatch.setattr(windows, "refresh_wake_task", failing)
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, "night", True, "22:00")
        view = await (await env.get("/settings/digests")).json()
    assert status == 200
    assert body["wake_updated"] is False and view["wake_updated"] is False
    assert body["night"]["time"] == "22:00"  # 바꾼 시각은 그대로 적용된다


async def test_undo_restores_previous_and_refreshes_wake(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        env.parts.state.set_digest_last("night", date(2026, 10, 25))
        _, body = await _put(env, "night", False, "21:30")
        undone = await _undo(env, body["undo_id"])
        got = env.parts.state.get_digest_settings(env.settings.schedule.digest)
        last = env.parts.state.get_digest_last()
        view = await (await env.get("/settings/digests")).json()
    assert undone["confirmation"] == "↩ 되돌림: 밤 일정 정리 알림"
    assert got["night"] == DigestSetting(True, time(21, 30))
    assert view["night"] == {"on": True, "time": "21:30"}
    assert last == {"morning": None, "night": date(2026, 10, 25)}  # digest_last는 건드리지 않는다
    assert len(wake_calls) == 2  # PUT 한 번, 되돌리기 한 번


async def test_undo_keeps_other_kind(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        _, first = await _put(env, "morning", True, "08:00")
        await _put(env, "night", True, "22:00")
        undone = await _undo(env, first["undo_id"])
        got = env.parts.state.get_digest_settings(env.settings.schedule.digest)
    assert undone["confirmation"] == "↩ 되돌림: 아침 일정 정리 알림"
    assert got == {"morning": DigestSetting(True, time(7, 30)), "night": DigestSetting(True, time(22, 0))}


async def test_undo_superseded_by_later_change(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        _, first = await _put(env, "morning", True, "08:00")
        await _put(env, "morning", True, "08:30")
        resp = await env.post(f"/activity/{first['undo_id']}/undo", json={"client_msg_id": "u-x"})
        body = await resp.json()
        got = env.parts.state.get_digest_settings(env.settings.schedule.digest)
    assert resp.status == 409 and body["error"]["code"] == "superseded"
    assert got["morning"] == DigestSetting(True, time(8, 30))
    assert len(wake_calls) == 2  # 되돌리지 못했으면 다시 등록하지 않는다


# --- 적용 시점(`applies`): 논리적 오늘 슬롯이 판정 전이고 보낼 시각이 지금보다 뒤면 today ---


@pytest.mark.parametrize(("kind", "on", "t", "want"), [
    ("morning", True, "09:00", "today"),  # 07:30은 지났지만 09:00은 뒤
    ("morning", True, "07:50", "tomorrow"),  # 새 시각도 지났다
    ("night", True, "22:00", "today"),
    ("night", False, "21:30", "today"),  # 끄기는 옛 시각(21:30)으로 본다
    ("morning", False, "07:30", "tomorrow"),  # 옛 시각 07:30이 지났다
])
async def test_applies(tmp_path, wake_calls, kind, on, t, want):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, kind, on, t)
    assert status == 200, body
    assert body["applies"] == want


async def test_applies_tomorrow_when_today_slot_judged(tmp_path, wake_calls):
    # 오늘 아침 슬롯을 이미 판정했으면(07:30에 보냄) 뒤로 바꿔도 오늘 다시 보내지 않는다
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        env.parts.state.set_digest_last("morning", date(2026, 10, 26))
        _, body = await _put(env, "morning", True, "09:00")
    assert body["applies"] == "tomorrow"


async def test_applies_uses_logical_today_after_midnight(tmp_path, wake_calls):
    # 00:30은 논리적 날짜로 전날(10-26)이다. 10-26 밤 슬롯(23:50)은 이미 지났으니 내일
    async with BeEnv.start(tmp_path, start=kst(2026, 10, 27, 0, 30)) as env:
        _, body = await _put(env, "night", True, "23:50")
    assert body["applies"] == "tomorrow"


async def test_set_digest_settings_not_public(tmp_path, wake_calls):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, _ = await env.action("set_digest_settings", {"kind": "morning", "on": False, "time": "07:30"})
        rows = _digest_rows(env)
    assert status == 400 and rows == [] and wake_calls == []


def test_action_spec_is_internal_push():
    from my_planner.tools.actions import ACTIONS

    spec = ACTIONS["set_digest_settings"]
    assert (spec.tool, spec.public, spec.endpoint) == ("apply_digest_settings", False, "push")


def test_digest_settings_copy_has_no_banned_words():
    """7장 금지어 검사: 활동 한 줄, 되돌림, 오류. 이 문구들은 `copy.ts`에 없어 `lint:copy`가 보지 않는다."""
    from my_planner.tools import digest_settings as ds
    from my_planner.tools.confirmations import digest_set_line, undo_summary
    from my_planner.tools.ui import banned_words

    on_a, on_b, off = DigestSetting(True, time(7, 30)), DigestSetting(True, time(8, 0)), DigestSetting(False, time(7, 30))
    lines = [digest_set_line(k, b, a) for k in ("morning", "night") for b, a in ((on_a, on_b), (on_a, off), (off, on_a))]
    copy = [*lines, *(undo_summary(x) for x in lines), *(v for k, v in vars(ds).items() if k.startswith("MSG_"))]
    assert [undo_summary(x) for x in lines] == ["↩ 되돌림: 아침 일정 정리 알림"] * 3 + ["↩ 되돌림: 밤 일정 정리 알림"] * 3
    words = banned_words()
    assert [(c, w) for c in copy for w in words if w in c] == []

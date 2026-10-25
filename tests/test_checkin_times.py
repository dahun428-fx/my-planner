"""체크인 시간 바꾸기 (SP9 스펙 8장, 9.7, 완료 조건 13). 시험 날짜 2026-10-26(월)~11-01(일)."""

from datetime import date, time, timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn, make_settings
from test_dispatcher_messages import kst
from test_runner import Env

from my_planner.domain import Cadence, LoopKey, RunStatus
from my_planner.loop.schedule import CheckinSlot, Due, checkin_time, due_between
from my_planner.store.repos.runs import Run
from my_planner.tools.checkin_times import decide_from


@pytest.fixture
def cfg(tmp_path):
    return make_settings(tmp_path)


def _run(loop, at, status=RunStatus.done):
    return Run(id=1, loop=loop, cadence=Cadence.day, scheduled_for=at, status=status, skip_reason=None, attempt=1,
               outbound_text=None, resent=0, conversation_id=None)


MB = LoopKey.morning_brief
MON = date(2026, 10, 26)


def _from(cfg, now, new, runs=(), loop=MB, day_type="weekday", ov=None):
    return decide_from(now, loop, day_type, new, ov or {}, list(runs), settings=cfg)


def _today_time(cfg, f, loop=MB, prev=time(9, 0), new=None, d=MON):
    ov = {loop: {"weekday": CheckinSlot(new, f, prev)}}
    return checkin_time(cfg, ov, loop, d)


# --- 8장 적용 시점 표 네 줄 ---


def test_0800_0900_to_0930_today(cfg):
    f = _from(cfg, kst(2026, 10, 26, 8, 0), time(9, 30))
    assert f == MON
    assert _today_time(cfg, f, new=time(9, 30)) == time(9, 30)


def test_0800_0900_to_0700_keeps_0900_today(cfg):
    f = _from(cfg, kst(2026, 10, 26, 8, 0), time(7, 0))
    assert f == MON + timedelta(days=1)
    assert _today_time(cfg, f, new=time(7, 0)) == time(9, 0)
    assert _today_time(cfg, f, new=time(7, 0), d=MON + timedelta(days=1)) == time(7, 0)


def test_0930_after_sent_no_second_run(cfg):
    now = kst(2026, 10, 26, 9, 30)
    f = _from(cfg, now, time(10, 0), runs=[_run(MB, kst(2026, 10, 26, 9, 0))])
    assert f == MON + timedelta(days=1)
    ov = {MB: {"weekday": CheckinSlot(time(10, 0), f, time(9, 0))}}
    # 10:00이 지나도 오늘 아침 회차는 09:00 그것 하나뿐이다(이미 보냄). 두 번째 회차가 생기지 않는다
    assert due_between(kst(2026, 10, 26, 8, 0), kst(2026, 10, 26, 11, 0), cfg, cfg.timezone, {MB}, ov) == [
        Due(MB, kst(2026, 10, 26, 9, 0))
    ]


def test_0850_0900_to_0840_keeps_0900_today(cfg):
    f = _from(cfg, kst(2026, 10, 26, 8, 50), time(8, 40))
    assert f == MON + timedelta(days=1)
    assert _today_time(cfg, f, new=time(8, 40)) == time(9, 0)


def test_skipped_run_counts_as_existing(cfg):
    # 건너뛴 회차도 "있음"이다: 시각을 늦춰도 오늘 다시 생기지 않는다
    f = _from(cfg, kst(2026, 10, 26, 8, 0), time(9, 30), runs=[_run(MB, kst(2026, 10, 26, 9, 0), RunStatus.skipped)])
    assert f == MON + timedelta(days=1)


def test_change_at_0030_targets_next_logical_day(cfg):
    # 10/27(화) 00:30의 논리적 날짜는 10/26(월). 그날 저녁 회차(17:30)는 이미 있다 → from = 10/27
    now = kst(2026, 10, 27, 0, 30)
    eve = LoopKey.evening_checkin
    assert _from(cfg, now, time(18, 0), runs=[_run(eve, kst(2026, 10, 26, 17, 30))], loop=eve) == date(2026, 10, 27)
    # 회차가 없어도(노트북 꺼짐) 원래 시각이 지났으니 다음 논리적 날짜
    assert _from(cfg, now, time(23, 30), loop=eve) == date(2026, 10, 27)


def test_other_day_type_applies_from_tomorrow(cfg):
    # 토요일에 평일 아침을 바꾸면 오늘은 그 칸을 쓰지 않는다
    assert _from(cfg, kst(2026, 10, 31, 8, 0), time(9, 30)) == date(2026, 11, 1)


def test_sunday_weekend_evening_checks_review_run(cfg):
    # 일요일 저녁 칸은 주간 회고와 같은 시각이다. 회고 회차가 이미 있으면 내일부터
    sun_1700 = kst(2026, 11, 1, 17, 0)
    eve = LoopKey.evening_checkin
    review = _run(LoopKey.review, kst(2026, 11, 1, 16, 0))
    assert _from(cfg, sun_1700, time(19, 0), loop=eve, day_type="weekend") == date(2026, 11, 1)
    assert _from(cfg, sun_1700, time(19, 0), runs=[review], loop=eve, day_type="weekend") == date(2026, 11, 2)


# --- 러너가 tick마다 다시 읽는다 ---


def test_due_between_reads_override_without_restart(tmp_path, conn, state):
    start = kst(2026, 10, 26, 8, 0)
    env = Env(tmp_path, conn, state, start, installed=start - timedelta(days=1), last_seen=start - timedelta(minutes=1))
    env.runner.tick()
    state.set_schedule_override({MB: {"weekday": CheckinSlot(time(9, 30), MON, time(9, 0))}})
    for minute in range(32):  # 08:59 → 09:30, 1분 tick
        env.clock.set(kst(2026, 10, 26, 8, 59) + timedelta(minutes=minute))
        env.runner.tick()
    submitted = [r.scheduled_for for r, _ in env.dispatcher.submitted]
    assert submitted == [kst(2026, 10, 26, 9, 30)]  # 같은 Runner(재시작 없음)가 09:00이 아니라 09:30에


def test_catchup_uses_override(cfg):
    # R1(복귀 인사)이 그날 아침 브리핑을 건너뛸 때도 바꾼 시각을 본다
    from my_planner.domain import SkipReason
    from my_planner.loop.catchup import decide

    woke = kst(2026, 10, 26, 9, 10)
    ov = {MB: {"weekday": CheckinSlot(time(9, 30), MON, time(9, 0))}}
    d = decide(woke, woke - timedelta(days=2), [], cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary, overrides=ov)
    assert d.create_return
    assert (Due(MB, kst(2026, 10, 26, 9, 30)), SkipReason.merged_into_return) in d.skipped
    d0 = decide(woke, woke - timedelta(days=2), [], cfg=cfg, tz=cfg.timezone, boundary=cfg.day_boundary)
    assert not any(due.loop is MB for due, _ in d0.skipped)  # 바꾸지 않았으면 09:00은 이미 지났다


# --- API와 도구 ---

MON_0800 = kst(2026, 10, 26, 8, 0)


async def _put(env, loop, day_type, t):
    resp = await env.put("/settings/checkin-times", json={"loop": loop, "day_type": day_type, "time": t})
    return resp.status, await resp.json()


def _validate(model, body):
    import jsonschema

    from my_planner.api.models import schema_bundle

    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


async def test_get_lists_four_slots(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        resp = await env.get("/settings/checkin-times")
        body = await resp.json()
    assert resp.status == 200
    _validate("CheckinTimes", body)
    assert [(i["loop"], i["day_type"], i["time"], i["from"], i["effective_today"]) for i in body["items"]] == [
        ("morning_brief", "weekday", "09:00", None, "09:00"),
        ("evening_checkin", "weekday", "17:30", None, "17:30"),
        ("morning_brief", "weekend", "10:00", None, "10:00"),
        ("evening_checkin", "weekend", "18:00", None, "18:00"),
    ]


async def test_put_applies_today_and_records_activity(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, "morning_brief", "weekday", "09:30")
        (row,) = [r for r in env.activity() if r["kind"] == "checkin_time_set"]
        ov = env.parts.state.get_schedule_override()
    assert status == 200, body
    _validate("CheckinTimesUpdated", body)
    assert body["applies"] == "today" and body["wake_updated"] is True  # Windows가 아니면 할 일이 없다
    assert body["items"][0] == {
        "loop": "morning_brief", "day_type": "weekday", "time": "09:30", "from": "2026-10-26", "effective_today": "09:30",
    }
    assert body["undo_id"] == row["id"] == body["activity_id"]
    assert (row["target"], row["risk"], row["actor"]) == ("checkin_time:morning_brief:weekday", "low", "user")
    assert row["summary"] == "✓ 체크인 시간 바꿈: 평일 아침 09:00 → 09:30 (오늘부터)"
    assert ov == {MB: {"weekday": CheckinSlot(time(9, 30), MON, time(9, 0))}}


async def test_put_tomorrow_keeps_today(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        _, body = await _put(env, "morning_brief", "weekday", "07:00")
        # from이 미래인 칸을 다시 바꾸면 prev와 from은 그대로, time만
        _, body2 = await _put(env, "morning_brief", "weekday", "07:30")
        ov = env.parts.state.get_schedule_override()
    assert body["applies"] == "tomorrow"
    assert body["items"][0]["from"] == "2026-10-27" and body["items"][0]["effective_today"] == "09:00"
    assert body2["applies"] == "tomorrow"
    assert ov[MB]["weekday"] == CheckinSlot(time(7, 30), date(2026, 10, 27), time(9, 0))


@pytest.mark.parametrize(("loop", "t"), [
    ("morning_brief", "04:50"), ("morning_brief", "11:40"), ("morning_brief", "09:05"),
    ("evening_checkin", "14:50"), ("evening_checkin", "23:40"), ("morning_brief", "9:00"),
])
async def test_range_and_step_validation(tmp_path, loop, t):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, loop, "weekday", t)
        assert env.parts.state.get_schedule_override() == {}
    assert status == 422
    assert body["error"]["code"] == "checkin_time_invalid"


async def test_range_edges_accepted(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        got = [(await _put(env, lp, "weekend", t))[0] for lp, t in (
            ("morning_brief", "05:00"), ("morning_brief", "11:30"), ("evening_checkin", "15:00"),
            ("evening_checkin", "23:30"),
        )]
    assert got == [200, 200, 200, 200]


async def test_put_bad_body_400(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, "review", "weekday", "09:00")
    assert status == 400 and body["error"]["code"] == "invalid_request"


async def test_put_reports_wake_updated_false_on_failure(tmp_path, monkeypatch):
    from my_planner.platform import windows

    calls = []

    async def failing(timeout_s=20, *, root=None):
        calls.append(root)
        return False

    monkeypatch.setattr(windows, "refresh_wake_task", failing)
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        status, body = await _put(env, "evening_checkin", "weekday", "18:00")
    assert status == 200
    assert body["wake_updated"] is False
    assert body["items"][1]["time"] == "18:00"  # 바꾼 시각은 그대로 적용된다
    assert calls == [env.settings.paths.root]


async def test_undo_restores_previous_slot(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        await _put(env, "morning_brief", "weekday", "07:00")  # 칸 생김(from 내일)
        _, second = await _put(env, "morning_brief", "weekday", "07:30")
        resp = await env.post(f"/activity/{second['undo_id']}/undo", json={"client_msg_id": "u-1"})
        assert resp.status == 200, await resp.text()
        undone = await resp.json()
        after = env.parts.state.get_schedule_override()
    assert undone["confirmation"] == "↩ 되돌림: 평일 아침 07:00 → 07:30 (내일부터) 체크인 시간 바꿈"
    assert after == {MB: {"weekday": CheckinSlot(time(7, 0), date(2026, 10, 27), time(9, 0))}}


async def test_undo_first_change_removes_slot(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        _, body = await _put(env, "evening_checkin", "weekend", "20:00")
        resp = await env.post(f"/activity/{body['undo_id']}/undo", json={"client_msg_id": "u-1"})
        assert resp.status == 200
        after = env.parts.state.get_schedule_override()
        view = await (await env.get("/settings/checkin-times")).json()
    assert after == {}
    assert view["items"][3] == {
        "loop": "evening_checkin", "day_type": "weekend", "time": "18:00", "from": None, "effective_today": "18:00",
    }


async def test_tool_always_needs_confirm(tmp_path):
    from my_planner.domain import RunContext
    from my_planner.tools.mcp_adapter import call_tool

    async with BeEnv.start(tmp_path, start=MON_0800) as env:
        tools = env.parts.tools
        ctx = RunContext(conversation_id=None, run_id=None, actor="secretary", channel="app")
        out = call_tool(tools, ctx, "set_checkin_time", {"loop": "evening_checkin", "day_type": "weekday",
                                                          "time": "18:00"})
        assert env.parts.state.get_schedule_override() == {}  # 아무것도 바꾸지 않았다
        bad = call_tool(tools, ctx, "set_checkin_time", {"loop": "evening_checkin", "day_type": "weekday",
                                                          "time": "14:00"})
        (ev,) = [e for e in ctx.events if e.kind == "confirm_requested"]
        # 확인 카드로 적용(`/actions` + 토큰)
        status, body = await env.action("set_checkin_time", dict(ev.data["args"]), confirm_token=out["confirm_token"])
        ov = env.parts.state.get_schedule_override()
        (row,) = [r for r in env.activity() if r["kind"] == "checkin_time_set"]
    assert out["status"] == "needs_confirm"
    assert out["summary"] == "체크인 시간을 바꿔요: 평일 저녁 17:30 → 18:00 (오늘부터)"
    assert "error" in bad
    assert ev.data["card"] is True and ev.data["args"] == {"loop": "evening_checkin", "day_type": "weekday",
                                                           "time": "18:00"}
    assert status == 200 and body["status"] == "applied", body
    assert ov[LoopKey.evening_checkin]["weekday"].time == time(18, 0)
    assert row["risk"] == "low" and body["undo_id"] == row["id"]  # 확인으로 적용해도 되돌릴 수 있다(8장)


async def test_chat_tool_adds_confirm_card_to_stream(tmp_path):
    from ui_stream import parse_sse

    turn = FakeTurn(text="저녁 체크인을 18:00으로 바꿀지 확인해 주세요.", tool_calls=[
        ("set_checkin_time", {"loop": "evening_checkin", "day_type": "weekday", "time": "18:00"}),
    ])
    async with BeEnv.start(tmp_path, start=MON_0800, script=[turn]) as env:
        resp, raw = await env.chat("저녁 체크인 6시로 바꿔줘")
        assert resp.status == 200
        assert env.parts.state.get_schedule_override() == {}
    parts = parse_sse(raw)
    cards = [p for p in parts if p.get("type") == "tool-input-available" and p.get("toolName") == "ui_confirm"]
    assert len(cards) == 1
    assert cards[0]["input"]["action"] == "set_checkin_time"
    assert cards[0]["input"]["summary"] == "체크인 시간을 바꿔요: 평일 저녁 17:30 → 18:00 (오늘부터)"


# --- 깨우기 작업 시각 ---

REPO_CONFIG = __import__("pathlib").Path(__file__).resolve().parents[1] / "config.toml"


def _db_with_override(root, value):
    from my_planner.store.db import migrate, open_db
    from my_planner.store.repos.state import StateRepo

    conn = open_db(root / "state" / "planner.db")
    migrate(conn)
    StateRepo(conn).set_schedule_override(value)
    conn.close()


def test_wake_times_include_override(tmp_path):
    from my_planner.wake_times import wake_times

    from_future = date(2026, 10, 27)
    ov = {
        MB: {"weekday": CheckinSlot(time(7, 0), from_future, time(9, 0))},  # 내일부터: 오늘 09:00도 깨운다
        LoopKey.evening_checkin: {"weekend": CheckinSlot(time(20, 0), date(2026, 10, 1), time(18, 0))},
    }
    from my_planner.config import ScheduleConfig

    got = [f"{k} {t:%H:%M}" for k, t in wake_times(ScheduleConfig(), ov, MON)]
    # 주간 회고도 주말 저녁(20:00)을 따라간다
    assert got == ["weekday 06:55", "weekday 08:55", "weekday 17:25", "weekend 09:55", "weekend 19:55"]
    # 하루 지나 from이 지나면 prev는 빠진다
    got2 = [f"{k} {t:%H:%M}" for k, t in wake_times(ScheduleConfig(), ov, from_future)]
    assert got2 == ["weekday 06:55", "weekday 17:25", "weekend 09:55", "weekend 19:55"]


def test_wake_lines_read_db_readonly(tmp_path):
    import shutil

    from my_planner.wake_times import wake_lines

    shutil.copy(REPO_CONFIG, tmp_path / "config.toml")
    _db_with_override(tmp_path, {LoopKey.evening_checkin: {"weekday": CheckinSlot(time(21, 0), date(2026, 1, 1),
                                                                                    time(17, 30))}})
    assert wake_lines(tmp_path) == ["weekday 08:55", "weekday 20:55", "weekend 09:55", "weekend 17:55"]


def test_wake_times_without_db_uses_config(tmp_path):
    import shutil

    from my_planner.wake_times import wake_lines

    shutil.copy(REPO_CONFIG, tmp_path / "config.toml")
    assert wake_lines(tmp_path) == ["weekday 08:55", "weekday 17:25", "weekend 09:55", "weekend 17:55"]
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "planner.db").write_bytes(b"not a database")  # 못 읽으면 config만
    assert wake_lines(tmp_path) == ["weekday 08:55", "weekday 17:25", "weekend 09:55", "weekend 17:55"]


async def test_refresh_wake_task_true_off_windows():
    from my_planner.platform import windows

    assert windows.IS_WINDOWS is False
    assert await windows.refresh_wake_task() is True


async def test_refresh_wake_task_runs_script_one_at_a_time(tmp_path, monkeypatch):
    import asyncio
    import threading

    from my_planner.platform import windows

    active, peak, seen = [0], [0], []
    lock = threading.Lock()

    def fake(root, timeout_s):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        import time as _t

        _t.sleep(0.05)
        with lock:
            active[0] -= 1
        seen.append((root, timeout_s))
        return True

    monkeypatch.setattr(windows, "IS_WINDOWS", True)
    monkeypatch.setattr(windows, "_run_wake_script", fake)
    got = await asyncio.gather(*(windows.refresh_wake_task(root=tmp_path) for _ in range(3)))
    assert got == [True, True, True] and peak[0] == 1 and seen == [(tmp_path, 20)] * 3


async def test_refresh_wake_task_timeout_is_false(tmp_path, monkeypatch):
    from my_planner.platform import windows

    def slow(root, timeout_s):
        import time as _t

        _t.sleep(0.3)
        return True

    monkeypatch.setattr(windows, "IS_WINDOWS", True)
    monkeypatch.setattr(windows, "_run_wake_script", slow)
    monkeypatch.setattr(windows, "_WAIT_MARGIN_S", 0)
    assert await windows.refresh_wake_task(0.05, root=tmp_path) is False


def test_update_wake_task_script_reuses_register_functions():
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    update = (scripts / "update_wake_task.ps1").read_text(encoding="utf-8-sig")
    register = (scripts / "register_task.ps1").read_text(encoding="utf-8-sig")
    common = (scripts / "task_common.ps1").read_text(encoding="utf-8-sig")
    for text in (update, register):
        assert ". (Join-Path $PSScriptRoot 'task_common.ps1')" in text
    assert "function Get-WakeTimes" in common and "function Register-FromXml" in common
    assert "function Get-WakeTimes" not in register
    assert '"would set $($times.Count) triggers"' in update and "[switch]$DryRun" in update

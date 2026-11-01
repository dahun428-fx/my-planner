"""측정값 확인 카드, `save_measures`·`delete_measure`, 되돌리기, X14, 스냅숏 (SP13-05). 값은 고정 자료의 가짜 사람이다."""

from __future__ import annotations

import json
from pathlib import Path

from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.domain import RunContext
from my_planner.harness import prompts
from my_planner.harness.dispatcher import _outbound
from my_planner.harness.stream import harness_cards
from my_planner.standing.metrics import METRICS
from my_planner.tools.ui import banned_words, validate_props

FIX = Path(__file__).parent / "fixtures"
MON = kst(2026, 11, 2, 13, 0)  # 월요일 낮, 논리적 오늘 2026-11-02(2026-Q4)
NEXT_Q = kst(2027, 1, 5, 13, 0)  # 2027-Q1
FACE_NOTE = "얼굴 점수는 조명·각도·취향에 따라 ±10 흔들려요."


def _sample(on: str | None = None) -> list[dict]:
    rows = json.loads((FIX / "standing_sample.json").read_text(encoding="utf-8"))["measures"]
    return [{**m, "measured_on": on or m["measured_on"]} for m in rows]


def _rows(on: str | None = None) -> list[dict]:
    """한 번에 저장할 수 있는 30줄(프로필·몸·건강·직업, 순자산까지)."""
    return _sample(on)[:30]


def _brain() -> RunContext:
    return RunContext(conversation_id=7, run_id=None, inbound_id=1001, channel="app")


def _measures(env, *, live: bool = True) -> list:
    sql = "SELECT * FROM standing_measures" + (" WHERE deleted_at IS NULL" if live else "") + " ORDER BY id"
    return env.conn.execute(sql).fetchall()


def _x14(env) -> list:
    return env.conn.execute(
        "SELECT * FROM status_xp_ledger WHERE source_kind = 'standing' ORDER BY id"
    ).fetchall()


def _snaps(env, period: str) -> list:
    return env.conn.execute("SELECT * FROM standing_snapshots WHERE period = ?", (period,)).fetchall()


async def _save(env, rows, source_kind="manual", source_ref=None):
    return await env.action("save_measures", {"rows": rows, "source_kind": source_kind, "source_ref": source_ref})


async def _undo(env, aid):
    resp = await env.post(f"/activity/{aid}/undo", json={"client_msg_id": f"undo-{aid}"})
    return resp.status, await resp.json()


async def test_propose_measures_validates(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        tools = env.parts.tools
        bad_ctx = _brain()
        bad = tools.propose_measures(bad_ctx, rows=[
            {"metric": "body_fat_pct", "value": 17.5, "measured_on": "2026-09-11"},
            {"metric": "body_fat_pct", "value": 80, "measured_on": "2026-09-11"},
        ], source_kind="photo", source_ref="photo:3")
        ok_ctx = _brain()
        ok = tools.propose_measures(ok_ctx, rows=[
            {"metric": "body_fat_pct", "value": 17.5, "measured_on": "2026-09-11"},
            {"metric": "skeletal_muscle_kg", "value": 36.8, "measured_on": "2026-09-11"},
        ], source_kind="photo", source_ref="photo:3")
        n = len(_measures(env, live=False))

    assert bad["ok"] is False and [e["index"] for e in bad["errors"]] == [1]
    assert bad_ctx.events == []
    assert ok == {"ok": True, "card": True}
    (event,) = ok_ctx.events
    assert event.kind == "measures_proposed"
    assert event.data["source_kind"] == "photo" and event.data["source_ref"] == "photo:3"
    assert [(r["metric"], r["label"], r["unit"]) for r in event.data["rows"]] == [
        ("body_fat_pct", "체지방률", "%"), ("skeletal_muscle_kg", "골격근량", "kg"),
    ]
    assert n == 0  # 두뇌 도구는 쓰지 않는다


async def test_propose_measures_rejects_bad_source_and_future(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        tools = env.parts.tools
        row = {"metric": "weight_kg", "value": 72.0, "measured_on": "2026-11-02"}
        kind = tools.propose_measures(_brain(), rows=[row], source_kind="import")
        ref = tools.propose_measures(_brain(), rows=[row], source_kind="photo", source_ref="/tmp/a.jpg")
        future = tools.propose_measures(_brain(), rows=[{**row, "measured_on": "2026-11-03"}], source_kind="manual")
        many = tools.propose_measures(_brain(), rows=[row] * 31, source_kind="manual")

    assert "error" in kind and "error" in ref and "error" in many
    assert future["ok"] is False and future["errors"][0]["index"] == 0


async def test_outbound_measure_card(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        ctx = _brain()
        env.parts.tools.propose_measures(ctx, rows=[
            {"metric": "salary_krw", "value": 55000000, "measured_on": "2026-11-01"},
            {"metric": "education_tier", "value": "seoul_mid_low", "measured_on": "2026-11-01"},
        ], source_kind="manual")
    cards = [c for c in harness_cards(_outbound("카드에서 확인하고 저장해 주세요.", ctx)) if c[1] == "ui_measure_confirm"]
    assert len(cards) == 1
    prefix, component, props, output = cards[0]
    assert prefix == "h_measure" and output == {"ok": True}
    assert validate_props(component, props) is None
    assert props["source_kind"] == "manual" and props["source_ref"] is None
    assert [r["metric"] for r in props["rows"]] == ["salary_krw", "education_tier"]


async def test_save_measures_low_risk_undoable(tmp_path):
    """T8: 활동 `risk = low`, 되돌릴 수 있고, `summary`·`undo_json`에 값이 없다."""
    rows = [{"metric": "salary_krw", "label": "연봉(세전)", "value": 55000000, "unit": "원",
             "measured_on": "2026-11-01"},
            {"metric": "net_worth_krw", "value": 123456789, "measured_on": "2026-11-01"}]
    async with BeEnv.start(tmp_path, start=MON) as env:
        status, body = await _save(env, rows)
        saved = _measures(env)
        (act,) = [a for a in env.activity() if a["kind"] == "measures_saved"]
        targets = [r[0] for r in env.conn.execute(
            "SELECT target FROM activity_targets WHERE activity_id = ? ORDER BY target", (act["id"],))]
        ledger = _x14(env)
        env.clock.advance(minutes=5)
        ustatus, ubody = await _undo(env, body["undo_id"])
        after = _measures(env)
        ledger_after = _x14(env)

    assert status == 200 and body["status"] == "applied", body
    assert len(saved) == 2 and {r["source_kind"] for r in saved} == {"manual"}
    assert act["risk"] == "low" and act["target"] is None
    assert targets == sorted(f"measure:{r['id']}" for r in saved)
    assert act["summary"] == "측정값 2개 저장"
    assert body["undo_id"] == act["id"]
    for text in (act["summary"], act["undo_json"], body["confirmation"]):
        assert "55000000" not in text and "123456789" not in text
    assert json.loads(act["undo_json"])["measure_ids"] == [r["id"] for r in saved]
    assert body["confirmation"].startswith("✓ 측정값 2개 저장")
    assert ustatus == 200 and ubody["status"] == "undone"
    assert after == []
    assert len(ledger) == 1 and [tuple(r) for r in ledger_after] == [tuple(r) for r in ledger]  # U6


async def test_save_measures_rejects_bad_row(tmp_path):
    rows = [{"metric": "weight_kg", "value": 72.0, "measured_on": "2026-11-01"},
            {"metric": "body_fat_pct", "value": 80, "measured_on": "2026-11-01"}]
    async with BeEnv.start(tmp_path, start=MON) as env:
        status, body = await _save(env, rows)
        n = len(_measures(env, live=False))
        acts = [a for a in env.activity() if a["kind"] == "measures_saved"]
        ledger = _x14(env)

    assert status == 422 and body["error"]["code"] == "rejected"
    assert "80" not in body["error"]["message"]
    assert n == 0 and acts == [] and ledger == []


async def test_x14_once_per_quarter(tmp_path):
    """T10: 분기마다 한 번, 지워도 남는다."""
    async with BeEnv.start(tmp_path, start=MON) as env:
        s1, b1 = await _save(env, [{"metric": "weight_kg", "value": 72.0, "measured_on": "2026-11-01"}])
        s2, b2 = await _save(env, [{"metric": "weight_kg", "value": 71.0, "measured_on": "2026-11-02"}])
        one = _x14(env)
        env.clock.set(NEXT_Q)
        s3, b3 = await _save(env, [{"metric": "weight_kg", "value": 70.0, "measured_on": "2027-01-05"}])
        two = _x14(env)
        for m in _measures(env):
            st, _ = await env.action("delete_measure", {"id": m["id"]})
            assert st == 200
        kept = _x14(env)

    assert (s1, s2, s3) == (200, 200, 200) and b3["xp"]["gained"] == 20
    assert b1["xp"]["gained"] == 20 and b2["xp"]["gained"] == 0
    assert [(r["source_ref"], r["amount"], r["label"]) for r in one] == [("standing:2026-Q4", 20, "측정값 기록")]
    assert [r["source_ref"] for r in two] == ["standing:2026-Q4", "standing:2027-Q1"]
    assert [tuple(r) for r in kept] == [tuple(r) for r in two]


async def test_first_save_writes_baseline_snapshot(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        status, body = await _save(env, _rows())
        snaps = _snaps(env, "2026-Q4")
        (act,) = [a for a in env.activity() if a["kind"] == "measures_saved"]

    assert status == 200, body
    assert len(snaps) > 0
    assert json.loads(act["undo_json"])["baseline_period"] == "2026-Q4"
    assert body["confirmation"] == "✓ 측정값 30개 저장"  # 이전 위치가 없다


async def test_save_confirmation_names_most_changed_area(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        await _save(env, _rows())
        status, body = await _save(env, [{"metric": "salary_krw", "value": 150000000, "measured_on": "2026-11-02"}])
        (_, second) = [a for a in env.activity() if a["kind"] == "measures_saved"]

    assert status == 200, body
    assert body["confirmation"].startswith("✓ 측정값 1개 저장 · 커리어 위치 ")
    before, after = body["confirmation"].rsplit(" ", 1)[1].split("→")
    assert int(after) > int(before)
    assert "baseline_period" not in json.loads(second["undo_json"])  # 이미 스냅숏이 있었다
    assert "150000000" not in second["undo_json"] + second["summary"]


async def test_undo_first_save_removes_baseline(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        _, body = await _save(env, _rows())
        assert _snaps(env, "2026-Q4")
        env.clock.advance(minutes=5)
        status, _ = await _undo(env, body["undo_id"])
        snaps = _snaps(env, "2026-Q4")
        await _save(env, _rows())
        snaps_again = _snaps(env, "2026-Q4")
        (_, second) = [a for a in env.activity() if a["kind"] == "measures_saved"]

    assert status == 200 and snaps == []
    assert snaps_again and json.loads(second["undo_json"])["baseline_period"] == "2026-Q4"


async def test_delete_measure_and_undo(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        await _save(env, [{"metric": "weight_kg", "value": 72.0, "measured_on": "2026-11-01"}])
        (m,) = _measures(env)
        status, body = await env.action("delete_measure", {"id": m["id"]})
        gone = _measures(env)
        (act,) = [a for a in env.activity() if a["kind"] == "measure_deleted"]
        missing, _ = await env.action("delete_measure", {"id": 999})
        env.clock.advance(minutes=5)
        ustatus, _ = await _undo(env, body["undo_id"])
        back = _measures(env)

    assert status == 200 and body["confirmation"] == "측정값 지움"
    assert gone == []
    assert (act["risk"], act["target"], act["summary"]) == ("low", f"measure:{m['id']}", "측정값 지움")
    assert json.loads(act["undo_json"]) == {"measure_id": m["id"]}
    assert missing == 422
    assert ustatus == 200 and [r["id"] for r in back] == [m["id"]]


async def test_face_rating_saved_low(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        await _save(env, [{"metric": "face_rating", "value": 55, "measured_on": "2026-11-01"},
                          {"metric": "grooming_rating", "value": 70, "measured_on": "2026-11-01"}], "photo", "photo:4")
        rows = {r["metric"]: (r["reliability"], r["source_kind"], r["source_ref"]) for r in _measures(env)}

    assert rows == {"face_rating": ("low", "photo", "photo:4"), "grooming_rating": ("mid", "photo", "photo:4")}


def test_banned_words_include_standing():
    """T11: 금지어 정본에 넷, 지시문·카드 라벨·확인 문구에 금지어가 없다."""
    from my_planner.tools.standing import measures_saved_line

    words = banned_words()
    assert {"등수", "패배", "뒤처짐", "실패"} <= set(words)
    texts = [
        prompts.load("channel_app.md"), FACE_NOTE,
        *(d.label for d in METRICS.values()),
        measures_saved_line(3, None), measures_saved_line(3, ("건강", 52, 58)), "측정값 지움",
    ]
    for text in texts:
        assert not [w for w in words if w in text], text
    assert FACE_NOTE in prompts.load("channel_app.md")


async def test_record_area_scores_quarter_writes_snapshot(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        await _save(env, _rows())
        (first,) = {r["taken_at"] for r in _snaps(env, "2026-Q4")}
        env.clock.advance(hours=2)
        status, _ = await env.action("record_area_scores", {"scores": {"health": 7}})
        snaps = _snaps(env, "2026-Q4")

    assert status == 200
    assert snaps and {r["taken_at"] for r in snaps} != {first}
    assert {json.loads(r["inputs_json"])["source"] for r in snaps} == {"review"}


async def test_record_area_scores_without_measures_writes_nothing(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        status, _ = await env.action("record_area_scores", {"scores": {"health": 7}})
        n = env.conn.execute("SELECT COUNT(*) FROM standing_snapshots").fetchone()[0]
    assert status == 200 and n == 0


async def test_record_past_quarter_scores_snapshot_as_of_end(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        await _save(env, _rows("2026-09-15"))
        status, body = await env.action("record_area_scores", {"period": "2026-Q3", "scores": {"health": 6}})
        snaps = _snaps(env, "2026-Q3")

    assert status == 200, body
    assert snaps
    assert {r["taken_at"][:16] for r in snaps} == {"2026-09-30T14:59"}  # 그 분기 끝 23:59 KST
    assert {json.loads(r["inputs_json"])["source"] for r in snaps} == {"review"}


async def test_standing_daily_catches_up(tmp_path):
    async with BeEnv.start(tmp_path, start=MON) as env:
        await _save(env, _rows())
        env.clock.set(NEXT_Q)
        jobs = {getattr(j, "__name__", ""): j for j in env.parts.runner._daily}
        assert "standing_daily" in jobs
        jobs["standing_daily"](env.parts.tools.today())
        snaps = _snaps(env, "2026-Q4")

    assert snaps and {json.loads(r["inputs_json"])["source"] for r in snaps} == {"catch_up"}


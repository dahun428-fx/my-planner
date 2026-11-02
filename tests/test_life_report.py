"""SP15-13: 인생 리포트 저장(`save_life_report`)과 API, 분기 회고 뒤 "전체 진단 해 볼까요?" 칩(T11, 스펙 10장, D3).

글·측정값은 모두 꾸며 낸 것이다(측정값은 SP13 시험의 가짜 사람 `standing_sample.json`).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import jsonschema
from be_env import BeEnv
from fakes import FakeTurn
from test_api_devices import _device
from test_api_read import get_json
from test_api_standing import put, seed_sample
from test_dispatcher_messages import kst
from ui_stream import parse_sse

from my_planner.api.models import schema_bundle
from my_planner.domain import RunContext
from my_planner.panel.report import (
    FULL_CHIP_KEY,
    FULL_DAYS_KEY,
    PSYCH_CLOSING,
    build_report,
    full_diagnosis_block,
    report_scores,
)
from my_planner.store.db import transaction

WED = kst(2026, 11, 4, 12, 0)  # 수요일 낮, 논리적 오늘 2026-11-04, 2026-W45, 2026-Q4
TODAY = date(2026, 11, 4)
EXPERT_KEYS = ("career", "finance", "health", "image", "relationship", "psych")
EV = [{"type": "record", "ref": "task:1", "note": "가짜 근거"}]
SCORES = {"career": 6, "finance": 5, "health": 7, "relationships": 6, "learning": 5, "quality_of_life": 6}


def _suggest(env, *, week: str = "2026-W45") -> int:
    with transaction(env.conn):
        return env.parts.panel.add_suggestion(
            conversation_id=None, kind="task", title="가짜 제안", area="career", size_min=30, per_week=None,
            due_hint=None, experts=["career"], evidence=EV, week=week, now=env.clock.now(),
        )


def _report(this_week: list[int] | None = None) -> dict[str, Any]:
    return {
        "summary": {"line": "가짜 한 줄 진단이에요.", "paths": ["가짜 통로 하나", "가짜 통로 둘", "가짜 통로 셋"]},
        "levers": [
            {"action": "가짜 행동 하나", "axis": "career", "strength": "strong"},
            {"action": "가짜 행동 둘", "axis": "health", "strength": "weak"},
        ],
        "experts": [
            {"expert": k, "line": f"가짜 {k} 소견", "prescriptions": ["가짜 처방 1", "가짜 처방 2", "가짜 처방 3"],
             "avoid": ["가짜 하지 말 것"]}
            for k in EXPERT_KEYS
        ],
        "scenario": {"do": "가짜로 하면 이렇게 돼요.", "dont": "가짜로 안 하면 이렇게 돼요."},
        "roadmap": [{"track": "가짜 트랙", "kpi": "가짜 지표", "start": "2026-11-09", "end": "2027-02-07"}],
        "this_week": this_week or [],
        "questions": ["가짜 질문이에요?"],
    }


def _manager_ctx(env, *, full: bool = True) -> RunContext:
    with transaction(env.conn):
        cid = int(env.conn.execute(
            "INSERT INTO conversations (kind, channel, logical_date, opened_at, last_message_at, agent) "
            "VALUES ('chat', 'app', '2026-11-04', 'a', 'a', 'manager')",
        ).lastrowid)
    return RunContext(cid, None, channel="app", agent="manager", in_brain=True, full_diagnosis=full)


def _count(env) -> int:
    return env.conn.execute("SELECT COUNT(*) FROM life_reports").fetchone()[0]


# --- 검사 ---


async def test_report_sections_validated(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        seed_sample(env)
        sid = _suggest(env)
        old = _suggest(env, week="2026-W44")
        ok = build_report(env.conn, env.clock, TODAY, _report([sid]))
        expected_scores = report_scores(env.conn, env.clock, TODAY)
        bads = {}
        r = _report()
        r["experts"] = r["experts"][:5]
        bads["experts5"] = r
        r = _report()
        r["experts"] = [*r["experts"][:5], {**r["experts"][0]}]  # 6개지만 career가 둘
        bads["experts_dup"] = r
        r = _report()
        r["summary"]["paths"] = r["summary"]["paths"][:2]
        bads["paths2"] = r
        r = _report()
        r["roadmap"][0]["end"] = "2027-02-08"  # 91일
        bads["roadmap91"] = r
        bads["last_week"] = _report([old])
        r = _report()
        r["experts"][2]["prescriptions"] = ["가짜"] * 5
        bads["prescriptions5"] = r
        r = _report()
        r["summary"]["line"] = "가짜 연속 진단"
        bads["banned"] = r
        r = _report()
        r["levers"][0]["axis"] = "height"
        bads["innate_axis"] = r
        r = _report()
        r["scores"] = {}
        bads["server_field"] = r
        errs = {k: build_report(env.conn, env.clock, TODAY, v) for k, v in bads.items()}
        rows = _count(env)
    assert isinstance(ok, dict), ok
    assert ok["scores"] == expected_scores
    assert any(v["national"] is not None for v in ok["scores"].values())
    assert set(ok["scores"]["career"]) == {"national", "peer", "reliability", "estimate"}
    assert ok["closing"] == PSYCH_CLOSING == "이 숫자는 이번 분기 조건의 측정값이지 나 자신이 아니다."
    assert ok["scenario"]["estimate"] is True and ok["version"] == 1
    assert ok["this_week"] == [sid] and ok["roadmap"][0]["start"] == "2026-11-09"
    for k, e in errs.items():
        assert isinstance(e, str) and e and "\n" not in e, (k, e)
    assert errs["banned"] == "리포트에 쓰지 않는 말이 있어요: 연속"
    assert errs["last_week"] == "this_week에는 이번 주에 낸 패널 제안 id만 넣어요."
    assert errs["roadmap91"].startswith("리포트 roadmap.0 칸이 맞지 않아요.")
    assert errs["experts_dup"].startswith("리포트 experts 칸이 맞지 않아요.")
    assert rows == 0


# --- 저장 도구 ---


async def test_save_only_in_full_diagnosis(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        tools = env.parts.tools
        plain = tools.save_life_report(_manager_ctx(env, full=False), report=_report())
        secretary = tools.save_life_report(
            RunContext(None, None, channel="app", full_diagnosis=True), report=_report()
        )
        ctx = _manager_ctx(env)
        first = tools.save_life_report(ctx, report=_report())
        second = tools.save_life_report(ctx, report=_report())
        rows = _count(env)
    assert plain == {"error": "전체 진단에서만 저장해요."} == secretary
    assert first["ok"] is True and isinstance(first["id"], int)
    assert "error" in second
    assert rows == 1


async def test_save_bad_report_no_row(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        ctx = _manager_ctx(env)
        r = _report()
        r["summary"]["line"] = "가짜 달성률"
        out = env.parts.tools.save_life_report(ctx, report=r)
        again = env.parts.tools.save_life_report(ctx, report=_report())  # 실패한 호출은 한 번으로 세지 않는다
        rows = _count(env)
        days = env.parts.state.get(FULL_DAYS_KEY)
    assert out == {"error": "리포트에 쓰지 않는 말이 있어요: 달성률"}
    assert again["ok"] is True and rows == 1
    assert json.loads(days or "[]") == [TODAY.isoformat()]


async def test_save_marks_full_day(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        before = await get_json(env, "/panel/budget")
        env.parts.tools.save_life_report(_manager_ctx(env), report=_report())
        block = full_diagnosis_block(env.parts.state, TODAY, 10)
        after = await get_json(env, "/panel/budget")
    assert before["full_diagnosis_ok"] is True
    assert block == "day"
    assert after["full_diagnosis_ok"] is False


async def test_save_emits_tool_event(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        ctx = _manager_ctx(env)
        out = env.parts.tools.save_life_report(ctx, report=_report())
    assert [(e.kind, e.data) for e in ctx.events] == [("life_report_saved", {"id": out["id"]})]
    script = [FakeTurn([("save_life_report", {"report": _report()})], "", status="error", error="cli")]
    async with BeEnv.start(tmp_path / "be", start=WED, script=script) as env:
        await env.chat("전체 진단", agent="manager", chip="manager_full")
        calls = len(env.brain.calls)
        rows = _count(env)
    assert calls == 1 and rows == 1


async def test_resume_fallback_can_save(tmp_path):
    script = [
        FakeTurn([], "안녕하세요", session_id="s-man"),
        FakeTurn([], "", resume_failed=True, session_id=None),
        FakeTurn([("save_life_report", {"report": _report()})], "진단을 정리했어요.", session_id="s-new"),
    ]
    async with BeEnv.start(tmp_path, start=WED, script=script) as env:
        await env.chat("안녕", agent="manager")
        env.clock.advance(timedelta(minutes=5))
        _, raw = await env.chat("전체 진단", agent="manager", chip="manager_full")
        rows = _count(env)
    outs = [c for c in parse_sse(raw) if c["type"] == "tool-output-available"]
    assert any(c["output"].get("ok") is True for c in outs), outs
    assert rows == 1


# --- API ---


async def test_life_report_routes(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        tools = env.parts.tools
        first = tools.save_life_report(_manager_ctx(env), report=_report())["id"]
        env.clock.advance(timedelta(days=1))
        second = tools.save_life_report(_manager_ctx(env), report=_report())["id"]
        listing = await get_json(env, "/life-reports")
        body = await get_json(env, f"/life-reports/{first}")
        missing = await env.get("/life-reports/9999")
        missing_body = await missing.json()
        dash, _ = await _device(env, client="dashboard", label="Windows · 대시보드")
        app, _ = await _device(env, client="app", label="iPhone · 앱")
        out = []
        for path in ("/life-reports", f"/life-reports/{first}"):
            d = await env.get(path, token=dash)
            a = await env.get(path, token=app)
            out.append((d.status, (await d.json())["error"]["code"], a.status))
    assert [i["id"] for i in listing["items"]] == [second, first]
    models = schema_bundle()["models"]
    jsonschema.Draft202012Validator(models["LifeReports"]).validate(listing)
    jsonschema.Draft202012Validator(models["LifeReportOut"]).validate(body)
    assert all(i["created_at"].endswith("Z") for i in listing["items"])
    assert body["id"] == first and body["created_at"] == listing["items"][1]["created_at"]
    rep = body["report"]
    assert rep["closing"] == PSYCH_CLOSING and rep["version"] == 1 and rep["scenario"]["estimate"] is True
    assert [e["expert"] for e in rep["experts"]] == list(EXPERT_KEYS)
    assert missing.status == 404 and missing_body == {"error": {"code": "not_found", "message": "없는 리포트예요."}}
    assert out == [(403, "forbidden", 200)] * 2


async def test_report_scores_are_snapshot(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        seed_sample(env)
        rid = env.parts.tools.save_life_report(_manager_ctx(env), report=_report())["id"]
        saved = (await get_json(env, f"/life-reports/{rid}"))["report"]["scores"]
        put(env, [{"metric": "salary_krw", "value": 123400000, "measured_on": "2026-11-03"}])
        now = report_scores(env.conn, env.clock, TODAY)
        later = (await get_json(env, f"/life-reports/{rid}"))["report"]["scores"]
    assert now != saved  # 측정값이 바뀌어 지금 점수는 다르다
    assert later == saved


async def test_report_keeps_this_week_titles(tmp_path):
    """"이번 주" 제안 제목은 저장할 때 리포트에 복사한다(28일 창이 지나도 남는다, 최종 리뷰 2)."""
    async with BeEnv.start(tmp_path, start=WED) as env:
        a = _suggest(env)
        b = _suggest(env)
        env.conn.execute("UPDATE panel_suggestions SET title = '가짜 둘째 제안' WHERE id = ?", (b,))
        env.conn.commit()
        rid = env.parts.tools.save_life_report(_manager_ctx(env), report=_report([b, a]))["id"]
        env.conn.execute("UPDATE panel_suggestions SET title = '가짜 바뀐 제목'")
        env.conn.commit()
        body = await get_json(env, f"/life-reports/{rid}")
    rep = body["report"]
    assert rep["this_week"] == [b, a]
    assert rep["this_week_items"] == [{"id": b, "title": "가짜 둘째 제안"}, {"id": a, "title": "가짜 제안"}]
    jsonschema.Draft202012Validator(schema_bundle()["models"]["LifeReportOut"]).validate(body)


async def test_old_report_without_titles_still_reads(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        rid = env.parts.tools.save_life_report(_manager_ctx(env), report=_report())["id"]
        (text,) = env.conn.execute("SELECT json FROM life_reports WHERE id = ?", (rid,)).fetchone()
        old = json.loads(text)
        old.pop("this_week_items")
        env.conn.execute("UPDATE life_reports SET json = ? WHERE id = ?", (json.dumps(old), rid))
        env.conn.commit()
        body = await get_json(env, f"/life-reports/{rid}")
    assert "this_week_items" not in body["report"]
    jsonschema.Draft202012Validator(schema_bundle()["models"]["LifeReportOut"]).validate(body)


# --- 분기 회고 뒤 칩 ---


def _chips(raw: bytes) -> list[dict]:
    return [
        c for c in parse_sse(raw)
        if c["type"] == "tool-input-available" and c["toolName"] == "ui_full_diagnosis_chip"
    ]


async def test_full_chip_after_quarter_review(tmp_path):
    record = ("record_area_scores", {"period": "2026-Q4", "scores": SCORES})
    script = [FakeTurn([record], "분기 회고를 마쳤어요."), FakeTurn([], "네"), FakeTurn([], "안녕하세요"),
              FakeTurn([], "좋아요"), FakeTurn([], "네")]
    async with BeEnv.start(tmp_path, start=WED, script=script) as env:
        _, first = await env.chat("영역 점수 적어 줘")
        _, again = await env.chat("고마워")
        key = env.parts.state.get(FULL_CHIP_KEY.format(period="2026-Q4"))
        await env.post("/conversations/new", json={})
        _, fresh = await env.chat("새 대화")
        status, body = await env.action("record_area_scores", {"period": "2026-Q3", "scores": SCORES})
        _, after_card = await env.chat("카드로 적었어")
        _, once_more = await env.chat("또")
        agents = [c["agents"] for c in env.brain.calls]
    chips = _chips(first)
    assert len(chips) == 1 and chips[0]["toolCallId"].startswith("h_fullchip")
    assert chips[0]["input"] == {"period": "2026-Q4"}
    out = next(c for c in parse_sse(first) if c.get("toolCallId") == chips[0]["toolCallId"]
               and c["type"] == "tool-output-available")
    assert out["output"] == {"ok": True, "data": {}}
    assert all(a is None for a in agents)  # 라이프 매니저 두뇌는 부르지 않는다
    assert key is not None
    assert _chips(again) == [] and _chips(fresh) == []
    assert status == 200, body
    later = _chips(after_card)
    assert len(later) == 1 and later[0]["input"] == {"period": "2026-Q3"}
    assert _chips(once_more) == []


async def test_full_chip_not_for_manager_mate_telegram(tmp_path):
    record = ("record_area_scores", {"period": "2026-Q4", "scores": SCORES})
    async with BeEnv.start(tmp_path, start=WED, script=[FakeTurn([], "네"), FakeTurn([], "네")]) as env:
        status, _ = await env.action("record_area_scores", {"period": "2026-Q4", "scores": SCORES})
        _, manager = await env.chat("안녕", agent="manager")
        _, mate = await env.chat("안녕", agent="mate")
        key = env.parts.state.get(FULL_CHIP_KEY.format(period="2026-Q4"))
    assert status == 200
    assert _chips(manager) == [] and _chips(mate) == [] and key is None
    async with BeEnv.start(tmp_path / "tg", start=WED, script=[FakeTurn([record], "네")]) as env:
        await env.telegram("영역 점수 적어 줘")
        recorded = env.conn.execute("SELECT COUNT(*) FROM activity WHERE kind = 'area_scores_recorded'").fetchone()[0]
        key = env.parts.state.get(FULL_CHIP_KEY.format(period="2026-Q4"))
    assert recorded == 1 and key is None


def test_report_copy_has_no_banned_words():
    from my_planner.panel import report
    from my_planner.tools.panel import PANEL_EXTRA_BANNED
    from my_planner.tools.ui import banned_words

    texts = [v for k, v in vars(report).items() if k.startswith("MSG_REPORT") or k == "PSYCH_CLOSING"]
    texts += list(report._HINTS.values())
    for t in texts:
        for w in (*banned_words(), *PANEL_EXTRA_BANNED):
            assert w not in t, (t, w)


def test_save_life_report_spec():
    from my_planner.tools.mcp_adapter import _SPECS
    from my_planner.tools.panel import PANEL_EXTRA_BANNED
    from my_planner.tools.ui import banned_words

    desc, schema = _SPECS["save_life_report"]
    assert schema["required"] == ["report"] and "준비 중" not in desc
    for w in (*banned_words(), *PANEL_EXTRA_BANNED):
        assert w not in desc, w
    jsonschema.Draft202012Validator(schema).validate({"report": _report([3])})
    bad = _report()
    bad["scores"] = {}
    assert not jsonschema.Draft202012Validator(schema).is_valid({"report": bad})

"""SP15-08: 패널 제안·내가 한 말·예측 도구와 제안 카드(T3, T5, T7, T12, 스펙 5.4, 7장, 9장).

도구를 직접 부르거나 가짜 두뇌(`FakeTurn`)가 부른다. 글과 값은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

import base64
import logging
from datetime import timedelta
from typing import Any

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst
from test_photos_api import upload
from test_photos_store import jpeg
from ui_stream import parse_sse

from my_planner.clock import to_iso
from my_planner.domain import RunContext
from my_planner.panel.budget import BUDGET_KEY
from my_planner.store.db import transaction
from my_planner.tools.mcp_adapter import _SPECS, EXPERT_TOOLS
from my_planner.tools.panel import (
    EXPERT_KEYS,
    MSG_NOT_HERE,
    PANEL_EXTRA_BANNED,
    normalize_title,
    suggestion_view,
)
from my_planner.tools.ui import banned_words

WED = kst(2026, 11, 4, 12, 0)  # 수요일 낮, 논리적 오늘 2026-11-04, 2026-W45

EV_TASK = {"type": "record", "ref": "task:1", "note": "가짜 근거"}
EV_BENCH = {"type": "external", "ref": "bench:income", "note": "가짜 기준"}


def _manager(conversation_id: int) -> RunContext:
    return RunContext(conversation_id, None, channel="app", agent="manager", in_brain=True)


def _conv(env, agent: str = "manager") -> int:
    with transaction(env.conn):
        return int(env.conn.execute(
            "INSERT INTO conversations (kind, channel, logical_date, opened_at, last_message_at, agent) "
            "VALUES ('chat', 'app', '2026-11-04', 'a', 'a', ?)", (agent,),
        ).lastrowid)


def _task(env, area: str = "career") -> int:
    out = env.parts.tools.add_task(
        RunContext(None, None, actor="user", channel="app"), title="가짜 할 일", areas=[area], planned_for="2026-11-04",
    )
    assert "error" not in out, out
    return out["id"]


def _args(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "task", "title": "가짜 제안", "area": "career", "size_min": 30, "experts": ["career"],
        "evidence": [EV_TASK, EV_BENCH],
    }
    return {**base, **kw}


def _rows(env) -> list[Any]:
    return env.conn.execute("SELECT * FROM panel_suggestions ORDER BY id").fetchall()


def _set_budget(env, n: int, week: str = "2026-W45") -> None:
    with transaction(env.conn):
        env.parts.tools.state.set(BUDGET_KEY.format(week=week), str(n))


def _dismissed(env, *, area: str, title: str, experts: list[str], reason: str, days_ago: int, size_min: int = 30,
               week: str = "2026-W40") -> int:
    panel = env.parts.panel
    now = env.clock.now()
    with transaction(env.conn):
        sid = panel.add_suggestion(
            conversation_id=None, kind="task", title=title, area=area, size_min=size_min, per_week=None, due_hint=None,
            experts=experts, evidence=[EV_TASK], week=week, now=now - timedelta(days=days_ago + 1),
        )
        panel.set_state(sid, "dismissed", now=now - timedelta(days=days_ago), dismiss_reason=reason)
    return sid


# --- 제안 (7장) ---


async def test_propose_creates_card_data(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="my_planner.tools.panel")
    async with BeEnv.start(tmp_path, start=WED) as env:
        assert _task(env) == 1
        ctx = _manager(_conv(env))
        out = env.parts.tools.propose_suggestion(ctx, **_args())
        rows = _rows(env)
        view = suggestion_view(env.conn, env.parts.panel.suggestion(out["id"]))

    assert out == {"ok": True, "id": rows[0]["id"], "remaining": 1}
    assert len(rows) == 1 and rows[0]["state"] == "proposed" and rows[0]["week"] == "2026-W45"
    assert rows[0]["conversation_id"] == ctx.conversation_id
    assert [(e.kind, e.data) for e in ctx.events] == [("suggestion_proposed", {"id": out["id"]})]
    assert view == {
        "id": out["id"], "kind": "task", "title": "가짜 제안", "area": "career", "size_min": 30, "per_week": None,
        "due_hint": None, "experts": ["career"],
        "evidence": [{**EV_TASK, "href": "/todos/"}, {**EV_BENCH, "href": None}], "state": "proposed",
        "week": "2026-W45",
    }
    (rec,) = [r for r in caplog.records if r.getMessage() == "panel_suggestion"]
    assert (rec.result, rec.area, rec.kind) == ("ok", "career", "task")
    assert "가짜" not in caplog.text


@pytest.mark.parametrize(("evidence", "code"), [
    ([EV_BENCH], "no_personal_evidence"),
    ([{"type": "record", "ref": "task:999", "note": "가짜 근거"}, EV_BENCH], "unknown_ref"),
])
async def test_propose_rejections(tmp_path, evidence, code):
    async with BeEnv.start(tmp_path, start=WED) as env:
        _task(env)
        ctx = _manager(_conv(env))
        out = env.parts.tools.propose_suggestion(ctx, **_args(evidence=evidence))
        rows = _rows(env)
    msg = {
        "no_personal_evidence": "내 기록이나 내가 한 말 근거가 없어요. 질문으로 바꾸거나 근거를 더해 주세요.",
        "unknown_ref": "없는 기록을 근거로 댔어요. 참조를 고쳐 주세요.",
    }[code]
    assert out == {"error": msg, "rejected": code}
    assert ctx.events == [] and rows == [] and ctx.panel_rejects == 1


async def test_propose_shape_errors_not_counted(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        _task(env)
        ctx = _manager(_conv(env))
        t = env.parts.tools
        bad = [
            _args(kind="goal"), _args(title=" "), _args(title="가" * 61), _args(title="두 줄\n제목"),
            _args(area="money"), _args(size_min=4), _args(size_min=121), _args(size_min=30.0), _args(size_min=True),
            _args(kind="habit"), _args(kind="habit", per_week=8), _args(per_week=2),
            _args(due_hint="2026-11-03"), _args(due_hint="2027-01-04"), _args(due_hint="11/05"),
            _args(experts=[]), _args(experts=["career", "career"]), _args(experts=["coach"]),
            _args(experts=list(EXPERT_KEYS) + ["career"]), _args(evidence=[]), _args(evidence="task:1"),
        ]
        outs = [t.propose_suggestion(ctx, **a) for a in bad]
        edge = [
            t.propose_suggestion(ctx, **_args(title="  가짜 제안 둘  ", due_hint="2027-01-03")),
            t.propose_suggestion(ctx, **_args(kind="habit", per_week=7, title="가짜 습관", due_hint="2026-11-04")),
        ]
        titles = [r["title"] for r in _rows(env)]
    for a, o in zip(bad, outs, strict=True):
        assert "error" in o and "rejected" not in o, (a, o)
    assert ctx.panel_rejects == 0
    assert all(o.get("ok") for o in edge), edge
    assert titles == ["가짜 제안 둘", "가짜 습관"]


async def test_propose_only_manager_chat(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        _task(env)
        t = env.parts.tools
        sec = RunContext(_conv(env, "secretary"), None, channel="app", in_brain=True)
        dayend = RunContext(None, None, agent="manager", kind="dayend", in_brain=True)
        outs = [t.propose_suggestion(c, **_args()) for c in (sec, dayend)]
        rows = _rows(env)
    assert outs == [{"error": MSG_NOT_HERE}] * 2 and MSG_NOT_HERE == "쓸 수 없는 도구예요."
    assert rows == []


async def test_budget_exhausted_no_card(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        _task(env)
        t = env.parts.tools
        conv = _conv(env)
        first = t.propose_suggestion(_manager(conv), **_args(title="가짜 하나"))
        second = t.propose_suggestion(_manager(conv), **_args(title="가짜 둘"))
        ctx = _manager(conv)
        third = t.propose_suggestion(ctx, **_args(title="가짜 셋"))
        n = len(_rows(env))
    assert (first["remaining"], second["remaining"]) == (1, 0)
    assert third == {"error": "이번 주 제안은 다 냈어요.", "rejected": "budget_exhausted"}
    assert ctx.events == [] and n == 2


async def test_retry_once_per_message(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        _task(env)
        t = env.parts.tools
        conv = _conv(env)
        ctx = _manager(conv)
        r1 = t.propose_suggestion(ctx, **_args(evidence=[EV_BENCH]))
        r2 = t.propose_suggestion(ctx, **_args(evidence=[EV_BENCH]))
        r3 = t.propose_suggestion(ctx, **_args())
        fresh = t.propose_suggestion(_manager(conv), **_args())
    assert r1["rejected"] == r2["rejected"] == "no_personal_evidence"
    assert r3 == {"error": "이번 메시지에서는 더 낼 수 없어요. 질문으로 바꿔 주세요.", "rejected": "retry_used"}
    assert ctx.panel_rejects == 3 and ctx.events == []
    assert fresh["ok"] is True


async def test_too_big_again_and_not_interested(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        _task(env)
        health_task = _task(env, "health")
        t = env.parts.tools
        conv = _conv(env)
        _set_budget(env, 5)
        _dismissed(env, area="career", title="가짜 큰 제안", experts=["career"], reason="too_big", days_ago=2,
                   size_min=60)
        big = t.propose_suggestion(_manager(conv), **_args(size_min=31))
        half = t.propose_suggestion(_manager(conv), **_args(size_min=30))

        ev = [{"type": "record", "ref": f"task:{health_task}", "note": "가짜 근거"}]
        walk = {"area": "health", "experts": ["health"], "evidence": ev}
        old = _dismissed(env, area="health", title="주 2회 걷기", experts=["health"], reason="not_interested",
                         days_ago=29)
        recent = t.propose_suggestion(_manager(conv), **_args(title="주2회 걷기!", **walk))
        other = t.propose_suggestion(_manager(conv), **_args(title="주2회 걷기!", **{**walk, "experts": ["health", "psych"]}))
        with transaction(env.conn):
            env.conn.execute("UPDATE panel_suggestions SET decided_at = ? WHERE id = ?",
                             (to_iso(env.clock.now() - timedelta(days=31)), old))
        later = t.propose_suggestion(_manager(conv), **_args(title="주2회 걷기!", **walk))
    assert big == {"error": "지난번에 너무 크다고 버렸어요. 30분 이하로 줄여 주세요.", "rejected": "too_big_again"}
    assert half["ok"] is True
    assert recent == {"error": "30일 안에 관심 없다고 버린 제안이에요.", "rejected": "not_interested_recent"}
    assert other["ok"] is True and later["ok"] is True


def test_normalize_title():
    assert normalize_title("주 2회 걷기") == normalize_title("주2회_걷기!") == "주2회걷기"
    assert normalize_title(" Walk, Twice. ") == "walktwice"


def test_write_tool_specs():
    required = {
        "propose_suggestion": ["kind", "title", "area", "size_min", "experts", "evidence"],
        "save_statement": ["kind", "text"],
        "record_prediction": ["metric", "predicted", "due"],
    }
    for name, req in required.items():
        desc, schema = _SPECS[name]
        assert schema["required"] == req and set(req) <= set(schema["properties"]), name
        assert "준비 중" not in desc
        for word in (*banned_words(), *PANEL_EXTRA_BANNED):
            assert word not in desc, (name, word)
    assert _SPECS["propose_suggestion"][1]["properties"]["experts"]["items"]["enum"] == list(EXPERT_KEYS)


def test_expert_keys_match_tool_table():
    assert list(EXPERT_KEYS) == list(EXPERT_TOOLS) == ["career", "finance", "health", "image", "relationship", "psych"]


async def test_monday_2am_counts_last_week(tmp_path):
    async with BeEnv.start(tmp_path, start=kst(2026, 11, 9, 2, 0)) as env:
        _task(env)
        out = env.parts.tools.propose_suggestion(_manager(_conv(env)), **_args())
        (row,) = _rows(env)
    assert out["ok"] is True and row["week"] == "2026-W45"


# --- 내가 한 말 (5.4, 1장 7) ---


async def test_save_statement_rules(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        t = env.parts.tools
        conv = _conv(env)
        text = "지난달 사적으로 만난 사람은 가짜 둘이에요"
        first = t.save_statement(_manager(conv), kind="fact", area="relationships", text=text)
        again = t.save_statement(_manager(conv), kind="fact", area="relationships", text=f" {text} ")
        secret = t.save_statement(_manager(conv), kind="fact", area=None, text="비밀번호는 1234")
        dec = t.save_statement(_manager(conv), kind="decision", area="career", text="가짜 결정 하나", key="fake_choice")
        seeded = t.save_statement(_manager(conv), kind="decision", area="career", text="가짜 결정 둘", key="career_first")
        bad = [
            t.save_statement(_manager(conv), kind="wish", text="가짜"),
            t.save_statement(_manager(conv), kind="fact", area="money", text="가짜"),
            t.save_statement(_manager(conv), kind="fact", text=""),
            t.save_statement(_manager(conv), kind="fact", text="가" * 201),
            t.save_statement(_manager(conv), kind="fact", text="두 줄\n말"),
            t.save_statement(_manager(conv), kind="decision", text="가짜 결정", key=None),
            t.save_statement(_manager(conv), kind="decision", text="가짜 결정", key="Bad-Key"),
            t.save_statement(_manager(conv), kind="fact", text="가짜", key="fake_key"),
        ]
        sec = t.save_statement(RunContext(_conv(env, "secretary"), None, channel="app", in_brain=True),
                               kind="fact", text="가짜 사실")
        rows = env.conn.execute(
            "SELECT kind, area, key, text, source_ref FROM owner_statements WHERE key IS NOT 'career_first' ORDER BY id"
        ).fetchall()
    assert first["ok"] is True and first["ref"].startswith("statement:")
    assert again == first
    assert secret == {"error": "식별 정보는 저장하지 않아요."}
    assert dec == {"ok": True, "ref": "decision:fake_choice"}
    assert seeded == {"error": "이미 있는 결정이에요."}
    assert all("error" in b for b in bad), bad
    assert sec == {"error": MSG_NOT_HERE}
    assert [tuple(r) for r in rows] == [
        ("fact", "relationships", None, text, f"conversation:{conv}"),
        ("decision", "career", "fake_choice", "가짜 결정 하나", f"conversation:{conv}"),
    ]


# --- 예측 (9장) ---


async def test_record_prediction_rules(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        t = env.parts.tools
        conv = _conv(env)
        fat = t.record_prediction(_manager(conv), metric="body_fat_pct", predicted=19.0, due="2027-02-02")
        axis = t.record_prediction(_manager(conv), metric="axis:health", predicted=55, due="2026-11-05")
        third = t.record_prediction(_manager(conv), metric="weight_kg", predicted=70, due="2027-01-01")
        other = _conv(env)
        bad = [
            t.record_prediction(_manager(other), metric="profile_sex", predicted=1, due="2027-01-01"),
            t.record_prediction(_manager(other), metric="body_fat_pct", predicted=19.0, due="2026-11-04"),
            t.record_prediction(_manager(other), metric="body_fat_pct", predicted=19.0, due="2027-12-09"),
            t.record_prediction(_manager(other), metric="body_fat_pct", predicted=99.0, due="2027-01-01"),
            t.record_prediction(_manager(other), metric="body_fat_pct", predicted=True, due="2027-01-01"),
            t.record_prediction(_manager(other), metric="axis:charm", predicted=50, due="2027-01-01"),
            t.record_prediction(_manager(other), metric="cert", predicted=1, due="2027-01-01"),
        ]
        edge = t.record_prediction(_manager(other), metric="weight_kg", predicted=70, due="2027-11-04")
        sec = t.record_prediction(RunContext(_conv(env, "secretary"), None, channel="app", in_brain=True),
                                  metric="weight_kg", predicted=70, due="2027-01-01")
        rows = env.conn.execute("SELECT metric, predicted, due, conversation_id FROM panel_predictions ORDER BY id").fetchall()
    assert fat["ok"] is True and axis["ok"] is True and edge["ok"] is True
    assert third == {"error": "예측은 한 대화에 2개까지예요."}
    assert all("error" in b for b in bad), bad
    assert sec == {"error": MSG_NOT_HERE}
    assert [tuple(r) for r in rows] == [
        ("body_fat_pct", 19.0, "2027-02-02", conv), ("axis:health", 55.0, "2026-11-05", conv),
        ("weight_kg", 70.0, "2027-11-04", other),
    ]


# --- 카드 글 금지어 (T12) ---


async def test_card_copy_banned(tmp_path):
    async with BeEnv.start(tmp_path, start=WED) as env:
        _task(env)
        t = env.parts.tools
        conv = _conv(env)
        title = t.propose_suggestion(_manager(conv), **_args(title="연속 3일 하기"))
        note = t.propose_suggestion(_manager(conv), **_args(evidence=[{**EV_TASK, "note": "못 했던 것"}]))
        said = t.save_statement(_manager(conv), kind="fact", area="career", text="나는 뒤처졌다")
        n = len(_rows(env)) + env.conn.execute(
            "SELECT COUNT(*) FROM owner_statements WHERE key IS NOT 'career_first'"
        ).fetchone()[0]
    for out in (title, note, said):
        assert "error" in out and "rejected" not in out, out
    assert n == 0


# --- 스트림의 제안 카드 (7장, 11장) ---


async def test_suggestion_card_in_stream(tmp_path):
    script = [FakeTurn([("propose_suggestion", _args())], "제안 하나를 냈어요.")]
    async with BeEnv.start(tmp_path, start=WED, script=script) as env:
        _task(env)
        _, raw = await env.chat("이번 주 뭐 할까?", agent="manager")
        chunks = parse_sse(raw)
        (row,) = _rows(env)
    inputs = [c for c in chunks if c.get("type") == "tool-input-available" and c.get("toolName") == "ui_panel_suggestion"]
    assert len(inputs) == 1
    card = inputs[0]
    assert card["toolCallId"] == "h_suggest_1" and card["input"] == {"suggestion_id": row["id"]}
    (output,) = [c for c in chunks if c.get("type") == "tool-output-available" and c.get("toolCallId") == "h_suggest_1"]
    assert output["output"]["ok"] is True
    suggestion = output["output"]["data"]["suggestion"]
    assert suggestion["title"] == "가짜 제안" and suggestion["id"] == row["id"]
    assert suggestion["evidence"][0]["href"] == "/todos/"


async def test_manager_photo_measures_path(tmp_path):
    """스펙 2장, SP13 6.3: 라이프 매니저 대화에 결과지 사진 → 두뇌 입력에 이미지 → 측정값 확인 카드 → 저장."""
    async with BeEnv.start(tmp_path, start=WED) as env:
        status, body = await upload(env, jpeg(1024, 768, pad=7), origin="chat", client_msg_id="ph-1")
        assert status == 201, body
        pid = body["id"]
        rows = [{"metric": "body_fat_pct", "value": 21.5, "measured_on": "2026-11-03"}]
        env.brain.script.append(FakeTurn(
            [("propose_measures", {"rows": rows, "source_kind": "photo", "source_ref": f"photo:{pid}"})],
            "카드에서 확인해 주세요.",
        ))
        parts = [{"type": "data-photo", "data": {"photo_id": pid}}, {"type": "text", "text": "결과지 올려요"}]
        _, raw = await env.chat(parts=parts, agent="manager")
        chunks = parse_sse(raw)
        call = env.brain.calls[0]
        p = env.parts.tools.photos.get(env.conn, pid)
        data = (env.parts.tools.photo_files.root / p.path).read_bytes()
        (card,) = [c for c in chunks if c.get("type") == "tool-input-available"
                   and c.get("toolName") == "ui_measure_confirm"]
        before = env.conn.execute("SELECT COUNT(*) FROM standing_measures").fetchone()[0]
        status, _ = await env.action("save_measures", card["input"])
        saved = env.conn.execute(
            "SELECT metric, value_num, source_ref FROM standing_measures WHERE deleted_at IS NULL"
        ).fetchall()
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(data).decode("ascii")}}
    assert call["run_ctx"].agent == "manager"
    assert image in call["prompt"]
    assert before == 0 and status == 200
    assert [tuple(r) for r in saved] == [("body_fat_pct", 21.5, f"photo:{pid}")]

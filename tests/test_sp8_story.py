"""SP8 수용 이야기 (스펙 1장 완료 조건 1~12, 13장 "이야기"). `BeEnv` + 가짜 두뇌·시계, 꾸며 낸 4주.

9/28(월) 12:00에 시작해 10/25(일)까지 날마다 건강 습관을 체크하고, 월·수·금에 커리어 할 일을 끝낸다. 10/26 04:01
tick이 10/25의 이룬 순간 2개를 정리하고, 앱에서 하나를 숨기고 하나를 지운다. 단축어가 3일을 보내고, 노트북이 사흘
꺼졌다 켜지면(10/29 04:01 tick) 10/26~10/28을 차례로 정리한다. 텔레그램 `/status`와 텔레그램 대화의 `get_status`에는
순간의 글이 없고, 히스토리 응답은 스키마에 맞는다.

로그·내보내기·원문 기록·활동 `summary` 검사는 `tests/test_api_logging.py`, 쓰기 경로 감시는 `tests/test_write_paths.py`가
같은 흐름(`sp8_story`)으로 본다. 내용은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import jsonschema
from be_env import BeEnv
from curve_sql import area_scores, chapter, milestone
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.api.models import schema_bundle
from my_planner.bot.commands import status_text
from my_planner.domain import RunContext
from my_planner.harness.moments import MOMENTS_SINCE_KEY
from my_planner.logging_setup import setup_logging

START = kst(2026, 9, 28, 12, 0)
FIRST = date(2026, 9, 28)
TODAY = date(2026, 10, 25)
BODY_TOKEN = "body-token-SP8STORY-" + "q" * 40  # 꾸며 낸 값(60자)
# 꾸며 낸 순간의 글. 10/25의 둘(하나 숨김, 하나 지움)과 따라잡기 사흘
MOMENT_HIDE = "꾸민순간가 아침 물 한 잔을 챙겼어요"
MOMENT_DELETE = "꾸민순간나 저녁 산책을 끝까지 즐겼어요"
MOMENT_DAYS = {
    date(2026, 10, 26): "꾸민순간다 물 마시기를 이어 갔어요",
    date(2026, 10, 27): "꾸민순간라 아침 물을 챙겨 마셨어요",
    date(2026, 10, 28): "꾸민순간마 물 마시기를 즐겼어요",
}
MOMENT_TEXTS = (MOMENT_HIDE, MOMENT_DELETE, *MOMENT_DAYS.values())
# 꾸며 낸 몸 기록(걸음 6,000 이상, 잠 7시간 이상: 건강 보너스에 든다)
BODY_DAYS = [
    {"date": "2026-10-24", "steps": 17293, "sleep_minutes": 437},
    {"date": "2026-10-25", "steps": 15847, "sleep_minutes": 451},
    {"date": "2026-10-26", "steps": 16391, "sleep_minutes": 468},
]
BODY_NUMBERS = ("17293", "15847", "16391", "437", "451", "468")
# 순간 호출마다 다른 세션 id(정규 UUID 모양): 호출 뒤 그 세션 파일을 지우는지 본다(6.3, 결정 18)
SESSION_IDS = {
    date(2026, 10, 25): "0f8c2a1e-5b3d-4c7a-9e21-6a4b8c0d1e01",
    date(2026, 10, 26): "0f8c2a1e-5b3d-4c7a-9e21-6a4b8c0d1e02",
    date(2026, 10, 27): "0f8c2a1e-5b3d-4c7a-9e21-6a4b8c0d1e03",
    date(2026, 10, 28): "0f8c2a1e-5b3d-4c7a-9e21-6a4b8c0d1e04",
}
CHAT_SID = "0f8c2a1e-5b3d-4c7a-9e21-6a4b8c0d1eff"
SP8_STAT_FIELDS = ("bonus", "effective_score", "activity")
SP8_TOP_FIELDS = ("moments", "moments_hidden", "body")


def _validate(model: str, body: Any) -> None:
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


def sp7_view(snap: dict[str, Any]) -> dict[str, Any]:
    """SP7 때의 스냅샷 모양: SP8이 더한 필드(`stats[]`의 보너스·근거, `moments`, `moments_hidden`, `body`)를 뺀다."""
    out = {k: v for k, v in snap.items() if k not in SP8_TOP_FIELDS}
    out["stats"] = [{k: v for k, v in s.items() if k not in SP8_STAT_FIELDS} for s in snap["stats"]]
    return out


def _save(d: date, *items: tuple[str, str]) -> tuple[str, dict[str, Any]]:
    moments = [{"text": text, "area": "health", "sources": [ref]} for text, ref in items]
    return ("save_moments", {"date": d.isoformat(), "moments": moments})


def _plant_session(proj: Path, sid: str) -> list[Path]:
    """가짜 CLI 설정 폴더에 그 세션의 jsonl과 하위 폴더를 둔다(내용은 꾸민 한 줄)."""
    f = proj / f"{sid}.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    sub = proj / sid
    sub.mkdir()
    (sub / "part.jsonl").write_text("{}\n", encoding="utf-8")
    return [f, sub]


async def _status(env: BeEnv) -> dict[str, Any]:
    resp = await env.get("/status")
    body = await resp.json()
    assert resp.status == 200, body
    _validate("Status", body)
    return body


def _stat(snap: dict[str, Any], area: str) -> dict[str, Any]:
    return next(s for s in snap["stats"] if s["area"] == area)


async def sp8_story(tmp_path: Path) -> dict[str, Any]:
    """이야기 전체를 돌리고 단언할 값을 모은다. BE가 멈춘 뒤의 파일(로그, 원문 기록, 내보내기)도 경로로 준다."""
    s: dict[str, Any] = {}
    async with BeEnv.start(tmp_path, start=START, moments=True, body_token=BODY_TOKEN) as env:
        p = env.parts
        p.runner.checkins = False  # 회차 없이 하루 한 번 작업만(4주 tick이 두뇌 시나리오를 쓰지 않게)
        p.state.set(MOMENTS_SINCE_KEY, TODAY.isoformat())  # 그 전 날은 고르지 않는다
        claude = tmp_path / "claude"
        proj = claude / "projects" / "-home-x"
        proj.mkdir(parents=True)
        p.dispatcher.claude_config_dir = claude
        state_dir = env.settings.paths.state_dir
        setup_logging(state_dir, 30)

        # 건강 Q4 점수 4(Q3 6: 디버프), 커리어 6. 경제는 점수 없음(조건 2)
        area_scores(env.conn, "2026-Q3", health=6)
        area_scores(env.conn, "2026-Q4", health=4, career=6)
        ch = chapter(env.conn, "꾸민 지금 시기", "2020-01", ladder_remembered=6)
        milestone(env.conn, "꾸민 이직", "2021-03", kind="turning_point", chapter_id=ch, area="career")
        milestone(env.conn, "꾸민민감사건", "2022-05", kind="low", chapter_id=ch, sensitive=1)
        env.conn.commit()

        # --- 꾸며 낸 4주: 9/28(월) ~ 10/25(일) ---
        code, added = await env.action("add_habit", {"title": "꾸민 물 마시기", "area": "health", "kind": "daily"})
        assert code == 200, added
        hid = added["result"]["id"]
        s["habit_id"] = hid
        n = 0
        d = FIRST
        while d <= TODAY:
            env.clock.set(kst(d.year, d.month, d.day, 12, 0))
            await env.tick()
            code, body = await env.action("check_habit", {"id": hid})
            assert (code, body["status"]) == (200, "applied"), body
            if d.weekday() in (0, 2, 4):  # 월·수·금
                n += 1
                _, task = await env.action("add_task", {"title": f"꾸민 커리어 일 {n}", "areas": ["career"]})
                code, body = await env.action("complete_task", {"id": task["result"]["id"]})
                assert (code, body["status"]) == (200, "applied"), body
            d += timedelta(days=1)
        s["career_tasks"] = n
        s["status_1025"] = await _status(env)

        # --- 10/26 04:01: 하루 끝 작업이 10/25를 정리한다 ---
        sid = SESSION_IDS[TODAY]
        s["planted"] = _plant_session(proj, sid)
        chat_files = _plant_session(proj, CHAT_SID)
        ref = f"habit:{hid}"
        env.brain.script.append(FakeTurn([_save(TODAY, (MOMENT_HIDE, ref), (MOMENT_DELETE, ref))], "", session_id=sid))
        env.clock.set(kst(2026, 10, 26, 4, 1))
        await env.tick()
        st = await _status(env)
        s["moments_after_job"] = st["moments"]
        by_text = {m["text"]: m["id"] for m in st["moments"]}

        # 앱 상태창: 하나 숨기고, 하나 지운다(확인 → 토큰)
        s["hide"] = await env.action("hide_moment", {"id": by_text[MOMENT_HIDE]})
        s["delete_ask"] = await env.action("delete_moment", {"id": by_text[MOMENT_DELETE]})
        s["delete"] = await env.action(
            "delete_moment", {"id": by_text[MOMENT_DELETE]}, confirm_token=s["delete_ask"][1].get("confirm_token"),
        )
        st = await _status(env)
        s["moments_after_app"] = (st["moments"], st["moments_hidden"])
        s["deleted_row"] = env.conn.execute(
            "SELECT COUNT(*) FROM status_moments WHERE text = ?", (MOMENT_DELETE,)
        ).fetchone()[0]

        # 단축어: 지난 3일
        resp = await env.post("/body", token=BODY_TOKEN, json={"days": BODY_DAYS})
        s["body_post"] = (resp.status, await resp.json())
        s["body_with_api_token"] = (await env.post("/body", json={"days": BODY_DAYS})).status
        s["status_with_body_token"] = (await env.get("/status", token=BODY_TOKEN)).status
        st = await _status(env)
        s["body"] = st["body"]
        s["health_after_body"] = _stat(st, "health")

        # --- 노트북 사흘 꺼짐(tick 없음). 그 사흘에 습관 체크가 하나씩 있었다 ---
        for day in MOMENT_DAYS:
            p.habits.check(hid, day, env.clock.now())
        script = []
        for day, text in MOMENT_DAYS.items():
            s["planted"] += _plant_session(proj, SESSION_IDS[day])
            script.append(FakeTurn([_save(day, (text, ref))], "", session_id=SESSION_IDS[day]))
        env.brain.script.extend(script)
        env.clock.set(kst(2026, 10, 29, 4, 1))
        await env.tick()
        s["moments_dates"] = [c["run_ctx"].moments_date for c in env.brain.calls if c["run_ctx"].kind == "moments"]
        s["moments_calls"] = [c for c in env.brain.calls if c["run_ctx"].kind == "moments"]
        s["day_rows"] = {
            r["date"]: (r["state"], r["saved"])
            for r in env.conn.execute("SELECT date, state, saved FROM status_moment_days")
        }

        # --- 텔레그램: `/status` 글은 SP7 그대로, 대화의 `get_status`에는 날짜와 개수만 ---
        env.clock.set(kst(2026, 10, 29, 12, 0))
        await env.telegram("/status")
        s["telegram_status"] = env.bot.sent[-1][1]
        st = await _status(env)
        s["status_1029"] = st
        s["sp7_status_text"] = status_text(sp7_view(st))

        seen: list[tuple[str, dict[str, Any]]] = []
        orig = p.tools.get_status

        def recording_get_status(ctx: RunContext) -> dict[str, Any]:
            out = orig(ctx)
            seen.append((ctx.channel, out))
            return out

        p.tools.get_status = recording_get_status  # type: ignore[method-assign]
        env.brain.script.append(FakeTurn([("get_status", {})], "꾸민 텔레그램 답: 앱 상태창에서 볼 수 있어요",
                                         session_id=CHAT_SID))
        await env.telegram("꾸민 텔레그램 질문: 요즘 이룬 순간 있어?")
        # 앱 대화의 `get_status`는 글을 받는다(D7). 비서가 그 글을 옮겨 말한 줄은 앱 대화 원문에 남는다(11장)
        quoted = MOMENT_DAYS[date(2026, 10, 28)]
        env.brain.script.append(FakeTurn([("get_status", {})], f"어제는 '{quoted}'가 있었어요", session_id=CHAT_SID))
        await env.chat("꾸민 앱 질문: 어제 이룬 순간 보여 줘")
        p.tools.get_status = orig  # type: ignore[method-assign]
        s["get_status_seen"] = seen
        s["telegram_read_transcript"] = p.tools.read_transcript(
            RunContext(None, None, channel="telegram"), **{"from": "2026-10-25", "to": "2026-10-29"}
        )["text"]
        s["transcripts_without_app_secretary"] = p.transcripts.read_range(
            FIRST, date(2026, 10, 29), drop_app_secretary=True, max_chars=10**7
        )
        s["transcripts_all"] = p.transcripts.read_range(FIRST, date(2026, 10, 29), max_chars=10**7)
        s["telegram_sent"] = [text for _, text in env.bot.sent] + [o.text for o in env.sender.sent]

        # --- 히스토리 ---
        resp = await env.get("/curve/history")
        s["history"] = (resp.status, await resp.json())

        s["summaries"] = [r["summary"] for r in env.conn.execute("SELECT summary FROM activity")]
        s["ledger_kinds"] = {r[0] for r in env.conn.execute("SELECT DISTINCT source_kind FROM status_xp_ledger")}
        s["session_files_left"] = [f for f in s["planted"] if f.exists()]
        s["chat_session_files"] = [f.exists() for f in chat_files]
        s["claude_dir"] = claude
        s["state_dir"] = state_dir
        s["data_dir"] = env.settings.paths.data_dir
        for h in logging.getLogger().handlers:
            h.flush()
    return s


async def test_sp8_story(tmp_path):
    s = await sp8_story(tmp_path)

    # 조건 1·2: 10/25 건강 Q4 4 + 매일 습관 28일 → 1.5, 5.5. 커리어 월·수·금 → 1.2. 점수 없는 영역은 `null`
    st = s["status_1025"]
    health, career, finance = (_stat(st, a) for a in ("health", "career", "finance"))
    assert (health["score"], health["bonus"], health["effective_score"]) == (4, 1.5, 5.5)
    assert health["debuff"] is True  # 디버프는 바탕끼리(6 → 4), 보너스가 지우지 않는다
    assert health["activity"]["habit_checks"] == 28
    assert s["career_tasks"] == 12
    assert (career["score"], career["bonus"], career["effective_score"]) == (6, 1.2, 7.2)
    assert (finance["score"], finance["bonus"], finance["effective_score"]) == (None, 0.0, None)

    # 조건 3: 10/26 04:01 → 10/25의 순간 2개(확인 없이). 조건 5: 앱에서 하나 숨김, 하나 지움(확인 → 토큰)
    assert [m["text"] for m in s["moments_after_job"]] == [MOMENT_HIDE, MOMENT_DELETE]
    assert all(m["date"] == "2026-10-25" and m["sources"] == ["habit"] for m in s["moments_after_job"])
    assert (s["hide"][0], s["hide"][1]["status"]) == (200, "applied") and "undo_id" in s["hide"][1]
    ask = s["delete_ask"][1]
    assert (s["delete_ask"][0], ask["status"], ask["summary"]) == (200, "needs_confirm", "이 순간을 지울까요? 되돌릴 수 없어요.")
    assert (s["delete"][0], s["delete"][1]["status"]) == (200, "applied")
    assert s["moments_after_app"] == ([], 1)
    assert s["deleted_row"] == 0

    # 조건 8: 단축어 3일 → `body.days_7 == 3`. `API_TOKEN`으로는 쓸 수 없고, `BODY_TOKEN`으로는 읽을 수 없다
    assert s["body_post"] == (200, {"saved": 3})
    assert s["body_with_api_token"] == 401 and s["status_with_body_token"] == 401
    assert s["body"]["days_7"] == 3 and s["body"]["last_date"] == "2026-10-26"
    assert s["health_after_body"]["activity"]["body_days"] == 3

    # 조건 4: 사흘 꺼짐 → 10/29 04:01 tick이 10/26~10/28을 오래된 날부터. 두뇌 호출 순서 = 날짜 순
    assert s["moments_dates"] == [TODAY, *MOMENT_DAYS]
    assert s["day_rows"] == {
        "2026-10-25": ("done", 2), "2026-10-26": ("done", 1), "2026-10-27": ("done", 1), "2026-10-28": ("done", 1),
    }
    # 순간 호출 모양(6.3): 새 세션, 세션 저장 끔, `max_turns = 3`. 호출 뒤 그 세션 파일이 없다(대화 세션은 그대로)
    for c in s["moments_calls"]:
        assert (c["session_id"], c["persist_session"], c["max_turns"]) == (None, False, 3)
    assert s["session_files_left"] == [] and s["chat_session_files"] == [True, True]
    # 조건 6: 순간은 경험치를 주지 않는다(원장 `source_kind`는 SP7 그대로)
    assert not any("moment" in k for k in s["ledger_kinds"])

    # 텔레그램 `/status` 글은 같은 DB의 SP7 기준 글과 같다(새 줄 없음)
    tg = s["telegram_status"]
    assert tg == s["sp7_status_text"] == status_text(s["status_1029"])
    assert "커리어 6 · 경제 - · 건강 4 ↓ · 관계 - · 배움 - · 삶의 질 -\n↓ 건강 6 → 4: 회복 퀘스트" in tg
    for word in ("요즘", "순간", "걸음", "잠", "+", "5.5", "7.2", *MOMENT_TEXTS):
        assert word not in tg, word

    # 텔레그램 대화의 `get_status`에는 날짜와 개수만, 앱 대화는 글을 받는다(D7, 10.3)
    (tg_out, app_out) = s["get_status_seen"]
    assert tg_out[0] == "telegram" and app_out[0] == "app"
    assert tg_out[1]["moments"] == [{"date": f"2026-10-{n}", "count": 1} for n in (28, 27, 26)]
    tg_json = json.dumps(tg_out[1], ensure_ascii=False)
    for text in MOMENT_TEXTS:
        assert text not in tg_json, text
    assert [m["text"] for m in app_out[1]["moments"]] == [MOMENT_DAYS[date(2026, 10, n)] for n in (28, 27, 26)]
    # 텔레그램 통로의 `read_transcript`는 앱 대화의 비서 줄을 빼고 준다(11장). 텔레그램에 나간 글에도 없다
    assert "꾸민 앱 질문" in s["telegram_read_transcript"]
    for text in MOMENT_TEXTS:
        assert text not in s["telegram_read_transcript"], text
        assert not any(text in sent for sent in s["telegram_sent"]), text

    # 히스토리: 200, 스키마에 맞고, 민감 사건은 개수와 해만
    code, history = s["history"]
    assert code == 200
    _validate("CurveHistory", history)
    (chap,) = history["chapters"]
    assert [e["title"] for e in chap["events"]] == ["꾸민 이직"]
    assert chap["hidden_sensitive"] == {"count": 1, "years": [2022]}
    assert "꾸민민감사건" not in json.dumps(history, ensure_ascii=False)

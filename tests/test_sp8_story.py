"""SP8 수용 이야기 (스펙 1장 완료 조건 1~12, 13장 "이야기"). 흐름은 `tests/sp8_story_flow.py`, 여기는 단언.

로그·내보내기·원문 기록·활동 `summary`는 `tests/test_api_logging.py`, 쓰기 경로는 `tests/test_write_paths.py`가 같은 흐름으로
본다. 내용은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from claude_agent_sdk import ResultMessage
from sp8_story_flow import (
    MOMENT_DAYS,
    MOMENT_DELETE,
    MOMENT_HIDE,
    MOMENT_TEXTS,
    TODAY,
    sp8_story,
    stat,
    validate,
)

from my_planner.bot.commands import status_text
from my_planner.harness import brain as brain_mod
from my_planner.harness.moments import moments_system_prompt


async def _replay_options(calls: list[dict[str, Any]], tmp_path, monkeypatch) -> list[tuple[str, Any]]:
    """가짜 두뇌가 받은 호출 인자 그대로 실제 `ClaudeBrain.run`을 부르고, SDK에 넘긴 `ClaudeAgentOptions`를 모은다.
    `query`와 도구 서버만 가짜다(옵션은 실제 `build_options`가 만든다)."""
    built: list[tuple[str, Any]] = []
    real_build = brain_mod.build_options
    kind = {"now": ""}

    def capture(**kw: Any) -> Any:
        opts = real_build(**kw)
        built.append((kind["now"], opts))
        return opts

    async def fake_query(*, prompt, options):
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="0f8c2a1e-5b3d-4c7a-9e21-6a4b8c0d1e99", result="")

    monkeypatch.setattr(brain_mod, "query", fake_query)
    monkeypatch.setattr(brain_mod, "build_planner_server", lambda tools, ctx: {"type": "sdk", "name": "planner"})
    monkeypatch.setattr(brain_mod, "build_options", capture)
    brain = brain_mod.ClaudeBrain(lambda: None, tmp_path / "replay-wd", max_turns=10)
    for c in calls:
        kind["now"] = c["run_ctx"].kind
        ctx = c["run_ctx"]
        stream, ctx.stream = ctx.stream, None  # 이미 닫힌 앱 스트림에는 쓰지 않는다(옵션은 부분 메시지 말고 같다)
        try:
            await brain.run(c["prompt"], session_id=c["session_id"], run_ctx=ctx, fork_session=c["fork_session"],
                            system_prompt=c["system_prompt"], max_turns=c["max_turns"],
                            persist_session=c["persist_session"])
        finally:
            ctx.stream = stream
    return built


async def test_sp8_story(tmp_path, monkeypatch):
    s = await sp8_story(tmp_path)

    # 조건 1·2: 10/25 건강 Q4 4 + 매일 습관 28일 → 1.5, 5.5. 커리어 월·수·금 → 1.2. 점수 없는 영역은 `null`
    st = s["status_1025"]
    health, career, finance = (stat(st, a) for a in ("health", "career", "finance"))
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
    # 첫 겹(플래그): 이야기의 두뇌 호출 인자를 실제 `ClaudeBrain.run`에 그대로 넘기면 순간 호출의 SDK 옵션에만
    # `extra_args = {"no-session-persistence": None}`이 실린다(대화 호출은 세션을 저장한다). CLI가 그 플래그로 정말 파일을
    # 쓰지 않는지는 로그인한 두뇌로만 볼 수 있다(사람 관문 H3, S-SP8-1)
    built = await _replay_options(s["brain_calls"], tmp_path, monkeypatch)
    assert [k for k, _ in built] == ["moments"] * 4 + ["chat", "chat"]
    for kind, opts in built:
        if kind == "moments":
            assert opts.extra_args == {"no-session-persistence": None} and opts.resume is None
            assert opts.max_turns == 3 and opts.system_prompt == moments_system_prompt()
        else:
            assert opts.extra_args == {}
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
    validate("CurveHistory", history)
    (chap,) = history["chapters"]
    assert [e["title"] for e in chap["events"]] == ["꾸민 이직"]
    assert chap["hidden_sensitive"] == {"count": 1, "years": [2022]}
    assert "꾸민민감사건" not in json.dumps(history, ensure_ascii=False)

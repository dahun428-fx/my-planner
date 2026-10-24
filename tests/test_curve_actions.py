"""인생 곡선 쓰기와 곡선 도구, `/actions`·되돌리기 (SP3-4 스펙 10장, 5.4, 6.4.2, 6.4.3, 9.4). 내용은 꾸며 낸 것이다."""

from datetime import date, timedelta

from be_env import BeEnv
from curve_sql import area_scores
from test_dispatcher_messages import kst

from my_planner.domain import ConversationKind, LoopKey, RunContext

SAT_1300 = kst(2026, 10, 24, 13, 0)  # 토요일 낮: 예정된 회차가 없다


def _ctx(conversation_id=None):
    return RunContext(conversation_id=conversation_id, run_id=None)


def _ladder(env, period):
    r = env.conn.execute("SELECT now, future, note FROM curve_ladder_scores WHERE period = ?", (period,)).fetchone()
    return tuple(r) if r else None


def _areas(env, period):
    rows = env.conn.execute(
        "SELECT area, score, note, recovery_quest FROM curve_area_scores WHERE period = ? ORDER BY area", (period,)
    ).fetchall()
    return {r["area"]: (r["score"], r["note"], r["recovery_quest"]) for r in rows}


def _draft(env, title="꾸민 사건", kind="high", date_text="2019", **kw):
    return env.parts.curve.add_milestone(date_text=date_text, kind=kind, title=title, status="draft", origin="chat",
                                         **kw).id


def _chapter_draft(env, title="꾸민 챕터", start="2019-01", end=None):
    return env.parts.curve.add_chapter(title=title, start_month=start, end_month=end, status="draft",
                                       origin="review").id


async def _undo(env, aid):
    resp = await env.post(f"/activity/{aid}/undo", json={"client_msg_id": f"undo-{aid}"})
    return resp.status, await resp.json()


# --- 사다리와 영역 점수 (10장) ---


async def test_ladder_future_only_first_then_now_keeps_future(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        status, first = await env.action("record_ladder_score", {"future": 8})
        after_first = _ladder(env, "2026-10")
        status2, second = await env.action("record_ladder_score", {"now": 6, "note": "꾸민 메모"})
        after_second = _ladder(env, "2026-10")
        rows = [(r["kind"], r["target"], r["summary"]) for r in env.activity()]

    assert status == 200 and first["result"] == {"period": "2026-10", "now": None, "future": 8, "note": None}
    assert first["confirmation"] == "✓ 사다리를 기록했어요 (2026-10): 5년 뒤 8"
    assert after_first == (None, 8, None)
    assert status2 == 200 and after_second == (6, 8, "꾸민 메모")
    assert second["confirmation"] == "✓ 사다리를 기록했어요 (2026-10): 지금 6 · 5년 뒤 8"
    assert "undo_id" in second
    assert rows[-1] == ("ladder_recorded", "ladder:2026-10", "✓ 사다리를 기록했어요 (2026-10): 지금 6 · 5년 뒤 8")
    assert "꾸민 메모" not in str(rows)  # 메모는 활동 요약에 없다


async def test_ladder_range_and_future_month_rejected(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        t = env.parts.tools
        out = [
            t.record_ladder_score(_ctx()),
            t.record_ladder_score(_ctx(), now=11),
            t.record_ladder_score(_ctx(), future=-1),
            t.record_ladder_score(_ctx(), now=True),
            t.record_ladder_score(_ctx(), now="7"),
            t.record_ladder_score(_ctx(), now=5, period="2026-11"),
            t.record_ladder_score(_ctx(), now=5, period="2026-13"),
            t.record_ladder_score(_ctx(), now=5, period="2026-9"),
        ]
        edges = (t.record_ladder_score(_ctx(), now=0, period="2025-12"), t.record_ladder_score(_ctx(), future=10))
        rows = env.conn.execute("SELECT period FROM curve_ladder_scores ORDER BY period").fetchall()

    assert all("error" in o for o in out), out
    assert out[5]["error"] == "아직 오지 않은 달의 사다리 점수는 기록할 수 없어요."
    assert [e.get("error") for e in edges] == [None, None]
    assert [r["period"] for r in rows] == ["2025-12", "2026-10"]


async def test_area_scores_range_names_and_quests_only_for_down(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        area_scores(env.conn, "2026-Q3", health=6, career=5)
        env.conn.commit()
        t = env.parts.tools
        bad = [
            t.record_area_scores(_ctx(), scores={}),
            t.record_area_scores(_ctx(), scores={"health": 0}),
            t.record_area_scores(_ctx(), scores={"health": 11}),
            t.record_area_scores(_ctx(), scores={"sleep": 5}),
            t.record_area_scores(_ctx(), scores={"health": 5}, period="2027-Q1"),
            t.record_area_scores(_ctx(), scores={"health": 5}, period="2026-Q5"),
            # 오르거나 같은 영역, 지난 분기 점수가 없는 영역에는 회복 퀘스트를 받지 않는다
            t.record_area_scores(_ctx(), scores={"career": 5}, recovery_quests={"career": "꾸민 퀘스트"}),
            t.record_area_scores(_ctx(), scores={"finance": 2}, recovery_quests={"finance": "꾸민 퀘스트"}),
            t.record_area_scores(_ctx(), scores={"health": 4}, recovery_quests={"career": "꾸민 퀘스트"}),
            t.record_area_scores(_ctx(), scores={"health": 4}, recovery_quests={"health": "가" * 81}),
        ]
        nothing = _areas(env, "2026-Q4")
        status, ok = await env.action("record_area_scores", {
            "scores": {"health": 4, "career": 7, "quality_of_life": 6}, "notes": {"career": "꾸민 메모"},
            "recovery_quests": {"health": "꾸민 산책"},
        })
        stored = _areas(env, "2026-Q4")

    assert all("error" in o for o in bad), bad
    assert bad[6]["error"] == "recovery_quests는 지난 분기보다 내려간 영역에만 넣을 수 있어요."
    assert nothing == {}
    assert status == 200, ok
    assert ok["result"] == {"period": "2026-Q4", "scores": {"career": 7, "health": 4, "quality_of_life": 6}}
    # 문구 C1: 넣은 영역만, SP1 영역 순서
    assert ok["confirmation"] == "✓ 영역 점수를 기록했어요 (2026-Q4): 커리어 7 · 건강 4 · 삶의 질 6"
    assert stored == {"career": (7, "꾸민 메모", None), "health": (4, None, "꾸민 산책"),
                      "quality_of_life": (6, None, None)}


# --- 사건·챕터 확정과 빼기, 칭호 (9.4) ---


def _titles(env):
    return [r["milestone_id"] for r in env.conn.execute("SELECT milestone_id FROM status_titles ORDER BY id")]


async def test_confirm_high_and_turning_grant_titles_low_does_not(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        hi = _draft(env, "꾸민 고점", "high", "2019")
        turn = _draft(env, "꾸민 전환", "turning_point", "2021-03")
        low = _draft(env, "꾸민 저점", "low", "2020-05-02")
        status, body = await env.action("confirm_milestones", {"ids": [hi, turn, low, 999]})
        titles = _titles(env)
        rows = env.conn.execute("SELECT id, status, draft_since, confirmed_at FROM curve_milestones").fetchall()
        snapshot = await (await env.get("/status")).json()
        (act,) = [r for r in env.activity() if r["kind"] == "milestones_confirmed"]
        targets = [r["target"] for r in env.conn.execute(
            "SELECT target FROM activity_targets WHERE activity_id = ? ORDER BY target", (act["id"],))]
        again = env.parts.tools.confirm_milestones(_ctx(), ids=[hi])

    assert status == 200 and body["result"]["skipped_ids"] == [999]
    assert [m["id"] for m in body["result"]["confirmed"]] == [hi, turn, low]
    assert body["confirmation"].split("\n") == [
        "✓ 저장: 꾸민 고점 (2019, 고점)", "칭호: 「꾸민 고점」의 순간",
        "✓ 저장: 꾸민 전환 (2021-03, 전환점)", "칭호: 「꾸민 전환」을 지나온 사람",
        "✓ 저장: 꾸민 저점 (2020-05-02, 저점)",
    ]
    assert titles == [hi, turn]
    assert all(r["status"] == "confirmed" and r["draft_since"] is None and r["confirmed_at"] for r in rows)
    assert [t["title"] for t in snapshot["titles"]] == ["「꾸민 고점」의 순간", "「꾸민 전환」을 지나온 사람"]
    assert act["target"] is None and targets == sorted(f"milestone:{i}" for i in (hi, turn, low))
    assert act["summary"] == "✓ 저장: 꾸민 고점 (2019, 고점), 꾸민 전환 (2021-03, 전환점), 꾸민 저점 (2020-05-02, 저점)"
    assert again == {"confirmed": [], "skipped_ids": [hi]}  # 이미 확정한 것은 건너뛴다


async def test_drop_milestone_deletes_row_and_confirmed_is_rejected(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        keep = _draft(env, "꾸민 확정")
        gone = _draft(env, "꾸민 초안")
        await env.action("confirm_milestones", {"ids": [keep]})
        status, body = await env.action("drop_milestone", {"id": gone})
        row = env.parts.curve.get_milestone(gone)
        twice = await env.action("drop_milestone", {"id": gone})
        confirmed = await env.action("drop_milestone", {"id": keep})
        other = _draft(env, "꾸민 둘")
        mixed = env.parts.tools.drop_curve_drafts(_ctx(), milestone_ids=[other, keep])
        still = env.parts.curve.get_milestone(other)
        (act,) = [r for r in env.activity() if r["kind"] == "milestone_dropped"]

    assert status == 200 and body["confirmation"] == "✗ 뺐어요: 꾸민 초안"
    assert row is None  # 행을 지운다
    assert "undo_id" not in body and act["undo_json"] is None  # 되돌릴 수 없다
    assert act["target"] == f"milestone:{gone}"
    assert twice[0] == 422 and twice[1]["error"]["message"] == "이미 정리된 사건이에요."
    assert confirmed[0] == 422 and confirmed[1]["error"]["message"] == "확정한 사건이나 챕터는 뺄 수 없어요. 초안만 뺄 수 있어요."
    assert "error" in mixed and still is not None  # 하나라도 확정이면 아무것도 빼지 않는다


async def test_dropping_chapter_draft_nulls_milestone_chapter_id(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        ch = _chapter_draft(env, "꾸민 챕터", "2019-01", "2020-12")
        kept = _chapter_draft(env, "꾸민 확정 챕터", "2021-01")
        m = _draft(env, chapter_id=ch)
        status, body = await env.action("drop_chapter", {"id": ch})
        chapter_row = env.parts.curve.get_chapter(ch)
        milestone = env.parts.curve.get_milestone(m)
        c_status, confirmed = await env.action("confirm_chapters", {"ids": [kept]})
        refused = await env.action("drop_chapter", {"id": kept})
        gone = await env.action("drop_chapter", {"id": ch})

    assert status == 200 and body["confirmation"] == "✗ 뺐어요: 꾸민 챕터"  # 문구 C3
    assert chapter_row is None
    assert milestone is not None and milestone.chapter_id is None
    assert c_status == 200 and confirmed["confirmation"] == "✓ 저장: 꾸민 확정 챕터 (2021-01~지금)"  # 문구 C2
    assert refused[0] == 422
    assert gone[0] == 422 and gone[1]["error"]["message"] == "이미 정리된 챕터예요."


# --- 되돌리기 (6.4.3) ---


async def test_undo_ladder_and_areas_restore_or_delete(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        area_scores(env.conn, "2026-Q4", health=5)
        env.conn.execute(
            "INSERT INTO curve_ladder_scores (period, now, future, note, recorded_at) VALUES "
            "('2026-08', 4, NULL, '꾸민 메모', '2026-09-01T00:00:00.000000+00:00')"
        )
        env.conn.commit()
        _, fresh = await env.action("record_ladder_score", {"now": 3, "period": "2026-09"})
        _, over = await env.action("record_ladder_score", {"now": 7, "future": 9, "period": "2026-08"})
        _, areas = await env.action("record_area_scores", {"scores": {"health": 8, "career": 6}})
        before_undo = (_ladder(env, "2026-08"), _ladder(env, "2026-09"), _areas(env, "2026-Q4"))

        s_over = await _undo(env, over["undo_id"])
        s_fresh = await _undo(env, fresh["undo_id"])
        ladder_after = (_ladder(env, "2026-08"), _ladder(env, "2026-09"))
        ladder_at = env.conn.execute(
            "SELECT recorded_at FROM curve_ladder_scores WHERE period = '2026-08'").fetchone()[0]
        sa = await _undo(env, areas["undo_id"])
        restored = _areas(env, "2026-Q4")
        recorded_at = env.conn.execute(
            "SELECT recorded_at FROM curve_area_scores WHERE period = '2026-Q4' AND area = 'health'").fetchone()[0]
        # 되돌린 뒤 같은 달을 다시 바꾸면 앞선 되돌리기도 막힌다(U3)
        _, again = await env.action("record_ladder_score", {"now": 2, "period": "2026-09"})
        _, again2 = await env.action("record_ladder_score", {"now": 1, "period": "2026-09"})
        blocked = await _undo(env, again["undo_id"])

    assert before_undo == ((7, 9, "꾸민 메모"), (3, None, None),
                           {"career": (6, None, None), "health": (8, None, None)})
    assert s_over[0] == 200 and s_over[1]["confirmation"] == "↩ 되돌림: 사다리 기록 (2026-08)"
    assert s_fresh[0] == 200
    assert ladder_after == ((4, None, "꾸민 메모"), None)  # 이전 행으로, 없었으면 행 삭제
    assert ladder_at == "2026-09-01T00:00:00.000000+00:00"
    assert sa[0] == 200 and sa[1]["confirmation"] == "↩ 되돌림: 영역 점수 기록 (2026-Q4)"
    assert restored == {"health": (5, None, None)}  # 있던 영역은 이전 값, 없던 영역은 지운다
    assert recorded_at == "2026-10-01T00:00:00.000000+00:00"  # 이전 행의 기록 시각 그대로
    assert "undo_id" in again2 and blocked[0] == 409


async def test_undo_confirm_resets_draft_since_and_removes_title(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        m = _draft(env, "꾸민 고점")
        ch = _chapter_draft(env)
        env.clock.advance(days=2)
        _, body = await env.action("confirm_milestones", {"ids": [m]})
        _, cbody = await env.action("confirm_chapters", {"ids": [ch]})
        env.clock.advance(hours=5)
        undo_at = env.clock.now()
        status, undone = await _undo(env, body["undo_id"])
        cstatus, cundone = await _undo(env, cbody["undo_id"])
        row = env.parts.curve.get_milestone(m)
        crow = env.parts.curve.get_chapter(ch)
        titles = _titles(env)
        status_view = await (await env.get("/status")).json()
        ledger = env.conn.execute("SELECT COUNT(*) FROM status_xp_ledger").fetchone()[0]

    assert status == 200 and undone["confirmation"] == "↩ 되돌림: 꾸민 고점 저장"
    assert cstatus == 200 and cundone["confirmation"] == "↩ 되돌림: 꾸민 챕터 저장"
    assert (row.status, row.confirmed_at) == ("draft", None)
    assert row.draft_since is not None and row.draft_since.startswith(undo_at.isoformat()[:19])
    assert crow.status == "draft" and crow.draft_since.startswith(undo_at.isoformat()[:19])
    assert titles == [] and status_view["titles"] == []
    assert ledger == 0


# --- 기간 기본값 (10장) ---


async def test_period_default_from_review_conversation(tmp_path):
    # 11/29(일) 회고를 R1로 넘겨 받아 12/1(화) 아침 브리핑과 합쳐 보냈다. 그 회차 대화에서 12/1에 사다리를 말한다
    async with BeEnv.start(tmp_path, start=kst(2026, 12, 1, 13, 0)) as env:
        p = env.parts
        review = p.runs.ensure(LoopKey.review, kst(2026, 11, 29, 19, 0), "week")
        brief = p.runs.ensure(LoopKey.morning_brief, kst(2026, 12, 1, 8, 0))
        p.runs.add_merged(brief.id, [review.id])
        run_conv = p.convs.open(ConversationKind.run, date(2026, 12, 1), brief.id)
        chat_conv = p.convs.open(ConversationKind.chat, date(2026, 12, 1))
        in_review = p.tools.record_ladder_score(_ctx(run_conv.id), now=7)
        in_chat = p.tools.record_ladder_score(_ctx(chat_conv.id), now=7)
        areas_review = p.tools.record_area_scores(_ctx(run_conv.id), scores={"health": 6})
        plain = p.tools.record_ladder_score(_ctx(), future=9)

    assert in_review["period"] == "2026-11"
    assert in_chat["period"] == "2026-12"
    assert areas_review["period"] == "2026-Q4"
    assert plain["period"] == "2026-12"


# --- 활동 통로 ---


async def test_curve_tool_from_brain_records_secretary_activity(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        env.clock.advance(timedelta(minutes=1))
        from fakes import FakeTurn

        env.brain.script.append(FakeTurn([("record_ladder_score", {"now": 5})], "기록했어요"))
        await env.telegram("이번 달 사다리 5")
        rows = [(r["kind"], r["actor"], r["channel"]) for r in env.activity()]
        out = env.sender.sent[-1].text if env.sender.sent else ""

    assert rows == [("ladder_recorded", "secretary", "telegram")]
    assert "✓ 사다리를 기록했어요 (2026-10): 지금 5" in out


# --- 저장소: 시드가 쓰는 함수 (티켓 12가 부른다) ---


def test_repo_questions_defaults_and_date_precision(conn):
    import pytest

    from my_planner.clock import FakeClock
    from my_planner.store.repos.curve import CurveRepo, date_precision

    repo = CurveRepo(conn, FakeClock(SAT_1300))
    q1, q2 = repo.add_question("꾸민 질문 하나"), repo.add_question("꾸민 질문 둘")
    assert repo.next_open_question().id == q1
    repo.mark_question(q1, "asked")
    asked = conn.execute("SELECT status, asked_at FROM curve_questions WHERE id = ?", (q1,)).fetchone()
    assert asked["status"] == "asked" and asked["asked_at"] is not None
    assert repo.next_open_question().id == q2
    repo.set_area_default("health", "꾸민 퀘스트")
    repo.set_area_default("health", "꾸민 퀘스트 둘")
    assert repo.area_default("health") == "꾸민 퀘스트 둘"
    assert date_precision("2019") == ("year", date(2019, 1, 1))
    assert date_precision("2019-05") == ("month", date(2019, 5, 1))
    assert date_precision("2019-05-02") == ("day", date(2019, 5, 2))
    for bad in ("2023-5", "2019-13", "2019-02-30", "19", "2019-05-02-01", "abcd"):
        with pytest.raises(ValueError):
            date_precision(bad)


async def test_rerecording_area_without_quest_clears_old_quest(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        area_scores(env.conn, "2026-Q3", health=6)
        env.conn.commit()
        t = env.parts.tools
        t.record_area_scores(_ctx(), scores={"health": 4}, recovery_quests={"health": "꾸민 산책"},
                             notes={"health": "꾸민 메모"})
        first = _areas(env, "2026-Q4")
        t.record_area_scores(_ctx(), scores={"health": 7})
        raised = _areas(env, "2026-Q4")
        t.record_area_scores(_ctx(), scores={"health": 5})
        lowered = _areas(env, "2026-Q4")
        status = await (await env.get("/status")).json()

    assert first == {"health": (4, "꾸민 메모", "꾸민 산책")}
    assert raised == {"health": (7, "꾸민 메모", None)}  # 이번 호출에 퀘스트가 없으면 예전 퀘스트를 지운다
    assert lowered == {"health": (5, "꾸민 메모", None)}
    health = next(s for s in status["stats"] if s["area"] == "health")
    assert health["debuff"] is True and health["recovery_quest"] != "꾸민 산책"


async def test_sensitive_milestone_title_masked_in_activity_summary(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        secret = _draft(env, "꾸민 비밀", kind="low", date_text="2020-03", sensitive=True)
        plain = _draft(env, "꾸민 여행")
        _, one = await env.action("confirm_milestones", {"ids": [secret]})
        await env.action("confirm_milestones", {"ids": [plain]})
        listing = await (await env.get("/activity?order=desc")).json()
        status, undone = await _undo(env, one["undo_id"])
        summaries = [r["summary"] for r in env.activity()]

    assert [i["summary"] for i in listing["items"]][::-1] == [
        "✓ 저장: (민감) (2020-03, 저점)", "✓ 저장: 꾸민 여행 (2019, 고점)"]
    assert status == 200 and undone["confirmation"] == "↩ 되돌림: (민감) 저장"
    assert not any("꾸민 비밀" in s for s in summaries)

"""곡선 초안의 만료(행 삭제), `data/curve/chapters.md` 내보내기, 곡선 확인 문구 (SP3-4 스펙 5.4, 부록 A, 문구 C1~C4).

내용은 꾸며 낸 것이다.
"""

from datetime import date, timedelta

from be_env import BeEnv
from test_dispatcher_messages import kst

from my_planner.curve.model import curve_view
from my_planner.domain import RunContext, ToolEvent
from my_planner.loop.runner import expire_curve_drafts
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.tools.confirmations import confirmation_line, undo_summary

SAT_1300 = kst(2026, 10, 24, 13, 0)
FORBIDDEN = ("놓쳤어요", "밀렸어요", "늦었지만", "실패")  # SP1 금지어


def _ctx():
    return RunContext(conversation_id=None, run_id=None)


def _draft(env, title, **kw):
    kw.setdefault("date_text", "2019")
    kw.setdefault("kind", "high")
    return env.parts.curve.add_milestone(title=title, status="draft", origin="chat", **kw).id


def test_confirmation_lines():
    today = date(2026, 10, 24)

    def line(event_kind, **data):
        return confirmation_line(ToolEvent(event_kind, None, data), today)

    lines = [
        line("milestones_confirmed", title="제주 여행", date_text="2019", kind="high"),
        line("milestones_confirmed", title="꾸민 일", date_text="2020-05", kind="low"),
        line("milestones_confirmed", title="꾸민 결심", date_text="2021-03-02", kind="turning_point"),
        line("title_granted", title="「제주 여행」의 순간"),
        line("milestone_dropped", title="제주 여행"),
        line("chapters_confirmed", title="꾸민 시절", start_month="2019-01", end_month="2020-12"),
        line("chapters_confirmed", title="꾸민 지금", start_month="2021-01", end_month=None),
        line("chapter_dropped", title="꾸민 시절"),
        line("ladder_recorded", period="2026-10", now=6, future=8),
        line("ladder_recorded", period="2026-10", now=6, future=None),
        line("ladder_recorded", period="2026-10", now=None, future=8),
        line("area_scores_recorded", period="2026-Q4",
             scores={"quality_of_life": 6, "finance": 5, "career": 7}),
    ]
    assert lines == [
        "✓ 저장: 제주 여행 (2019, 고점)",  # 부록 A 사건 확정
        "✓ 저장: 꾸민 일 (2020-05, 저점)",
        "✓ 저장: 꾸민 결심 (2021-03-02, 전환점)",
        "칭호: 「제주 여행」의 순간",  # 부록 A 칭호 생김
        "✗ 뺐어요: 제주 여행",  # 부록 A 사건 빼기
        "✓ 저장: 꾸민 시절 (2019-01~2020-12)",  # C2
        "✓ 저장: 꾸민 지금 (2021-01~지금)",
        "✗ 뺐어요: 꾸민 시절",  # C3
        "✓ 사다리를 기록했어요 (2026-10): 지금 6 · 5년 뒤 8",  # C4
        "✓ 사다리를 기록했어요 (2026-10): 지금 6",
        "✓ 사다리를 기록했어요 (2026-10): 5년 뒤 8",
        "✓ 영역 점수를 기록했어요 (2026-Q4): 커리어 7 · 경제 5 · 삶의 질 6",  # C1: SP1 영역 순서
    ]
    undos = [
        undo_summary(lines[0]), undo_summary("✓ 저장: 가 (2019, 고점), 나 (2020-05, 저점)"), undo_summary(lines[5]),
        undo_summary(lines[8]), undo_summary(lines[11]),
    ]
    assert undos == [
        "↩ 되돌림: 제주 여행 저장", "↩ 되돌림: 가, 나 저장", "↩ 되돌림: 꾸민 시절 저장",
        "↩ 되돌림: 사다리 기록 (2026-10)", "↩ 되돌림: 영역 점수 기록 (2026-Q4)",
    ]
    assert not any(w in text for text in [*lines, *undos] for w in FORBIDDEN)


async def test_export_chapters_md_masks_sensitive(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        cv = env.parts.curve
        ch = cv.add_chapter(title="꾸민 시절", start_month="2019-01", end_month="2020-12", status="draft",
                            origin="review", theme="꾸민 주제").id
        open_ch = cv.add_chapter(title="꾸민 지금", start_month="2021-01", status="draft", origin="review").id
        m1 = _draft(env, "꾸민 여행", chapter_id=ch, note="꾸민 메모")
        m2 = _draft(env, "꾸민 비밀", date_text="2020-03", kind="low", chapter_id=ch, sensitive=True)
        m3 = _draft(env, "꾸민 바깥 일", date_text="2018")
        _draft(env, "꾸민 남은 초안")
        await env.action("confirm_chapters", {"ids": [ch, open_ch]})
        await env.action("confirm_milestones", {"ids": [m1, m2, m3]})
        path = env.settings.paths.data_dir / "curve" / "chapters.md"
        text = path.read_text(encoding="utf-8")

    assert text.splitlines() == [
        "# 인생 곡선",
        "",
        "_이 파일은 자동으로 다시 만들어져요. 직접 고치지 마세요._",
        "",
        "## 꾸민 시절 (2019-01~2020-12)",
        "",
        "꾸민 주제",
        "",
        "- 2019 · 고점 · 꾸민 여행",
        "- 2020-03 · 저점 · (민감)",
        "",
        "## 꾸민 지금 (2021-01~지금)",
        "",
        "(사건 없음)",
        "",
        "## 챕터 밖 사건",
        "",
        "- 2018 · 고점 · 꾸민 바깥 일",
    ]
    assert "꾸민 비밀" not in text and "꾸민 메모" not in text and "꾸민 남은 초안" not in text


async def test_curve_drafts_deleted_after_3_days_by_draft_since(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        cv = env.parts.curve
        old = _draft(env, "꾸민 오래된 초안")
        ch = cv.add_chapter(title="꾸민 챕터 초안", start_month="2019-01", status="draft", origin="review").id
        linked = _draft(env, "꾸민 챕터 사건")
        env.conn.execute("UPDATE curve_milestones SET chapter_id = ? WHERE id = ?", (ch, linked))
        env.conn.commit()
        # 오래전에 만들었지만 확정을 되돌린 사건: 만료 시계는 created_at이 아니라 draft_since(되돌린 시각)부터
        env.clock.advance(days=2)
        reverted = _draft(env, "꾸민 되돌린 사건")
        env.conn.execute(
            "UPDATE curve_milestones SET created_at = '2026-01-01T00:00:00.000000+00:00' WHERE id = ?", (reverted,))
        env.conn.commit()
        confirmed = _draft(env, "꾸민 확정 사건")
        await env.action("confirm_milestones", {"ids": [confirmed]})

        env.clock.advance(days=1)  # 처음 초안은 딱 3일
        job = expire_curve_drafts(env.parts.dispatcher, env.clock, days=env.settings.limits.draft_ttl_days)
        job(date(2026, 10, 27))
        left = [r["id"] for r in env.conn.execute("SELECT id FROM curve_milestones ORDER BY id")]
        chapters = [r["id"] for r in env.conn.execute("SELECT id FROM curve_chapters")]
        rows = [(r["kind"], r["actor"], r["channel"], r["summary"], r["undo_json"]) for r in env.activity()
                if r["kind"].endswith("_expired")]

        env.clock.advance(days=2)
        job(date(2026, 10, 29))
        final = [r["id"] for r in env.conn.execute("SELECT id FROM curve_milestones ORDER BY id")]

    assert left == [reverted, confirmed]  # 확정한 것은 남고, 챕터 사건도 함께 사라졌다(초안이었다)
    assert chapters == []
    assert rows == [
        ("milestone_drafts_expired", "secretary", "scheduler", "✓ 초안 정리: 2개", None),
        ("chapter_drafts_expired", "secretary", "scheduler", "✓ 초안 정리: 1개", None),
    ]
    assert old not in left and linked not in left
    assert final == [confirmed]


async def test_drafts_not_in_get_curve_until_confirmed(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        cv = env.parts.curve
        m = _draft(env, "꾸민 고점")
        ch = cv.add_chapter(title="꾸민 시절", start_month="2019-01", status="draft", origin="review").id

        def view():
            return curve_view(cv, ConditionsRepo(env.conn, env.clock), zoom="year", from_=date(2019, 1, 1),
                              to=date(2026, 12, 31), include_sensitive=True, today=date(2026, 10, 24))

        before = view()
        env.parts.tools.confirm_milestones(_ctx(), ids=[m])
        env.parts.tools.confirm_chapters(_ctx(), ids=[ch])
        after = view()

    assert before["milestones"] == [] and before["chapters"] == []
    assert [x["id"] for x in after["milestones"]] == [m]
    assert [x["id"] for x in after["chapters"]] == [ch]


async def test_runner_registers_curve_expiry_daily(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        names = [getattr(j, "__name__", "") for j in env.parts.runner._daily]

    assert "expire_curve_drafts" in names


async def test_expire_curve_drafts_is_internal(tmp_path):
    async with BeEnv.start(tmp_path, start=SAT_1300) as env:
        older = (env.clock.now() + timedelta(days=1)).isoformat()
        status, body = await env.action("expire_curve_drafts", {"older_than": older})

    assert status == 400 and body["error"]["code"] == "invalid_request"  # 앱에서는 부를 수 없다

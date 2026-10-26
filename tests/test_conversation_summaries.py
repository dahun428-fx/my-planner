"""SP9 7장: 대화 요약, 잇기, 말아 넣기, 지우기 (ADR 0014).

마이그레이션 018, 저장소, 요약 큐(가짜 두뇌), 라우터 0번 규칙, 말아 넣기, 지우기, `find_conversations`.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock, to_iso
from my_planner.domain import RunContext
from my_planner.loop.runner import retry_summaries_daily
from my_planner.store.db import migrate, open_db
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.transcripts import ERASED_LINE
from my_planner.tools.mcp_adapter import tool_names_for

START = kst(2026, 10, 26, 10, 0)  # 월


def _at_017(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    assert migrate(conn, upto=17) == 17
    return conn


# --- 018 ---


def test_018_backfills_conversation_sessions(tmp_path):
    conn = _at_017(tmp_path)
    at = "2026-10-25T01:00:00+00:00"
    for sid in ("sess-a", None):
        conn.execute(
            "INSERT INTO conversations (kind, session_id, logical_date, opened_at, last_message_at, channel) "
            "VALUES ('chat', ?, '2026-10-25', ?, ?, 'app')",
            (sid, at, at),
        )
    conn.commit()
    assert migrate(conn) == 19
    rows = [dict(r) for r in conn.execute("SELECT * FROM conversation_sessions")]
    assert rows == [{"conversation_id": 1, "session_id": "sess-a", "started_at": at}]
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)")}
    assert {"title", "summary", "summary_through", "user_messages", "deleted_at"} <= cols
    assert conn.execute("SELECT user_messages FROM conversations WHERE id = 2").fetchone()[0] == 0


def test_fts_on_title_summary(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    clock = FakeClock(START)
    repo = ConversationsRepo(conn, clock)
    a = repo.open("chat", START.date(), channel="app")
    b = repo.open("chat", START.date(), channel="app")
    for c in (a, b):
        repo.close(c.id)
    repo.set_summary(a.id, "치과 예약 정리", "토요일 오전 치과를 잡기로 했다.", clock.now())
    repo.set_summary(b.id, "책 고르기", "사피엔스를 읽기로 했다.", clock.now())

    def hits(q):
        return [c.id for c in repo.recent(channel="app", limit=10, q=q)]

    assert hits("사피엔스") == [b.id]
    assert hits("치과") == [a.id]  # 3글자 미만은 LIKE
    assert hits("토요일 오전") == [a.id]
    repo.set_summary(b.id, "책 고르기", "코스모스로 바꿨다.", clock.now())
    assert hits("사피엔스") == []  # 옛 값은 색인에서 빠진다
    assert hits("코스모스") == [b.id]
    repo.delete(b.id, clock.now())
    assert hits("코스모스") == [] and hits("고르기") == []
    assert [c.id for c in repo.recent(channel="app", limit=10)] == [a.id]
    gone = repo.get(b.id)
    assert gone.deleted_at is not None and gone.title is None and gone.summary is None
    assert conn.execute("SELECT count(*) FROM conversations_fts_docsize").fetchone()[0] == 1  # 색인한 행


def test_repo_sessions_bump_reset_reopen(tmp_path):
    conn = open_db(tmp_path / "state" / "planner.db")
    migrate(conn)
    clock = FakeClock(START)
    repo = ConversationsRepo(conn, clock)
    c = repo.open("chat", START.date(), channel="app")
    repo.set_session(c.id, "s1")
    repo.set_session(c.id, "s1")
    repo.add_session(c.id, "s2", clock.now())
    assert repo.sessions(c.id) == ["s1", "s2"]
    assert [repo.bump_user_messages(c.id) for _ in range(3)] == [1, 2, 3]
    repo.reset_session(c.id)
    got = repo.get(c.id)
    assert got.session_id is None and got.user_messages == 1
    repo.close(c.id)
    clock.advance(timedelta(hours=3))
    repo.reopen(c.id, clock.now())
    got = repo.get(c.id)
    assert got.closed_at is None and to_iso(got.last_message_at) == to_iso(clock.now())


# --- 요약 큐 (7.2) ---


AFTERNOON = kst(2026, 10, 26, 14, 0)  # 월 14:00: tick 사이에 생기는 회차가 없다


def summary_turn(title="치과 예약 정리", summary="토요일 오전 10시 치과를 잡았어요. 다음에 할 일은 없어요.", **kw):
    return FakeTurn([], json.dumps({"title": title, "summary": summary}, ensure_ascii=False), **kw)


def conv_row(env, cid):
    return env.parts.convs.get(cid)


async def chat_twice(env, first="치과 예약 잡아 줘 토요일 오전", second="10시로 해 줘"):
    resp, _ = await env.chat(first)
    cid = int(resp.headers["x-conversation-id"])
    env.clock.advance(timedelta(minutes=2))
    resp, _ = await env.chat(second)
    assert int(resp.headers["x-conversation-id"]) == cid
    return cid


async def close_by_idle(env):
    env.clock.advance(timedelta(minutes=31))
    await env.tick()


async def test_close_queues_summary(tmp_path):
    script = [FakeTurn([], "언제가 좋아요?"), FakeTurn([], "잡았어요."), summary_turn()]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        cid = await chat_twice(env)
        assert len(env.brain.calls) == 2
        await close_by_idle(env)
        c = conv_row(env, cid)
        call = env.brain.calls[2]
    assert c.closed_at is not None
    assert (c.title, c.summary) == ("치과 예약 정리", "토요일 오전 10시 치과를 잡았어요. 다음에 할 일은 없어요.")
    assert c.summary_through == c.last_message_at
    ctx = call["run_ctx"]
    assert ctx.kind == "summary" and tool_names_for(ctx) == []  # 도구 없음
    assert call["max_turns"] == 1 and call["persist_session"] is False and call["session_id"] is None
    assert call["system_prompt"].startswith("당신은 Dahun") and "JSON" in call["system_prompt"]
    assert "치과 예약 잡아 줘 토요일 오전" in call["prompt"] and "잡았어요." in call["prompt"]


async def test_daily_retry_summarizes_pending(tmp_path):
    script = [
        FakeTurn([], "언제가 좋아요?"), FakeTurn([], "잡았어요."),
        FakeTurn([], "", status="error", error="is_error"),  # 닫힐 때: 두뇌 오류
        summary_turn(),  # 하루 한 번 작업이 다시 해 본다
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        cid = await chat_twice(env)
        await close_by_idle(env)
        failed = conv_row(env, cid)
        env.clock.advance(timedelta(minutes=1))
        await env.tick()  # 이미 해 본 대화는 tick마다 다시 넣지 않는다
        calls_after_tick = len(env.brain.calls)
        names = [getattr(j, "__name__", "") for j in env.parts.runner._daily]
        retry_summaries_daily(env.parts.dispatcher)(env.parts.dispatcher._today())
        await env.drain()
        done = conv_row(env, cid)
    assert (failed.title, failed.summary) == ("치과 예약 잡아 줘 토요일 오전"[:20], None)  # 대체 제목, 요약은 비움
    assert calls_after_tick == 3 and len(env.brain.calls) == 4
    assert "retry_summaries" in names
    assert done.title == "치과 예약 정리" and done.summary.startswith("토요일")


async def test_reopened_then_closed_is_summarized_again_same_process(tmp_path):
    """SP9-09 리뷰: 이 프로세스에서 한 번 요약한 대화도 다시 열어 말이 더 생기면 닫힐 때 tick이 다시 요약한다."""
    script = [
        FakeTurn([], "언제가 좋아요?"), FakeTurn([], "잡았어요."), summary_turn(),
        FakeTurn([], "일요일로 바꿨어요."), summary_turn("치과 일요일로", "치과를 일요일로 옮겼어요. 다음에 할 일은 없어요."),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        cid = await chat_twice(env)
        await close_by_idle(env)
        first = conv_row(env, cid)
        resp, _ = await env.chat("일요일로 바꿔 줘", resume_conversation_id=cid)
        assert int(resp.headers["x-conversation-id"]) == cid
        await close_by_idle(env)
        again = conv_row(env, cid)
        call = env.brain.calls[4]
    assert first.title == "치과 예약 정리"
    assert (again.title, again.summary_through) == ("치과 일요일로", again.last_message_at)
    assert call["run_ctx"].kind == "summary" and "토요일 오전 10시 치과를 잡았어요" in call["prompt"]  # 이전 요약


async def test_summary_saved_title_20_summary_600(tmp_path):
    long = "```json\n" + json.dumps({"title": "가" * 30, "summary": "나" * 700}) + "\n```"
    script = [FakeTurn([], "네"), FakeTurn([], "네"), FakeTurn([], long)]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        cid = await chat_twice(env)
        await close_by_idle(env)
        c = conv_row(env, cid)
    assert c.title == "가" * 20 and c.summary == "나" * 600


async def test_cap_15_and_error_fallback_title(tmp_path):
    script = [FakeTurn([], "네"), FakeTurn([], "네")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        p = env.parts
        cid = await chat_twice(env, first="  이번 주말에\n등산 갈까 고민 중이에요 날씨 보고")
        for _ in range(15):
            p.state.incr_usage(p.dispatcher._today(), "summaries")
        await close_by_idle(env)
        c = conv_row(env, cid)
    assert len(env.brain.calls) == 2  # 상한: 두뇌를 부르지 않는다
    assert c.title == "이번 주말에 등산 갈까 고민 중이에요" and c.summary is None  # 앞 20자, 줄바꿈은 공백


async def test_summary_brain_error_counts_and_falls_back(tmp_path):
    script = [FakeTurn([], "네"), FakeTurn([], "네"), FakeTurn([], "제목 없이 그냥 글")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        p = env.parts
        cid = await chat_twice(env, first="책 고르는 중")
        await close_by_idle(env)
        c = conv_row(env, cid)
        usage = p.state.usage(p.dispatcher._today())
    assert (c.title, c.summary) == ("책 고르는 중", None)  # JSON이 아니면 실패로 본다
    assert usage.summaries == 1 and usage.brain_calls == 3


async def test_short_conversation_no_brain_call(tmp_path):
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=[FakeTurn([], "좋아요, 다녀오세요.")]) as env:
        resp, _ = await env.chat("오늘 저녁 산책 다녀올게요")
        cid = int(resp.headers["x-conversation-id"])
        await close_by_idle(env)
        c = conv_row(env, cid)
    assert len(env.brain.calls) == 1
    assert (c.title, c.summary) == ("오늘 저녁 산책 다녀올게요", "")


async def test_telegram_not_summarized(tmp_path):
    script = [FakeTurn([], "네"), FakeTurn([], "네")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        await env.telegram("치과 예약 잡아 줘")
        env.clock.advance(timedelta(minutes=2))
        await env.telegram("10시로")
        cid = env.brain.calls[0]["run_ctx"].conversation_id
        await close_by_idle(env)
        c = conv_row(env, cid)
    assert c.closed_at is not None and c.title is None and c.summary is None
    assert len(env.brain.calls) == 2


# --- 완료 조건 9: 새 대화의 첫 두뇌 입력에 다른 대화의 원문이 없다 ---

UNIQUE = "청록색-하마-4417"


async def test_new_conversation_input_has_no_other_transcript(tmp_path):
    script = [
        FakeTurn([], f"알겠어요, {UNIQUE} 기억할게요."), FakeTurn([], "네, 그것도요."),
        summary_turn("암호 같은 말", "사용자가 기억해 달라는 말을 남겼어요."),
        FakeTurn([], "새 대화 답"), FakeTurn([], "또 새 대화"), FakeTurn([], "텔레그램 답"),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await chat_twice(env, first=f"이거 기억해 {UNIQUE}", second=f"{UNIQUE} 다시 한 번")
        await close_by_idle(env)  # 30분 규칙으로 닫히고 요약된다
        resp, _ = await env.chat("완전히 새 얘기")
        b = int(resp.headers["x-conversation-id"])
        await env.post("/conversations/new")  # "새 대화"로도
        resp, _ = await env.chat("또 새 얘기")
        c = int(resp.headers["x-conversation-id"])
        await env.telegram("텔레그램에서 처음")
    assert len({a, b, c}) == 3
    for i in (3, 4, 5):  # 새 대화 B, C(앱)와 텔레그램 새 대화의 첫 입력
        first = env.brain.prompts[i]
        assert env.brain.session_ids[i] is None and "## 지금 상황" in first
        assert UNIQUE not in first and "암호 같은 말" not in first and "기억해 달라는" not in first


# --- 7.7 지우기 ---


SID_A1, SID_A2, SID_B = (str(uuid.UUID(int=i)) for i in (1, 2, 3))


def day_text(env, ymd):
    y, m, _ = ymd.split("-")
    return (env.settings.paths.data_dir / "transcripts" / y / m / f"{ymd}.md").read_text(encoding="utf-8")


async def test_delete_erases_lines_across_days(tmp_path):
    script = [
        FakeTurn([], "A 첫날 답", session_id=SID_A1), FakeTurn([], "텔레그램 답", session_id=SID_B),
        FakeTurn([], "A 둘째 날 답", session_id=SID_A1),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        resp, _ = await env.chat("A의 첫날 비밀 이야기")
        a = int(resp.headers["x-conversation-id"])
        await env.telegram("텔레그램 말은 남는다")
        tg = env.brain.calls[1]["run_ctx"].conversation_id
        env.clock.set(kst(2026, 10, 27, 14, 0))  # 다음 날 다시 연다
        await env.chat("A의 둘째 날 이야기", resume_conversation_id=a)
        resp = await env.delete(f"/conversations/{a}")
        again = await env.delete(f"/conversations/{a}")
        d1, d2 = day_text(env, "2026-10-26"), day_text(env, "2026-10-27")
        kept = env.parts.transcripts.messages(tg)
        gone = env.parts.transcripts.messages(a)
    assert resp.status == 204 and again.status == 404
    for text in (d1, d2):
        assert "A의" not in text and "A 첫날" not in text and "A 둘째" not in text and f"[{a}]" not in text
        assert text.count(ERASED_LINE) == 1  # 이어진 줄은 한 줄로
    assert "텔레그램 말은 남는다" in d1 and "텔레그램 답" in d1
    assert [m.text for m in kept] == ["텔레그램 말은 남는다", "텔레그램 답"]  # 지운 자리가 다른 대화 본문에 붙지 않는다
    assert gone == []
    assert not list((env.settings.paths.data_dir / "transcripts").rglob("*.tmp"))


async def test_delete_erase_retries_per_file_and_daily_reerase(tmp_path, monkeypatch):
    """SP9-09 리뷰: 원문 지우기는 날짜 파일마다 따로 짧게 다시 해 본다. 한 파일이 끝내 안 돼도 다른 날은 지운다.
    못 지운 날은 하루 한 번 작업(최근 30일 안에 지운 대화)이 다시 지운다. 여러 번 해도 같다."""
    import os

    from my_planner.store import transcripts as tr_mod

    monkeypatch.setattr(tr_mod, "ERASE_RETRY_DELAYS", (0, 0, 0))
    script = [FakeTurn([], "A 첫날 답"), FakeTurn([], "A 둘째 날 답")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        resp, _ = await env.chat("A의 첫날 비밀 이야기")
        a = int(resp.headers["x-conversation-id"])
        env.clock.set(kst(2026, 10, 27, 14, 0))
        await env.chat("A의 둘째 날 이야기", resume_conversation_id=a)
        real, calls = os.replace, {"d1": 0, "d2": 0}

        def flaky(src, dst):
            key = "d1" if "2026-10-26" in str(dst) else "d2"
            calls[key] += 1
            if key == "d1" or calls["d2"] == 1:  # 첫날 파일은 계속 잡혀 있고, 둘째 날 파일은 한 번만
                raise PermissionError(32, "in use")
            return real(src, dst)

        monkeypatch.setattr(tr_mod.os, "replace", flaky)
        resp = await env.delete(f"/conversations/{a}")
        monkeypatch.setattr(tr_mod.os, "replace", real)
        d1_after, d2_after = day_text(env, "2026-10-26"), day_text(env, "2026-10-27")
        names = [getattr(j, "__name__", "") for j in env.parts.runner._daily]
        env.clock.set(kst(2026, 10, 28, 4, 30))
        job = next(j for j in env.parts.runner._daily if j.__name__ == "reerase_deleted_conversations")
        job(env.parts.dispatcher._today())
        d1_next = day_text(env, "2026-10-26")
        again = env.parts.dispatcher.reerase_deleted()
        env.clock.advance(timedelta(days=31))
        later = env.parts.convs.deleted_since(env.clock.now() - timedelta(days=30))
    assert resp.status == 204 and calls == {"d1": 4, "d2": 2}  # 첫날은 처음 + 다시 3번, 둘째 날은 한 번 다시
    assert "A의 첫날" in d1_after  # 못 바꾼 날은 그대로 남아 있다
    assert "A의 둘째 날" not in d2_after and ERASED_LINE in d2_after  # 다른 날은 건너뛰지 않는다
    assert "reerase_deleted_conversations" in names
    assert "A의 첫날" not in d1_next and ERASED_LINE in d1_next
    assert again == 0 and later == []
    assert not list((env.settings.paths.data_dir / "transcripts").rglob("*.tmp"))


async def test_delete_removes_all_session_files(tmp_path):
    script = [
        FakeTurn([], "A 답", session_id=SID_A1),
        FakeTurn([], "", status="error", session_id=None, resume_failed=True),  # 다시 열 때 resume 실패
        FakeTurn([], "A 새 세션", session_id=SID_A2),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        config = tmp_path / "claude"
        env.parts.dispatcher.claude_config_dir = config
        resp, _ = await env.chat("A 이야기")
        a = int(resp.headers["x-conversation-id"])
        await close_by_idle(env)
        await env.chat("다시 A", resume_conversation_id=a)
        sessions = env.parts.convs.sessions(a)
        project = config / "projects" / "-some-project"
        project.mkdir(parents=True)
        for sid in (SID_A1, SID_A2, SID_B):
            (project / f"{sid}.jsonl").write_text("{}", encoding="utf-8")
        (project / SID_A1).mkdir()  # 같은 id의 하위 폴더도
        resp = await env.delete(f"/conversations/{a}")
        left = sorted(p.name for p in project.iterdir())
    assert resp.status == 204
    assert sessions == [SID_A1, SID_A2]
    assert left == [f"{SID_B}.jsonl"]  # 다른 대화의 세션은 그대로


async def test_deleted_hidden_from_list_messages_and_tool(tmp_path):
    script = [FakeTurn([], "네"), FakeTurn([], "네"), summary_turn("치과 예약 정리", "토요일로 잡았어요.")]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await chat_twice(env)
        await close_by_idle(env)
        tools, ctx = env.parts.tools, RunContext(None, None, channel="app")
        before = tools.find_conversations(ctx, query="치과")["items"]
        listed = (await (await env.get("/conversations?channel=app")).json())["items"]
        resp = await env.delete(f"/conversations/{a}")
        after_list = (await (await env.get("/conversations?channel=app")).json())["items"]
        searched = (await (await env.get("/conversations?q=치과")).json())["items"]
        messages = await env.get(f"/conversations/{a}/messages")
        after_tool = tools.find_conversations(ctx, query="치과")["items"]
        recent_tool = tools.find_conversations(ctx)["items"]
        row = env.activity()[-1]
    assert [i["id"] for i in before] == [a] and [i["id"] for i in listed] == [a]
    assert resp.status == 204
    assert after_list == [] and searched == [] and messages.status == 404
    assert after_tool == [] and recent_tool == []
    assert (row["kind"], row["summary"], row["undo_json"], row["actor"], row["channel"]) == (
        "conversation_deleted", "대화를 지웠어요", None, "user", "app",
    )


# --- 7.5 `find_conversations` ---


async def test_find_conversations_no_transcript(tmp_path):
    script = [
        FakeTurn([], "네"), FakeTurn([], "네"),
        summary_turn("치과 예약 정리", "토요일로 잡았어요. 계좌 110-123-456789로 보냈어요."),
        FakeTurn([], "책 답"), FakeTurn([], "책 답2"), summary_turn("책 고르기", "사피엔스를 읽기로 했어요."),
    ]
    async with BeEnv.start(tmp_path, start=AFTERNOON, script=script) as env:
        a = await chat_twice(env, first=f"치과 원문 {UNIQUE}", second="그날로")
        await close_by_idle(env)
        b = await chat_twice(env, first="책 원문 이야기", second="두 권만")
        await close_by_idle(env)
        tools, ctx = env.parts.tools, RunContext(None, None, channel="app")
        recent = tools.find_conversations(ctx)
        dentist = tools.find_conversations(ctx, query="치과 예약")
        short = tools.find_conversations(ctx, query="책")
        old = tools.find_conversations(ctx, days=1)
        env.clock.advance(timedelta(days=3))
        none = tools.find_conversations(ctx, days=2)
        bad = [tools.find_conversations(ctx, **kw) for kw in ({"days": 0}, {"limit": 21}, {"query": 3})]
    assert [i["id"] for i in recent["items"]] == [b, a]
    assert all(set(i) == {"id", "date", "title", "summary"} for i in recent["items"])
    assert UNIQUE not in str(recent) and "원문" not in str(recent)  # 원문은 주지 않는다
    (d,) = dentist["items"]
    assert (d["id"], d["date"], d["title"]) == (a, "2026-10-26", "치과 예약 정리")
    assert "110-123-456789" not in d["summary"] and "[가림]" in d["summary"]  # redact()
    assert [i["id"] for i in short["items"]] == [b] and len(old["items"]) == 2 and none["items"] == []
    assert all("error" in r for r in bad)

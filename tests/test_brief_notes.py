"""마스터의 아침 브리핑 관찰 한 줄 (SP14 스펙 1장 4, 8장, T7, Review Focus 2·3).

순수 함수(`harness/brief_notes.py`)와 디스패처(`BeEnv` + `FakeBrain`·`FakeSender`). 관찰 글은 모두 꾸며 낸 것이다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from be_env import BeEnv
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.harness.brief_notes import (
    BRIEF_NOTE_DAYS,
    BRIEF_P1_MAX,
    BriefNotes,
    brief_block,
    note_line,
    settle_brief,
)
from my_planner.harness.dispatcher import SEND_ATTEMPTS
from my_planner.store.db import transaction
from my_planner.store.repos.agents import AgentNote, AgentsRepo

TODAY = date(2026, 11, 2)
T0 = kst(2026, 11, 2, 4, 1)
A = "토요일 저녁만 비어 있어 운동은 그날이 좋아요"
B = "이번 주는 걷기 기록이 꾸준해요"
C = "다리 운동 다음 날은 가볍게 걸어요"


def mk(id_: int, text: str, priority: int = 2, agent: str = "mate", sec: int = 0) -> AgentNote:
    return AgentNote(
        id=id_, agent=agent, day=TODAY - timedelta(days=1), text=text, priority=priority, refs=("workout:1",),
        shown_at=None, created_at=T0 + timedelta(seconds=sec),
    )


# --- 순수 함수 ---


def test_at_most_one_p2():
    a, b = mk(1, A), mk(2, B, sec=1)
    got = settle_brief(f"좋은 아침이에요.\n\n운동메이트: {A}\n운동메이트: {B}", [a, b])
    assert got == BriefNotes(f"좋은 아침이에요.\n\n운동메이트: {A}", (1,))
    assert B not in got.text


def test_p1_appended_even_if_brain_omits():
    p1 = mk(7, A, priority=1)
    got = settle_brief("좋은 아침이에요.", [p1])
    assert got == BriefNotes(f"좋은 아침이에요.\n\n운동메이트: {A}", (7,))


def test_p1_not_duplicated_when_brain_wrote_it():
    p1 = mk(7, A, priority=1)
    got = settle_brief(f"좋은 아침이에요.\n\n운동메이트: {A}", [p1])
    assert got.text == f"좋은 아침이에요.\n\n운동메이트: {A}"
    assert got.text.count(A) == 1 and got.shown_ids == (7,)


def test_p1_capped_at_two(conn):
    clock = FakeClock(T0)
    repo = AgentsRepo(conn, clock)
    with transaction(conn):
        x = repo.add_note("mate", TODAY - timedelta(days=1), A, 1, ["workout:1"], T0)
        y = repo.add_note("manager", TODAY - timedelta(days=1), B, 1, ["task:1"], T0 + timedelta(seconds=1))
        z = repo.add_note("mate", TODAY - timedelta(days=1), C, 1, ["workout:2"], T0 + timedelta(seconds=2))
    cands = repo.brief_candidates(TODAY)
    assert [n.id for n in cands] == [x, y, z]
    got = settle_brief("좋은 아침이에요.", cands)
    assert BRIEF_P1_MAX == 2
    assert got.text == f"좋은 아침이에요.\n\n운동메이트: {A}\n라이프 매니저: {B}"
    assert got.shown_ids == (x, y) and C not in got.text
    assert C not in brief_block(cands)
    with transaction(conn):
        repo.mark_shown(got.shown_ids, T0)
    assert [n.id for n in repo.brief_candidates(TODAY)] == [z]


def test_matched_line_rewritten_to_label_form():
    p2 = mk(3, A)
    got = settle_brief(f"좋은 아침이에요.\n- 참고로 {A}", [p2])
    assert got.text.splitlines()[-1] == f"운동메이트: {A}"
    assert "참고로" not in got.text and got.shown_ids == (3,)


def test_two_p1_both_and_no_p2():
    x, y, p2 = mk(1, A, priority=1), mk(2, B, priority=1, agent="manager", sec=1), mk(3, C, sec=2)
    got = settle_brief(f"좋은 아침이에요.\n운동메이트: {C}", [x, y, p2])
    assert got.text == f"좋은 아침이에요.\n\n운동메이트: {A}\n라이프 매니저: {B}"
    assert got.shown_ids == (1, 2)


def test_brief_match_ignores_spacing_and_label():
    """Review Focus 3: 띄어쓰기·앞 이름을 바꿔 써도 찾는다. 본문을 바꿔 쓰면 못 찾고 보인 것이 아니다."""
    p2 = mk(4, A)
    spaced = A.replace(" ", "  ")
    got = settle_brief(f"좋은 아침이에요.\n메이트:  {spaced}", [p2])
    assert got.text == f"좋은 아침이에요.\n운동메이트: {A}" and got.shown_ids == (4,)
    rewritten = settle_brief("좋은 아침이에요.\n메이트: 토요일 저녁이 비어 운동하기 좋아요", [p2])
    assert rewritten.shown_ids == ()
    assert "운동메이트:" not in rewritten.text


def test_block_copy():
    p1, p2 = mk(1, A, priority=1), mk(2, B)
    assert brief_block([]) == ""
    assert brief_block([p1, p2]) == (
        "## 아래층 관찰\n"
        "하네스가 아래 줄을 메시지 끝에 그대로 붙입니다. 같은 내용을 다시 쓰지 않습니다.\n"
        f"- 운동메이트: {A}"
    )
    assert brief_block([p2, mk(3, C, agent="manager")]) == (
        "## 아래층 관찰\n"
        "아래 가운데 오늘 도움이 될 줄이 있으면 하나만 골라 그대로 메시지 끝에 한 줄로 붙입니다. 없으면 붙이지 않습니다.\n"
        f"- 운동메이트: {B}\n"
        f"- 라이프 매니저: {C}"
    )
    assert note_line(mk(5, C, agent="manager")) == f"라이프 매니저: {C}"


def test_candidate_window_matches_brief_note_days(conn):
    repo = AgentsRepo(conn, FakeClock(T0))
    with transaction(conn):
        inside = repo.add_note("mate", TODAY - timedelta(days=BRIEF_NOTE_DAYS), A, 2, ["workout:1"], T0)
        repo.add_note("mate", TODAY - timedelta(days=BRIEF_NOTE_DAYS + 1), B, 2, ["workout:2"], T0)
    assert [n.id for n in repo.brief_candidates(TODAY)] == [inside]


# --- 디스패처 ---

MON_0900 = kst(2026, 11, 2, 9, 0) + timedelta(seconds=30)
MORNING = "좋은 아침이에요."


def add_note(env, text: str, priority: int, *, day: date = TODAY - timedelta(days=1), at: datetime = T0) -> int:
    with transaction(env.conn):
        return env.parts.agents.add_note("mate", day, text, priority, ["workout:1"], at)


def shown_at(env, nid: int):
    return env.conn.execute("SELECT shown_at FROM agent_notes WHERE id = ?", (nid,)).fetchone()["shown_at"]


def calls(env, kind: str):
    return [c for c in env.brain.calls if c["run_ctx"].kind == kind]


def morning_outbound(env) -> str:
    rows = env.conn.execute("SELECT outbound_text FROM runs WHERE loop = 'morning_brief' ORDER BY id").fetchall()
    return rows[-1]["outbound_text"]


async def test_morning_brief_gets_block_others_not(tmp_path):
    script = [FakeTurn([], MORNING), FakeTurn([], "오늘 하루 어땠어요?")]
    async with BeEnv.start(tmp_path, script=script, start=MON_0900) as env:
        add_note(env, A, 2)
        await env.tick()
        env.clock.set(kst(2026, 11, 2, 17, 30) + timedelta(seconds=30))
        await env.tick()
        runs = calls(env, "run")

    assert len(runs) == 2
    assert "\n## 아래층 관찰\n" in runs[0]["prompt"] and f"- 운동메이트: {A}" in runs[0]["prompt"]
    assert "\n## 아래층 관찰\n" not in runs[1]["prompt"]
    # 앞머리 뒤, 조건 블록들 앞
    assert runs[0]["prompt"].index("## 지금") < runs[0]["prompt"].index("\n## 아래층 관찰\n")


async def test_p1_appended_by_harness_with_fake_brain(tmp_path):
    async with BeEnv.start(tmp_path, script=[FakeTurn([], MORNING)], start=MON_0900) as env:
        add_note(env, A, 1)
        await env.tick()
        sent = env.sender.sent[-1].text
        saved = morning_outbound(env)
        proactive = env.parts.state.usage(TODAY).proactive_messages

    assert sent.endswith(f"\n\n운동메이트: {A}") and sent.count(A) == 1
    assert saved.endswith(f"운동메이트: {A}")
    assert proactive == 1  # 관찰은 브리핑 안이라 따로 세지 않는다


async def test_shown_marked_only_after_delivery(tmp_path):
    async with BeEnv.start(tmp_path, script=[FakeTurn([], MORNING)], start=MON_0900) as env:
        nid = add_note(env, A, 1)
        env.sender.fail = True
        await env.tick()
        status = env.conn.execute("SELECT status FROM runs WHERE loop = 'morning_brief'").fetchone()["status"]
        never = shown_at(env, nid)

    assert status == "failed" and never is None

    async with BeEnv.start(tmp_path / "ok", script=[FakeTurn([], MORNING)], start=MON_0900) as env:
        nid = add_note(env, A, 1)
        await env.tick()
        now = shown_at(env, nid)
    assert now is not None


async def test_shown_marked_after_resend(tmp_path):
    """바로 보내기(3회)가 모두 안 되면 표시하지 않고, 5분 뒤 재전송이 되면 그때 `_run_delivered`가 표시한다."""
    async with BeEnv.start(tmp_path, script=[FakeTurn([], MORNING)], start=MON_0900) as env:
        nid = add_note(env, A, 1)
        inner, seen = env.sender.send, []

        async def flaky(out):
            seen.append(shown_at(env, nid))
            if len(seen) <= SEND_ATTEMPTS:
                raise ConnectionError("fake send failure")
            return await inner(out)

        env.sender.send = flaky
        await env.tick()
        for _ in range(20):
            if shown_at(env, nid) is not None:
                break
            await env.drain()
        after = shown_at(env, nid)
        status = env.conn.execute("SELECT status FROM runs WHERE loop = 'morning_brief'").fetchone()["status"]

    assert len(seen) == SEND_ATTEMPTS + 1 and all(x is None for x in seen)
    assert env.sender.sent[-1].text.endswith(f"운동메이트: {A}")
    assert status == "done" and after is not None


async def test_shown_marked_after_resend_without_conversation(tmp_path):
    """재전송이 됐는데 회차 대화를 못 찾아도(`conv is None`) 사용자는 받았다: 실은 관찰은 보인 것으로."""
    async with BeEnv.start(tmp_path, script=[FakeTurn([], MORNING)], start=MON_0900) as env:
        nid = add_note(env, A, 1)
        d = env.parts.dispatcher
        inner, tries = env.sender.send, []

        async def flaky(out):
            tries.append(1)
            if len(tries) <= SEND_ATTEMPTS:
                if len(tries) == SEND_ATTEMPTS:  # 재전송 때 대화가 없어진 것처럼
                    d.convs.get = lambda _cid: None
                raise ConnectionError("fake send failure")
            return await inner(out)

        env.sender.send = flaky
        await env.tick()
        for _ in range(20):
            if shown_at(env, nid) is not None:
                break
            await env.drain()
        after = shown_at(env, nid)
        left = dict(d._brief_shown)
        del d.convs.get

    assert len(tries) == SEND_ATTEMPTS + 1
    assert env.sender.sent[-1].text.endswith(f"운동메이트: {A}")
    assert after is not None and left == {}


async def test_brief_shown_dropped_when_resend_skipped(tmp_path):
    """재전송이 답장 창 밖이라 건너뛰면 표시하지 않고 메모리에서도 지운다(다음 브리핑 후보로 남는다)."""
    async with BeEnv.start(tmp_path, script=[FakeTurn([], MORNING)], start=MON_0900) as env:
        nid = add_note(env, A, 1)
        d = env.parts.dispatcher

        async def fail(out):
            env.clock.set(kst(2026, 11, 2, 12, 30))  # 답장 창(12:00) 밖
            raise ConnectionError("fake send failure")

        env.sender.send = fail
        await env.tick()
        for _ in range(20):
            if not d._brief_shown and not d._timers:
                break
            await env.drain()
        left = dict(d._brief_shown)
        never = shown_at(env, nid)
        cands = [n.id for n in env.parts.agents.brief_candidates(TODAY + timedelta(days=1))]

    assert left == {} and never is None and cands == [nid]


async def test_unchosen_note_kept(tmp_path):
    async with BeEnv.start(tmp_path, script=[FakeTurn([], f"{MORNING}\n\n운동메이트: {A}")], start=MON_0900) as env:
        a = add_note(env, A, 2)
        b = add_note(env, B, 2, at=T0 + timedelta(seconds=1))
        await env.tick()
        repo = env.parts.agents
        shown = (shown_at(env, a), shown_at(env, b))
        later = [n.id for n in repo.brief_candidates(TODAY + timedelta(days=3))]
        kept = [n.id for n in repo.notes(None, TODAY - timedelta(days=7))]

    assert shown[0] is not None and shown[1] is None
    assert b not in later and b in kept


async def test_note_judged_after_brief_shows_next_morning(tmp_path):
    """Review Focus 2: 하루 경계 뒤 첫 tick에 아침 브리핑(차례 1)과 하루 끝 판단(차례 3)이 함께 든다. 그날 브리핑에는
    관찰이 없고, 판단이 쓴 관찰은 다음 날 브리핑 끝에 붙는다."""
    note = ("write_note", {"text": A, "priority": 1, "refs": ["task:1"]})
    script = [FakeTurn([], MORNING), FakeTurn([note], ""), FakeTurn([], MORNING)]
    async with BeEnv.start(tmp_path, script=script, start=MON_0900, dayend=True) as env:
        with transaction(env.conn):
            env.parts.agents.add_event("task_done", "task:1", None, "app", TODAY - timedelta(days=1),
                                       to=("mate",), now=kst(2026, 11, 1, 20, 0))
        await env.tick()
        first_kinds = [c["run_ctx"].kind for c in env.brain.calls]
        first = env.sender.sent[-1].text
        (n,) = env.parts.agents.notes("mate", date.min)
        left = [x.id for x in env.parts.agents.brief_candidates(TODAY + timedelta(days=1))]
        env.parts.runner.checkins = False
        env.clock.set(kst(2026, 11, 3, 4, 1))
        await env.tick()
        env.parts.runner.checkins = True
        env.clock.set(kst(2026, 11, 3, 9, 0) + timedelta(seconds=30))
        await env.tick()
        kinds = [c["run_ctx"].kind for c in env.brain.calls]
        second = env.sender.sent[-1].text
        shown = shown_at(env, n.id)

    assert first_kinds == ["run", "dayend"]
    assert "운동메이트:" not in first and "\n## 아래층 관찰\n" not in env.brain.calls[0]["prompt"]
    assert left == [n.id]
    assert kinds == ["run", "dayend", "run"]
    assert second == f"{MORNING}\n\n운동메이트: {A}"
    assert shown is not None

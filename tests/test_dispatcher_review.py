"""디스패처: 일요일 주간 회고를 저녁 체크인에 합쳐 실행, 회고 저장 (스펙 5.3, 5.4)."""

from datetime import timedelta

from fakes import FakeTurn
from test_dispatcher_messages import Env, kst

from my_planner.domain import Cadence, LoopKey, RunStatus
from my_planner.harness import prompts

SUN_1800 = kst(2026, 10, 25, 18, 0)
REVIEW_REPLY = "이번 주도 수고 많으셨어요. 다음 주 우선순위로 보고서 마무리를 제안드려요. 오늘 컨디션도 눌러 주세요."


def _env(tmp_path, conn, state, script, start):
    return Env(tmp_path, conn, state, script=script, start=start, with_tools=True, with_conditions=True)


def _queued_sunday(env):
    eve = env.runs.ensure(LoopKey.evening_checkin, SUN_1800)
    review = env.runs.ensure(LoopKey.review, SUN_1800, Cadence.week)
    for r in (eve, review):
        env.runs.mark_queued(r.id)
    return env.runs.get(eve.id), env.runs.get(review.id)


def _review_file(env, period):
    return env.settings.paths.data_dir / "reviews" / "week" / f"{period}.md"


async def test_weekly_review_saved_when_merged_into_evening(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 25, 18, 10))
    eve, review = _queued_sunday(env)
    await env.process_run(eve, [review])

    assert [o.text for o in env.sender.sent] == [REVIEW_REPLY]
    assert env.runs.get(eve.id).status is RunStatus.done
    assert env.runs.get(review.id).status is RunStatus.done
    prompt = env.brain.prompts[0]
    assert prompt.index(prompts.load("evening_checkin.md")) < prompt.index(prompts.load("review_week.md"))
    path = _review_file(env, "2026-W43")
    assert path.exists() and REVIEW_REPLY in path.read_text(encoding="utf-8")


class StatusAtSendSender:
    """보내는 순간 두 회차의 상태를 적는다."""

    def __init__(self):
        self.runs = None
        self.ids = []
        self.statuses_at_send = []
        self.sent = []

    async def send(self, out):
        self.statuses_at_send.append([self.runs.get(i).status for i in self.ids])
        self.sent.append(out)

    async def typing(self):
        pass


async def test_merged_runs_marked_done_after_send(tmp_path, conn, state):
    sender = StatusAtSendSender()
    env = Env(
        tmp_path, conn, state, script=[FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 25, 18, 10),
        sender=sender, with_tools=True, with_conditions=True,
    )
    eve, review = _queued_sunday(env)
    sender.runs, sender.ids = env.runs, [eve.id, review.id]
    await env.process_run(eve, [review])

    assert sender.statuses_at_send == [[RunStatus.running, RunStatus.queued]]  # 보내기 전에는 done이 아니다
    assert [env.runs.get(i).status for i in (eve.id, review.id)] == [RunStatus.done, RunStatus.done]
    assert env.runs.get(eve.id).merged_run_ids == [review.id]  # 합친 회차는 실행된 회차에 기록한다
    assert state.usage(kst(2026, 10, 25, 18, 10).date()).proactive_messages == 1


async def test_merged_run_past_its_limit_dropped_primary_still_runs(tmp_path, conn, state):
    # 월 10:00에 꺼낸 월 아침 + [일 회고(+3일 안), 일 저녁(한계 월 04:00 지남)]:
    # 저녁만 따로 late, 아침과 회고는 합쳐 실행한다
    from my_planner.domain import SkipReason

    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 26, 10, 0))
    eve, review = _queued_sunday(env)
    mon = env.runs.ensure(LoopKey.morning_brief, kst(2026, 10, 26, 9, 0))
    env.runs.mark_queued(mon.id)
    await env.process_run(env.runs.get(mon.id), [review, eve])

    assert [o.text for o in env.sender.sent] == [REVIEW_REPLY]
    late = env.runs.get(eve.id)
    assert late.status is RunStatus.skipped and late.skip_reason is SkipReason.late
    assert [env.runs.get(i).status for i in (mon.id, review.id)] == [RunStatus.done, RunStatus.done]
    assert env.runs.get(mon.id).merged_run_ids == [review.id]
    prompt = env.brain.prompts[0]
    assert prompts.load("review_week.md") in prompt and prompts.load("evening_checkin.md") not in prompt
    assert _review_file(env, "2026-W43").exists()


async def test_late_primary_promotes_merged_run(tmp_path, conn, state):
    # 월 04:30에 꺼낸 일 저녁(한계 월 04:00 지남) + [일 회고]: 저녁은 late, 회고가 primary로 실행된다
    from my_planner.domain import SkipReason

    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 26, 4, 30))
    eve, review = _queued_sunday(env)
    await env.process_run(eve, [review])

    assert [o.text for o in env.sender.sent] == [REVIEW_REPLY]
    late = env.runs.get(eve.id)
    assert late.status is RunStatus.skipped and late.skip_reason is SkipReason.late
    done = env.runs.get(review.id)
    assert done.status is RunStatus.done and done.merged_run_ids == []
    assert env.convs.get(done.conversation_id).run_id == review.id
    prompt = env.brain.prompts[0]
    assert prompts.load("review_week.md") in prompt and prompts.load("evening_checkin.md") not in prompt
    assert _review_file(env, "2026-W43").exists()


async def test_review_prompt_names_review_week_and_next_week(tmp_path, conn, state):
    # 두뇌가 set_priorities(week, 다음 주)를 바로 부를 수 있게 이번 회고 주와 다음 주를 알린다
    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 25, 18, 10))
    eve, review = _queued_sunday(env)
    await env.process_run(eve, [review])

    prompt = env.brain.prompts[0]
    note = prompt[prompt.index("## 회고 주\n"):]
    assert "2026-W43 (10/19~10/25)" in note and "2026-W44 (10/26~11/1)" in note


async def test_evening_alone_has_no_review_note(tmp_path, conn, state):
    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 25, 18, 10))
    eve, _ = _queued_sunday(env)
    await env.process_run(eve)

    assert "## 회고 주\n" not in env.brain.prompts[0]
    assert not (env.settings.paths.data_dir / "reviews").exists()


async def test_review_save_error_keeps_runs_done_and_logs_type_only(tmp_path, conn, state, monkeypatch, caplog):
    import logging

    from my_planner.harness import dispatcher as dispatcher_mod

    def boom(*a, **k):
        raise PermissionError("C:/secret/path 회고 본문")

    monkeypatch.setattr(dispatcher_mod, "save_weekly_review", boom)
    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 25, 18, 10))
    eve, review = _queued_sunday(env)
    with caplog.at_level(logging.INFO, logger="my_planner"):
        await env.process_run(eve, [review])

    assert [env.runs.get(i).status for i in (eve.id, review.id)] == [RunStatus.done, RunStatus.done]
    recs = [r for r in caplog.records if r.getMessage() == "review_save_error"]
    assert len(recs) == 1 and recs[0].error_type == "PermissionError" and recs[0].exc_info is None
    assert "secret" not in caplog.text and "회고 본문" not in caplog.text


async def test_saved_review_is_redacted_and_overwrites_same_week(tmp_path, conn, state):
    # 같은 주에 다시 저장되면 덮어쓴다. 파일에는 원문 기록과 같은 가림을 거친 답만 남는다
    env = _env(
        tmp_path, conn, state, [FakeTurn([], "계좌 110-123-456789로 정리했어요. 한 주 수고하셨어요.")],
        start=kst(2026, 10, 25, 18, 10),
    )
    path = _review_file(env, "2026-W43")
    path.parent.mkdir(parents=True)
    path.write_text("예전 내용", encoding="utf-8")
    eve, review = _queued_sunday(env)
    await env.process_run(eve, [review])

    body = path.read_text(encoding="utf-8")
    assert "예전 내용" not in body and "110-123-456789" not in body
    assert "계좌 [가림]로 정리했어요. 한 주 수고하셨어요." in body
    assert not list(path.parent.glob("*.tmp"))


async def test_review_saved_when_delivered_by_resend(tmp_path, conn, state):
    # 바로 3회 전송이 안 되면 저장하지 않고, 5분 뒤 재전송이 되면 그때 두 회차 done과 함께 저장한다
    from test_dispatcher_runs import TimedSender, _wait_for

    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=kst(2026, 10, 25, 18, 10))
    env.sender = env.dispatcher.sender = TimedSender(env.clock, fail_times=3)
    eve, review = _queued_sunday(env)
    path = _review_file(env, "2026-W43")
    env.dispatcher.start()
    env.dispatcher.submit_run(eve, [review])
    await _wait_for(lambda: env.runs.get(eve.id).status is RunStatus.failed)
    assert not path.exists()
    await _wait_for(lambda: env.runs.get(eve.id).resent == 1)
    await env.dispatcher.stop(timeout=5)

    assert [env.runs.get(i).status for i in (eve.id, review.id)] == [RunStatus.done, RunStatus.done]
    assert REVIEW_REPLY in path.read_text(encoding="utf-8")


def test_review_prompt_covers_week_without_banned_words():
    text = prompts.load("review_week.md")
    for must in ("돌아보기", "우선순위 1~3개", "propose_tasks", "set_priorities", "week", "## 회고 주", "초안"):
        assert must in text, must
    for word in ("놓쳤어요", "밀렸어요", "늦었지만", "실패"):
        assert word not in text, word


async def test_reply_monday_morning_continues_merged_review_conversation(tmp_path, conn, state):
    # 일 18:10 저녁+회고 합쳐 보냄 → 월 09:00 답장. 저녁 창(월 04:00)은 지났지만 회고 창(24시간, 월 18:00) 안이라
    # 같은 run 대화로 잇는다. 창은 primary와 merged_run_ids 가운데 가장 늦은 끝이다
    env = _env(
        tmp_path, conn, state,
        [FakeTurn([], REVIEW_REPLY, session_id="rev-s"), FakeTurn([], "좋아요, 그걸로 정할게요.", session_id="rev-s"),
         FakeTurn([], "새 대화", session_id="chat-s")],
        start=kst(2026, 10, 25, 18, 10),
    )
    eve, review = _queued_sunday(env)
    await env.process_run(eve, [review])
    run_conv = env.runs.get(eve.id).conversation_id

    env.clock.set(kst(2026, 10, 26, 9, 0))
    await env.process(env.inbound("이걸로 해", update_id=1))
    assert env.brain.session_ids[1] == "rev-s"
    assert env.brain.calls[1]["run_ctx"].conversation_id == run_conv

    env.clock.set(kst(2026, 10, 25, 18, 0) + timedelta(hours=24, minutes=1))  # 회고 창 밖
    await env.process(env.inbound("다른 얘기", update_id=2))
    assert env.brain.session_ids[2] is None


def _review_at(env, at):
    review = env.runs.ensure(LoopKey.review, at, Cadence.week)
    env.runs.mark_queued(review.id)
    return env.runs.get(review.id)


async def test_review_week_at_iso_year_start(tmp_path, conn, state):
    # 2026-01-04(일)은 ISO 2026-W01(2025-12-29~2026-01-04)
    at = kst(2026, 1, 4, 18, 0)
    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=at + timedelta(minutes=10))
    await env.process_run(_review_at(env, at))

    note = env.brain.prompts[0][env.brain.prompts[0].index("## 회고 주\n"):]
    assert "2026-W01 (12/29~1/4)" in note and "2026-W02 (1/5~1/11)" in note
    assert _review_file(env, "2026-W01").exists()


async def test_review_week_53(tmp_path, conn, state):
    # 2027-01-03(일)은 ISO 2026-W53. 다음 주는 2027-W01
    at = kst(2027, 1, 3, 18, 0)
    env = _env(tmp_path, conn, state, [FakeTurn([], REVIEW_REPLY)], start=at + timedelta(minutes=10))
    await env.process_run(_review_at(env, at))

    note = env.brain.prompts[0][env.brain.prompts[0].index("## 회고 주\n"):]
    assert "2026-W53 (12/28~1/3)" in note and "2027-W01 (1/4~1/10)" in note
    assert _review_file(env, "2026-W53").exists()

"""대화 상대마다 따로 고르는 대화 (SP12 스펙 5.2): 비서·메이트가 같은 앱 통로에서 서로의 대화를 닫거나 잇지 않는다.

가짜 시계의 디스패처(`test_dispatcher_messages.Env`)에서 받을 때 고르기(`route_app_message`)만 본다. 두뇌는 부르지 않는다.
"""

from datetime import timedelta

import pytest
from test_dispatcher_messages import Env, kst

from my_planner.domain import ConversationKind

START = kst(2026, 10, 31, 19, 0)


def env_at(tmp_path, conn, state):
    return Env(tmp_path, conn, state, script=[], start=START)


def route(env, agent="secretary", **kw):
    kw.setdefault("conversation_id", None)
    kw.setdefault("checkin_id", None)
    return env.dispatcher.route_app_message(env.clock.now(), agent=agent, **kw)


def test_mate_message_opens_own_conversation(tmp_path, conn, state):
    env = env_at(tmp_path, conn, state)
    sec = route(env)
    env.clock.advance(timedelta(minutes=10))
    mate = route(env, "mate")

    assert mate.id != sec.id
    assert mate.agent == "mate" and mate.kind is ConversationKind.chat and mate.channel == "app"
    assert env.convs.get(sec.id).closed_at is None  # 비서 대화는 열린 채
    assert sec.agent == "secretary"


def test_alternating_agents_keep_own_conversations(tmp_path, conn, state):
    """Review Focus 1: 비서 → 메이트 → 비서(5분 간격). 비서 둘째 메시지는 첫 비서 대화에 잇는다."""
    env = env_at(tmp_path, conn, state)
    a = route(env)
    env.clock.advance(timedelta(minutes=5))
    b = route(env, "mate")
    env.clock.advance(timedelta(minutes=5))
    c = route(env)

    assert c.id == a.id and b.id != a.id
    assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 2
    assert all(env.convs.get(i).closed_at is None for i in (a.id, b.id))


def test_close_expired_per_agent(tmp_path, conn, state):
    env = env_at(tmp_path, conn, state)
    sec = route(env)
    env.clock.advance(timedelta(minutes=30))
    mate = route(env, "mate")
    env.clock.advance(timedelta(minutes=1))  # 비서 마지막 31분 전, 메이트 1분 전
    env.dispatcher.router.close_expired()

    assert env.convs.get(sec.id).closed_at is not None
    assert sec.id in env.convs.summary_pending()
    assert env.convs.get(mate.id).closed_at is None


def test_mate_skips_run_and_plan_rules(tmp_path, conn, state):
    """메이트에는 계획·회차 갈래가 없다(5.2-2): 앱 계획 대화가 열려 있어도 메이트 메시지는 메이트 `chat`으로."""
    env = env_at(tmp_path, conn, state)
    plan = env.dispatcher.router.start_plan("app")
    mate = route(env, "mate")

    assert mate.kind is ConversationKind.chat and mate.agent == "mate"
    assert env.convs.get(plan.id).closed_at is None


def test_mate_asked_id_must_match_agent(tmp_path, conn, state):
    """`asked_id` 갈래(앱이 보낸 대화 id)도 상대를 본다: 비서 대화 id를 실은 메이트 메시지는 그 대화를 잇지 않는다."""
    env = env_at(tmp_path, conn, state)
    sec = route(env)
    mate = route(env, "mate", conversation_id=sec.id)

    assert mate.id != sec.id and mate.agent == "mate"


def test_resume_other_agent_rejected(tmp_path, conn, state):
    env = env_at(tmp_path, conn, state)
    sec = route(env)
    with pytest.raises(ValueError, match="agent_mismatch"):
        route(env, "mate", resume_conversation_id=sec.id)
    mate = route(env, "mate")
    with pytest.raises(ValueError, match="agent_mismatch"):
        route(env, resume_conversation_id=mate.id)


def test_resume_secretary_keeps_mate_open(tmp_path, conn, state):
    env = env_at(tmp_path, conn, state)
    old = route(env)
    env.convs.close(old.id)
    env.clock.advance(timedelta(minutes=5))
    sec_now = route(env)
    mate = route(env, "mate")
    env.clock.advance(timedelta(minutes=5))
    got = route(env, resume_conversation_id=old.id)

    assert got.id == old.id and got.closed_at is None
    assert env.convs.get(sec_now.id).closed_at is not None  # 같은 상대의 열린 대화는 닫는다(SP9 7.3)
    assert env.convs.get(mate.id).closed_at is None


def test_new_conversation_closes_only_that_agent(tmp_path, conn, state):
    env = env_at(tmp_path, conn, state)
    sec = route(env)
    mate = route(env, "mate")

    assert env.dispatcher.new_conversation("mate") == [mate.id]
    assert env.convs.get(sec.id).closed_at is None
    mate2 = route(env, "mate")
    assert env.dispatcher.new_conversation() == [sec.id]  # 기본은 비서
    assert env.convs.get(mate2.id).closed_at is None


def test_continued_from_inherits_agent(tmp_path, conn, state):
    """닫힌 계획 대화를 고르면 그것을 잇는 새 `chat`(`continued_from`)은 고른 대화의 상대(비서)다. 메이트는 그대로."""
    env = env_at(tmp_path, conn, state)
    plan = env.dispatcher.router.start_plan("app")
    env.convs.close(plan.id)
    mate = route(env, "mate")
    got = route(env, resume_conversation_id=plan.id)

    assert got.continued_from == plan.id and got.kind is ConversationKind.chat
    assert got.agent == "secretary"
    assert env.convs.get(mate.id).closed_at is None


def test_current_app_conversation_per_agent(tmp_path, conn, state):
    env = env_at(tmp_path, conn, state)
    sec = route(env)
    assert env.dispatcher.current_app_conversation(None, "mate") is None
    mate = route(env, "mate")
    assert env.dispatcher.current_app_conversation(None, "mate").id == mate.id
    assert env.dispatcher.current_app_conversation(None).id == sec.id
    assert env.dispatcher.current_app_conversation(sec.id, "mate").id == mate.id  # 다른 상대의 id는 쓰지 않는다

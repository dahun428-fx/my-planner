"""메이트 도구 (SP12 스펙 5.3, 6장, 7.2~7.3, 8장, 10장 X13), 앞머리(5.5). 도구를 직접 부른다. 내용은 꾸며 낸 것이다."""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import RunContext
from my_planner.harness.mate_context import build_mate_preamble
from my_planner.store.repos.activity import ActivityRepo, ConfirmsRepo
from my_planner.store.repos.body import BodyDay, BodyRepo
from my_planner.store.repos.conditions import ConditionsRepo
from my_planner.store.repos.conversations import ConversationsRepo
from my_planner.store.repos.events import EventsRepo
from my_planner.store.repos.habits import HabitsRepo
from my_planner.store.repos.status import StatusRepo
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.repos.workout import WorkoutRepo
from my_planner.store.transcripts import TranscriptStore
from my_planner.tools.actions import ActionDeps, ActionRequest, apply_action
from my_planner.tools.confirmations import render_confirmations
from my_planner.tools.core import Tools
from my_planner.tools.workout import MSG_LOG_RANGE, MSG_NOTES_FULL

TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
SAT_1000 = kst(2026, 10, 31, 10, 0)  # 논리적 오늘 10-31(토)


class WorkoutEnv:
    def __init__(self, tmp_path, conn, now=SAT_1000):
        self.clock = FakeClock(now)
        self.conn = conn
        self.activity = ActivityRepo(conn, self.clock)
        self.confirms = ConfirmsRepo(conn, self.clock)
        self.status = StatusRepo(conn, self.clock)
        self.workout = WorkoutRepo(conn, self.clock)
        self.conditions = ConditionsRepo(conn, self.clock)
        self.body = BodyRepo(conn, self.clock)
        self.events = EventsRepo(conn, self.clock, TZ)
        self.convs = ConversationsRepo(conn, self.clock)
        self.tasks = TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY)
        self.habits = HabitsRepo(conn, self.clock)
        self.tools = Tools(
            tasks=self.tasks, habits=self.habits,
            transcripts=TranscriptStore(tmp_path / "data", TZ, BOUNDARY),
            export_path=tmp_path / "data" / "exports" / "tasks.md", clock=self.clock, tz=TZ, boundary=BOUNDARY,
            conditions=self.conditions, activity=self.activity, confirms=self.confirms, status=self.status,
            body=self.body, events=self.events, conversations=self.convs, workout=self.workout,
        )
        self.deps = ActionDeps(tools=self.tools, clock=self.clock, activity=self.activity, confirms=self.confirms)

    def mate(self):
        """메이트 대화의 사용자 차례(두뇌)."""
        return RunContext(conversation_id=7, run_id=None, inbound_id=1001, channel="app", agent="mate")

    def button(self):
        return RunContext(conversation_id=None, run_id=None, actor="user", channel="app")

    def acts(self):
        return [self.activity.get(r[0]) for r in self.conn.execute("SELECT id FROM activity ORDER BY id")]

    def last(self, kind):
        return [a for a in self.acts() if a.kind == kind][-1]

    def undo(self, aid):
        res = apply_action(
            self.deps, ActionRequest("undo", {"activity_id": aid}, actor="user", channel="app", endpoint="undo")
        )
        return res.status

    def log(self, **kw):
        kw.setdefault("title", "하체")
        out = self.tools.log_workout(self.mate(), **kw)
        assert "error" not in out, out
        return out["log"]["id"]

    def ledger(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM status_xp_ledger WHERE source_kind = 'workout_log' ORDER BY id"
        )]

    def snapshot(self):
        q = self.conn.execute
        return (
            [tuple(r) for r in q("SELECT * FROM workout_plans ORDER BY id")],
            [tuple(r) for r in q("SELECT * FROM workout_plan_sessions ORDER BY id")],
            [tuple(r) for r in q("SELECT * FROM activity ORDER BY id")],
        )


@pytest.fixture
def env(tmp_path, conn):
    return WorkoutEnv(tmp_path, conn)


def item(name="고블릿 스쿼트", **kw):
    out = {"name": name, "sets": 3, "reps": "8-10", "weight_kg": 16, "minutes": None, "note": None}
    out.update(kw)
    return out


def session(position=1, label="하체", weekdays=(0, 3), items=None):
    return {
        "position": position, "label": label, "weekdays": list(weekdays) if weekdays is not None else None,
        "items": items if items is not None else [item()],
    }


def plan(env, title="A", sessions=None):
    out = env.tools.set_workout_plan(env.mate(), title=title, note=None, sessions=sessions or [session()])
    assert "error" not in out, out
    return out["plan"]


# --- 기록 (8장, X13) ---


def test_log_date_window(tmp_path, conn):
    env = WorkoutEnv(tmp_path, conn)
    ok = env.tools.log_workout(env.mate(), title="하체", date="2026-10-25")
    assert "error" not in ok
    assert env.tools.log_workout(env.mate(), title="하체", date="2026-10-24") == {"error": MSG_LOG_RANGE}
    assert env.tools.log_workout(env.mate(), title="하체", date="2026-11-01") == {"error": MSG_LOG_RANGE}
    env.clock.set(kst(2026, 11, 1, 3, 59))  # 아직 논리적 10-31
    assert "error" not in env.tools.log_workout(env.mate(), title="하체", date="2026-10-25")
    env.clock.set(kst(2026, 11, 1, 4, 0))
    assert env.tools.log_workout(env.mate(), title="하체", date="2026-10-25") == {"error": MSG_LOG_RANGE}
    assert env.tools.log_workout(env.mate(), title="하체", date="20261031")["error"]


def test_log_xp_once_per_day(env):
    first = env.log()
    env.log(title="걷기")
    rows = env.ledger()
    assert [(r["amount"], r["source_ref"], r["label"], r["area"], r["logical_date"]) for r in rows] == [
        (5, "workout_day:2026-10-31", "운동 기록", "health", "2026-10-31")
    ]
    assert "error" not in env.tools.delete_workout_log(env.button(), id=first)
    assert len(env.ledger()) == 1
    env.log(date="2026-10-30")
    assert [r["source_ref"] for r in env.ledger()] == ["workout_day:2026-10-31", "workout_day:2026-10-30"]


def test_log_activity_and_confirmation(env):
    ctx = env.mate()
    out = env.tools.log_workout(ctx, title="하체", items=[{"name": "스쿼트", "sets": 5, "reps": 5, "weight_kg": 60}])
    a = env.last("workout_logged")
    lid = out["log"]["id"]
    assert (a.summary, a.target, a.actor, a.undo) == ("운동 기록: 하체", f"workout_log:{lid}", "secretary", {"log_id": lid})
    assert render_confirmations(ctx.events, env.tools.today()) == "✓ 운동 기록: 하체"
    assert out["log"]["items"][0] == {
        "name": "스쿼트", "sets": 5, "reps": 5, "weight_kg": 60, "minutes": None, "distance_km": None,
    }
    assert env.undo(a.id) == "undone"
    assert env.workout.log(lid) is None


def test_log_items_limits(env):
    many = [{"name": f"운동{i}", "sets": 1} for i in range(20)]
    assert "error" not in env.tools.log_workout(env.mate(), title="많이", items=many)
    assert "error" in env.tools.log_workout(env.mate(), title="많이", items=[*many, {"name": "하나 더"}])
    assert "error" in env.tools.log_workout(env.mate(), title="하체", items=[{"name": "스쿼트", "reps": 0}])
    assert "error" in env.tools.log_workout(env.mate(), title="하체", items=[{"name": "스쿼트", "weight_kg": 501}])
    assert "error" in env.tools.log_workout(env.mate(), title="하체", effort=6)
    lid = env.log(items=[{"name": "스쿼트", "sets": 5, "reps": 5, "weight_kg": 60}])
    ctx = env.mate()
    out = env.tools.update_workout_log(ctx, id=lid, items=[{"name": "스쿼트", "sets": 5, "reps": 5, "weight_kg": 65}])
    assert out["log"]["items"][0]["weight_kg"] == 65
    a = env.last("workout_log_updated")
    assert a.summary == "운동 기록 고침: 하체"
    assert render_confirmations(ctx.events, env.tools.today()) == "✓ 운동 기록 고침: 하체"
    assert env.undo(a.id) == "undone"
    assert env.workout.log(lid).items[0].weight_kg == 60
    assert "error" in env.tools.update_workout_log(env.mate(), id=lid, nope=1)


def test_list_workouts(env):
    env.log(items=[{"name": "고블릿 스쿼트", "sets": 3}])
    env.log(title="걷기", date="2026-10-26", items=[{"name": "걷기", "minutes": 30}])
    assert [g["title"] for g in env.tools.list_workouts(env.mate())["logs"]] == ["하체", "걷기"]
    assert [g["title"] for g in env.tools.list_workouts(env.mate(), name="스쿼트")["logs"]] == ["하체"]
    assert [g["title"] for g in env.tools.list_workouts(env.mate(), days=1)["logs"]] == ["하체"]
    assert "error" in env.tools.list_workouts(env.mate(), days=181)
    assert "error" in env.tools.list_workouts(env.mate(), days=0)


def test_delete_log_needs_confirm_from_brain(env):
    lid = env.log(date="2026-10-30")
    ctx = env.mate()
    out = env.tools.delete_workout_log(ctx, id=lid)
    assert out["status"] == "needs_confirm" and out["confirm_token"]
    assert out["summary"] == "운동 기록 '하체'(10-30)를 지울까요?"
    assert env.workout.log(lid) is not None
    assert [e.kind for e in ctx.events] == ["confirm_requested"] and ctx.events[0].data["card"] is True
    # 확인 카드의 ✓(`/actions` + 토큰)로 지운다
    res = apply_action(env.deps, ActionRequest(
        "delete_workout_log", {"id": lid}, actor="user", channel="app", confirm_token=out["confirm_token"],
    ))
    assert res.status == "applied", res.body
    assert env.workout.log(lid) is None
    assert env.last("workout_log_deleted").target == f"workout_log:{lid}"


def test_delete_log_from_app_asks_first(env):
    lid = env.log()
    res = apply_action(env.deps, ActionRequest("delete_workout_log", {"id": lid}, actor="user", channel="app"))
    assert res.status == "needs_confirm"
    assert res.body["summary"] == "운동 기록 '하체'(10-31)를 지울까요?"
    assert env.workout.log(lid) is not None


# --- 플랜 (7.2~7.3) ---


def test_plan_activity_and_confirmation(env):
    ctx = env.mate()
    out = env.tools.set_workout_plan(ctx, title="주 3회", note="가볍게", sessions=[
        session(2, "걷기", None, [item("걷기", sets=None, reps=None, weight_kg=None, minutes=30)]), session(1),
    ])
    p = out["plan"]
    assert [s["label"] for s in p["sessions"]] == ["하체", "걷기"]  # position 순
    assert p["sessions"][0]["weekdays"] == [0, 3] and p["sessions"][1]["weekdays"] is None
    a = env.last("workout_plan_set")
    assert a.summary == "운동 플랜 바꿈" and a.undo == {"new_id": p["id"], "prev_id": None}
    assert sorted(env.activity.targets(a.id)) == sorted(["workout_plan:current", f"workout_plan:{p['id']}"])
    assert render_confirmations(ctx.events, env.tools.today()) == "✓ 운동 플랜 바꿈"
    ctx2 = env.mate()
    assert env.tools.set_workout_plan(ctx2, title=None, note=None, sessions=[]) == {"plan": None}
    c = env.last("workout_plan_set")
    assert c.summary == "운동 플랜 내림" and c.undo == {"cleared_id": p["id"]}
    assert render_confirmations(ctx2.events, env.tools.today()) == "✓ 운동 플랜 내림"
    n = len(env.acts())
    assert env.tools.set_workout_plan(env.mate(), title=None, note=None, sessions=[]) == {"plan": None}
    assert len(env.acts()) == n  # 지금 플랜이 없으면 아무것도 바꾸지 않는다


def test_plan_undo_latest_only(env):
    a = plan(env, "A")
    plan(env, "B")
    ab = env.last("workout_plan_set")
    b_id = ab.undo["new_id"]
    plan(env, "C")
    bc = env.last("workout_plan_set")
    assert ab.undo == {"new_id": b_id, "prev_id": a["id"]}
    assert set(env.activity.targets(ab.id)) == {"workout_plan:current", f"workout_plan:{a['id']}", f"workout_plan:{b_id}"}
    assert env.undo(ab.id) == "superseded"
    assert env.undo(bc.id) == "undone"
    assert env.workout.current_plan().title == "B"


def test_plan_undo_after_clear(env):
    plan(env, "A")
    env.tools.set_workout_plan(env.mate(), title=None, note=None, sessions=[])
    clear = env.last("workout_plan_set")
    plan(env, "B")
    make_b = env.last("workout_plan_set")
    assert make_b.undo["prev_id"] is None
    assert env.undo(clear.id) == "superseded"
    assert env.undo(make_b.id) == "undone"
    assert env.workout.current_plan() is None


def test_plan_undo_clear(env):
    a = plan(env, "A")
    env.tools.set_workout_plan(env.mate(), title=None, note=None, sessions=[])
    assert env.undo(env.last("workout_plan_set").id) == "undone"
    assert env.workout.current_plan().id == a["id"]


def test_set_plan_rejects_partial_shapes(env):
    plan(env, "A")
    before = env.snapshot()
    bad = [
        [session(items=[])],
        [session(1), session(1, "상체")],
        [session(1), session(3, "상체")],
        [session(i, f"세션{i}") for i in range(1, 9)],
        [session(items=[item(weight_kg=0.3)])],
        [session(weekdays=[7])],
        [session(weekdays=[1, 1])],
        [session(items=[item(sets=11)])],
        [session(items=[item(reps="12345678901")])],
        [session(items=[item(minutes=181)])],
        [session(items=[item(note="가" * 61)])],
        [session(items=[item(name="")])],
        [session(label="")],
        [session(items=[item() for _ in range(13)])],
    ]
    for sessions in bad:
        out = env.tools.set_workout_plan(env.mate(), title="B", note=None, sessions=sessions)
        assert "error" in out, sessions
        assert env.snapshot() == before, sessions
    assert "error" in env.tools.set_workout_plan(env.mate(), title="", note=None, sessions=[session()])
    assert "error" in env.tools.set_workout_plan(env.mate(), title="B", note="가" * 301, sessions=[session()])
    assert env.snapshot() == before
    seven = [session(i, f"세션{i}") for i in range(1, 8)]
    assert "error" not in env.tools.set_workout_plan(env.mate(), title="B", note=None, sessions=seven)


def test_log_session_id_must_exist(env):
    p = plan(env)
    sid = p["sessions"][0]["id"]
    assert "error" not in env.tools.log_workout(env.mate(), title="하체", session_id=sid)
    assert "error" in env.tools.log_workout(env.mate(), title="하체", session_id=sid + 100)


# --- 몸 메모 (6장) ---


def test_body_note_limits(env):
    ctx = env.mate()
    for i in range(30):
        assert "error" not in env.tools.save_body_note(ctx, kind="other", text=f"메모 {i}")
    assert env.tools.save_body_note(ctx, kind="other", text="서른한 번째") == {"error": MSG_NOTES_FULL}
    same = env.tools.save_body_note(ctx, kind="other", text="메모 3")
    assert same["note"]["text"] == "메모 3"
    assert env.workout.count_notes() == 30
    first = env.workout.notes()[-1]
    out = env.tools.save_body_note(ctx, kind="injury", text="왼쪽 무릎", id=first.id)  # 고치기는 상한과 상관없다
    assert out["note"] == {"id": first.id, "kind": "injury", "text": "왼쪽 무릎"}
    assert "error" in env.tools.save_body_note(ctx, kind="nope", text="x")
    assert "error" in env.tools.save_body_note(ctx, kind="other", text="가" * 121)
    assert "error" in env.tools.save_body_note(ctx, kind="other", text="x", id=9999)


def test_body_note_edit_into_existing_returns_existing(env):
    """고치기로 다른 살아 있는 메모와 같은 kind·text가 되면 중복을 만들지 않고 그 메모를 그대로 준다."""
    ctx = env.mate()
    a = env.tools.save_body_note(ctx, kind="injury", text="왼쪽 무릎")["note"]
    b = env.tools.save_body_note(ctx, kind="other", text="초안")["note"]
    out = env.tools.save_body_note(ctx, kind="injury", text="왼쪽 무릎", id=b["id"])
    assert out["note"] == a
    assert env.workout.note(b["id"]).text == "초안"
    assert env.workout.count_notes() == 2


def test_body_note_is_redacted(env):
    out = env.tools.save_body_note(env.mate(), kind="other", text="헬스장 회비 계좌 110-123-456789")
    saved = env.workout.note(out["note"]["id"]).text
    assert "[가림]" in saved and "456789" not in saved


def test_body_note_save_has_no_activity_drop_has(env):
    ctx = env.mate()
    nid = env.tools.save_body_note(ctx, kind="equipment", text="집에 덤벨 20kg까지")["note"]["id"]
    env.tools.save_body_note(ctx, kind="equipment", text="집에 덤벨 24kg까지", id=nid)
    assert env.acts() == [] and ctx.events == []
    ctx2 = env.mate()
    assert "error" not in env.tools.drop_body_note(ctx2, id=nid)
    acts = env.acts()
    assert [(a.kind, a.summary, a.target, a.undo) for a in acts] == [
        ("body_note_dropped", "몸 메모 지움", f"body_note:{nid}", {"note_id": nid})
    ]
    assert render_confirmations(ctx2.events, env.tools.today()) == "✓ 몸 메모 지움"
    assert env.workout.note(nid) is None
    assert env.undo(acts[0].id) == "undone"
    assert env.workout.note(nid).text == "집에 덤벨 24kg까지"


def test_drop_body_note_from_app(env):
    nid = env.tools.save_body_note(env.mate(), kind="other", text="아침형")["note"]["id"]
    res = apply_action(env.deps, ActionRequest("drop_body_note", {"id": nid}, actor="user", channel="app"))
    assert res.status == "applied" and res.body["confirmation"] == "✓ 몸 메모 지움"


# --- 지난 대화 (5.3) ---


def test_find_conversations_scoped_by_agent(env):
    for agent, title in (("secretary", "치과 예약 정리"), ("mate", "하체 플랜 정리")):
        c = env.convs.open("chat", env.tools.today(), channel="app", agent=agent)
        env.convs.touch(c.id)
        env.convs.set_summary(c.id, title, "요약", env.clock.now())
        env.convs.close(c.id)
    got = env.tools.find_conversations(env.mate())["items"]
    assert [i["title"] for i in got] == ["하체 플랜 정리"]


# --- 앞머리 (5.5) ---


def _preamble(env):
    return build_mate_preamble(
        now=env.clock.now(), tz=TZ, boundary=BOUNDARY, conditions=env.conditions, body=env.body,
        events=env.events, workout=env.workout, tasks=env.tasks, habits=env.habits,
    )


def _section(text, title):
    start = text.index(f"## {title}\n") + len(f"## {title}\n")
    end = text.find("\n\n## ", start)
    return text[start:end if end != -1 else None]


def test_mate_preamble_sections(env):
    empty = _preamble(env)
    assert _section(empty, "오늘") == "2026-10-31 (토) 10:00, 논리적 날짜"
    assert _section(empty, "오늘 몸") == "- 컨디션: 기록 없음\n- 지난밤 잠: 기록 없음\n- 최근 7일 걸음: 기록 없음"
    assert _section(empty, "오늘 일정") == "없음"
    assert _section(empty, "몸 메모") == "아직 없음"
    assert _section(empty, "지금 플랜") == "아직 없음"
    assert _section(empty, "최근 기록 (14일, 최대 8개)") == "아직 없음"
    assert _section(empty, "비서 쪽 운동 흔적 (14일, 최대 10개)") == "없음"
    assert env.tools.get_mate_context(env.mate()) == {"text": empty}

    env.conditions.upsert(env.tools.today(), 3, None)
    env.body.upsert([BodyDay(env.tools.today(), 7000, 370), BodyDay(env.tools.today() - timedelta(days=1), 7400, None)],
                    env.clock.now())
    env.tools.create_event(env.button(), title="저녁 약속", date="2026-10-31", time="19:00")
    ctx = env.mate()
    for i in range(30):
        env.tools.save_body_note(ctx, kind="equipment", text=f"메모 {i}")
    env.tools.drop_body_note(ctx, id=env.workout.notes()[0].id)
    env.tools.save_body_note(ctx, kind="equipment", text="메모 30")  # 31행, 지우지 않은 것 30
    plan(env, "주 3회", [session(1, "하체", (0, 3), [item("고블릿 스쿼트", reps="10"), item("플랭크", sets=None, reps=None,
                                                                                  weight_kg=None, minutes=5)])])
    old = env.log(title="오래된", date="2026-10-25")
    gone = env.log(title="지운 것")
    env.tools.delete_workout_log(env.button(), id=gone)
    for i in range(9):
        env.log(title=f"기록{i}", date="2026-10-30", effort=3,
                items=[{"name": "덤벨 프레스", "sets": 3, "reps": 10, "weight_kg": 14}])
    text = _preamble(env)
    assert _section(text, "오늘 몸") == "- 컨디션: 3\n- 지난밤 잠: 6시간 10분\n- 최근 7일 걸음: 하루 평균 7,200"
    assert _section(text, "오늘 일정") == "- 19:00 저녁 약속"
    notes = _section(text, "몸 메모").splitlines()
    assert len(notes) == 30 and notes[0].startswith("- [장비] 메모 ")
    assert _section(text, "지금 플랜").splitlines()[1] == "1. 하체 (월·목) — 고블릿 스쿼트 3x10 @16kg, 플랭크 5분"
    logs = _section(text, "최근 기록 (14일, 최대 8개)").splitlines()
    assert len(logs) == 8
    assert logs[0].startswith("- 10-30 (금) 기록8 — 덤벨 프레스 3x10 @14kg · 힘듦 3 (#")
    assert "지운 것" not in text and not any(line.endswith(f"(#{old})") for line in logs)


def test_mate_preamble_drops_old_logs(tmp_path, conn):
    env = WorkoutEnv(tmp_path, conn, now=kst(2026, 10, 25, 10, 0))
    env.log(title="보름 전")
    env.clock.set(kst(2026, 11, 9, 10, 0))  # 15일 뒤
    assert _section(_preamble(env), "최근 기록 (14일, 최대 8개)") == "아직 없음"
    env.clock.set(kst(2026, 11, 7, 10, 0))  # 13일 뒤: 14일 안
    assert "보름 전" in _preamble(env)


def test_update_log_date_grants_xp_for_new_day(env):
    lid = env.log()
    assert "error" not in env.tools.update_workout_log(env.mate(), id=lid, date="2026-10-30")
    assert [r["source_ref"] for r in env.ledger()] == ["workout_day:2026-10-31", "workout_day:2026-10-30"]  # 옛 날짜는 그대로
    other = env.log(title="걷기")
    assert "error" not in env.tools.update_workout_log(env.mate(), id=other, date="2026-10-30")
    assert len(env.ledger()) == 2  # 이미 있는 날은 겹쳐 주지 않는다
    assert "error" not in env.tools.update_workout_log(env.mate(), id=other, note="좋았어요")
    assert len(env.ledger()) == 2


# --- 비서 쪽 운동 흔적 ---


def _traces_seed(env):
    """건강 습관 체크 2번, 운동 낱말 습관(다른 영역) 1번, 운동과 무관한 습관·할 일, 끝낸 운동 할 일 1개."""
    now = env.clock.now()
    gym = env.habits.add("헬스", "health", "weekly", 3, now)
    walk = env.habits.add("저녁 산책", "quality_of_life", "daily", None, now)
    read = env.habits.add("책 읽기", "learning", "daily", None, now)
    today = env.tools.today()
    env.habits.check(gym.id, today - timedelta(days=1), now)
    env.habits.check(gym.id, today - timedelta(days=20), now)  # 14일 밖
    env.habits.check(walk.id, today - timedelta(days=2), now)
    env.habits.check(read.id, today - timedelta(days=1), now)
    run = env.tasks.create("러닝 5km", ["quality_of_life"])
    env.tasks.set_status(run.id, "done")  # 오늘 끝냄
    mail = env.tasks.create("메일 보내기", ["career"])
    env.tasks.set_status(mail.id, "done")
    env.tasks.create("수영 등록", ["health"])  # 아직 안 끝냄
    return gym, walk, run


def test_mate_preamble_shows_secretary_traces(env):
    gym, walk, run = _traces_seed(env)
    lines = _section(_preamble(env), "비서 쪽 운동 흔적 (14일, 최대 10개)").splitlines()
    assert lines == [
        f"- 10-31 (토) 할 일 끝냄: 러닝 5km (task:{run.id})",
        f"- 10-30 (금) 습관 체크: 헬스 (habit:{gym.id})",
        f"- 10-29 (목) 습관 체크: 저녁 산책 (habit:{walk.id})",
    ]
    assert env.tools.get_mate_context(env.mate())["text"] == _preamble(env)


def test_list_workouts_returns_traces(env):
    gym, walk, run = _traces_seed(env)
    out = env.tools.list_workouts(env.mate(), days=14)
    assert out["logs"] == []
    assert [x["ref"] for x in out["traces"]] == [f"task:{run.id}", f"habit:{gym.id}", f"habit:{walk.id}"]
    assert out["traces"][1] == {"date": "2026-10-30", "kind": "habit", "title": "헬스", "ref": f"habit:{gym.id}"}
    assert len(env.tools.list_workouts(env.mate(), days=28)["traces"]) == 4  # 20일 전 헬스 체크까지
    assert [x["title"] for x in env.tools.list_workouts(env.mate(), name="헬스")["traces"]] == ["헬스", "헬스"]
    assert env.tools.list_workouts(env.mate(), days=1)["traces"] == [
        {"date": "2026-10-31", "kind": "task", "title": "러닝 5km", "ref": f"task:{run.id}"}
    ]


def test_traces_skip_deleted_habits(env):
    gym, _walk, _run = _traces_seed(env)
    env.conn.execute("UPDATE habits SET deleted_at = '2026-10-31T00:00:00+00:00' WHERE id = ?", (gym.id,))
    assert all(x["title"] != "헬스" for x in env.tools.list_workouts(env.mate())["traces"])

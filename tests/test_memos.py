"""메모 (SP9 스펙 6장): 마이그레이션 016, `MemosRepo`, 제목 규칙, 검색, 도구. 내용은 꾸며 낸 것이다."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, time, timedelta

import pytest
from fakes import FakeTurn
from test_dispatcher_messages import kst

from my_planner.clock import FakeClock
from my_planner.domain import Area, RunContext
from my_planner.store.db import migrate, open_db
from my_planner.store.repos.activity import ActivityRepo
from my_planner.store.repos.memos import Memo, MemoConflict, MemosRepo, memo_title
from my_planner.store.repos.tasks import TasksRepo
from my_planner.store.transcripts import TranscriptStore

NOW = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)  # 10/26(월) 14:00 KST
TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)


@pytest.fixture
def memos(conn):
    return MemosRepo(conn, FakeClock(NOW))


def fts_ids(conn, q):
    return [r[0] for r in conn.execute("SELECT rowid FROM memos_fts WHERE memos_fts MATCH ? ORDER BY rowid", (q,))]


# --- 슬라이스 1: 016 ---


def test_016_creates_tables_and_fts_triggers(tmp_path):
    conn = open_db(tmp_path / "planner.db")
    assert migrate(conn, upto=15) == 15
    assert migrate(conn) >= 16
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"memos", "memos_fts", "idx_memos_list"} <= names
    assert {"memos_ai", "memos_ad", "memos_au"} <= names
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'memos_fts'").fetchone()[0]
    assert "trigram" in sql
    at = "2026-10-26T05:00:00.000000+00:00"
    ins = "INSERT INTO memos (body, area, origin, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
    for bad in (("", None, "user"), ("x" * 20001, None, "user"), ("가", "money", "user"), ("가", None, "brain")):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ins, (*bad, at, at))
    conn.execute(ins, ("x" * 20000, "health", "chat", at, at))
    conn.close()


def test_fts_follows_update_and_delete(conn, memos):
    m = memos.create("읽을 책\n- [ ] 사피엔스", None, "user", NOW)
    assert fts_ids(conn, '"사피엔"') == [m.id]
    memos.update(m.id, "읽을 책\n- [ ] 총균쇠", None, m.updated_at, NOW + timedelta(minutes=1))
    assert fts_ids(conn, '"사피엔"') == [] and fts_ids(conn, '"총균쇠"') == [m.id]
    memos.pin(m.id, NOW + timedelta(minutes=2))  # 본문이 그대로면 색인도 그대로
    assert fts_ids(conn, '"총균쇠"') == [m.id]
    memos.delete(m.id, NOW + timedelta(minutes=3))
    assert fts_ids(conn, '"총균쇠"') == []
    memos.restore(m.id)
    assert fts_ids(conn, '"총균쇠"') == [m.id]
    memos.delete(m.id, NOW + timedelta(minutes=4))
    assert memos.purge_deleted(NOW + timedelta(days=31)) == 1
    assert conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 0
    conn.execute("INSERT INTO memos_fts(memos_fts) VALUES ('integrity-check')")  # 색인과 표가 맞다


# --- 슬라이스 2: 제목 ---


def test_title_from_first_line_strips_markup():
    assert memo_title("읽을 책\n- [ ] 사피엔스") == "읽을 책"
    assert memo_title("# 장보기 목록\n우유") == "장보기 목록"
    assert memo_title("- [ ] **사피엔스** 읽기") == "사피엔스 읽기"
    assert memo_title("- [x] 끝낸 일") == "끝낸 일"
    assert memo_title("- 목록 하나") == "목록 하나"
    assert memo_title("가" * 50) == "가" * 40
    assert memo_title("  -5도 아침  ") == "-5도 아침"  # 서식이 아닌 `-`는 그대로


def test_title_skips_empty_and_markup_only_lines():
    """Review Focus 4: 첫 줄이 `- [ ]`나 빈 줄이면 서식을 뺀 다음 비지 않은 줄, 그것도 없으면 "제목 없는 메모"."""
    assert memo_title("- [ ]\n\n  \n두 번째 줄 제목") == "두 번째 줄 제목"
    assert memo_title("\n\n#\n**\n- \n셋째") == "셋째"
    assert memo_title("- [ ]") == "제목 없는 메모"
    assert memo_title("   \n\n") == "제목 없는 메모"
    assert memo_title("#\n- [x]\n****") == "제목 없는 메모"


# --- 슬라이스 3: 검색 ---


def test_search_trigram_korean_substring_사피(conn, memos):
    m = memos.create("읽을 책\n- [ ] 사피엔스", None, "user", NOW)
    memos.create("장보기\n- 우유", None, "user", NOW)
    assert [x.id for x in memos.search("사피엔", 5)] == [m.id]  # 3글자: trigram
    assert [x.id for x in memos.search("피엔스", 5)] == [m.id]  # 단어 가운데
    assert [x.id for x in memos.search("사피", 5)] == [m.id]  # 완료 조건 6: 2글자는 LIKE
    assert [x.id for x in memos.list(q="사피")] == [m.id]
    assert memos.search('"사피', 5) == [] and memos.search("AND OR", 5) == []  # FTS 문법 글자도 글자 그대로


def test_two_char_query_uses_like(conn, memos):
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    m = memos.create("100% 확실", None, "user", NOW)
    memos.create("1000원", None, "user", NOW)
    seen.clear()
    assert [x.id for x in memos.search("0%", 5)] == [m.id]  # `%`는 LIKE 와일드카드가 아니다
    assert any(" LIKE " in s for s in seen) and not any("MATCH" in s for s in seen)
    seen.clear()
    memos.search("확실히", 5)
    assert any("MATCH" in s for s in seen)
    conn.set_trace_callback(None)


def test_deleted_not_searchable(memos):
    m = memos.create("비밀 계획 사피엔스", None, "user", NOW)
    memos.delete(m.id, NOW)
    assert memos.search("사피엔스", 5) == [] and memos.search("사피", 5) == []
    assert memos.list() == [] and memos.list(q="사피엔스") == [] and memos.get(m.id) is None


# --- 슬라이스 4: 고치기, 상한, 지우기 ---


def test_list_pinned_first_then_recent_and_cursor(memos):
    a = memos.create("가", None, "user", NOW)
    b = memos.create("나", None, "user", NOW + timedelta(minutes=1))
    c = memos.create("다", None, "user", NOW + timedelta(minutes=2))
    memos.pin(a.id, NOW + timedelta(minutes=3))
    first = memos.list(limit=1)
    assert [m.id for m in first] == [a.id, c.id]
    assert first[0].pinned and isinstance(first[0], Memo)
    cursor = (first[-1].updated_at, first[-1].id)
    assert [m.id for m in memos.list(limit=5, before=cursor)] == [b.id]  # 다음 쪽에는 고정 메모가 없다


def test_repo_update_conflict(memos):
    m = memos.create("처음", Area.learning, "user", NOW)
    later = NOW + timedelta(minutes=1)
    got = memos.update(m.id, "고침", None, m.updated_at, later)
    assert (got.body, got.area, got.updated_at) == ("고침", None, later)
    with pytest.raises(MemoConflict):
        memos.update(m.id, "다시", None, m.updated_at, later + timedelta(minutes=1))  # 옛 updated_at
    assert memos.get(m.id).body == "고침"


def test_purge_after_30_days(conn, memos):
    old = memos.create("오래된 것", None, "user", NOW)
    new = memos.create("최근 것", None, "user", NOW)
    live = memos.create("살아 있는 것", None, "user", NOW)
    memos.delete(old.id, NOW - timedelta(days=31))
    memos.delete(new.id, NOW - timedelta(days=29))
    assert memos.purge_deleted(NOW - timedelta(days=30)) == 1
    left = [r[0] for r in conn.execute("SELECT id FROM memos ORDER BY id")]
    assert left == [new.id, live.id]


# --- 도구 (6.3) ---


MON_1400 = kst(2026, 10, 26, 14, 0)


class MemoEnv:
    def __init__(self, tmp_path, conn, now=MON_1400):
        from my_planner.tools.core import Tools

        self.clock = FakeClock(now)
        self.conn = conn
        self.memos = MemosRepo(conn, self.clock)
        self.activity = ActivityRepo(conn, self.clock)
        self.tools = Tools(
            tasks=TasksRepo(conn, self.clock, tz=TZ, boundary=BOUNDARY),
            transcripts=TranscriptStore(tmp_path / "data", TZ, BOUNDARY),
            export_path=tmp_path / "data" / "exports" / "tasks.md", clock=self.clock, tz=TZ, boundary=BOUNDARY,
            activity=self.activity, memos=self.memos,
        )

    def chat(self):
        """앱 대화의 사용자 차례(두뇌)."""
        return RunContext(conversation_id=7, run_id=None, inbound_id=1001, channel="app")

    def button(self):
        """`/actions`(사용자)."""
        return RunContext(conversation_id=None, run_id=None, actor="user", channel="app")

    def rows(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM activity ORDER BY id")]


@pytest.fixture
def menv(tmp_path, conn):
    return MemoEnv(tmp_path, conn)


def test_tools_app_only_and_no_edit_tools():
    from my_planner.tools.mcp_adapter import (
        _SPECS,
        APP_ONLY_TOOLS,
        TOOL_NAMES,
        tool_names_for,
    )

    app = tool_names_for(RunContext(None, None, channel="app"))
    telegram = tool_names_for(RunContext(None, None, channel="telegram"))
    new = {"search_memos", "read_memo", "create_memo"}
    assert new <= set(APP_ONLY_TOOLS) and new <= set(app) and not new & set(TOOL_NAMES)
    assert len(app) == 44 == len(set(app)) and len(telegram) == 28  # 텔레그램 목록은 그대로(Q14)
    for edit in ("update_memo", "delete_memo", "pin_memo", "unpin_memo"):  # Q5: 고치기·지우기 도구는 없다
        assert edit not in app and edit not in _SPECS
    assert all(n in _SPECS for n in new)


def test_create_memo_origin_confirmation_and_run_turn(menv):
    from my_planner.tools.confirmations import render_confirmations

    ctx = menv.chat()
    out = menv.tools.create_memo(ctx, body="읽을 책\n- [ ] 사피엔스", area="learning")
    assert out == {"id": out["id"], "title": "읽을 책", "area": "learning"}  # 두뇌에는 본문을 돌려주지 않는다
    assert menv.memos.get(out["id"]).origin == "chat"
    assert render_confirmations(ctx.events, menv.tools.today()) == "✓ 메모를 만들었어요: 읽을 책"
    (row,) = menv.rows()
    assert (row["kind"], row["target"], row["actor"]) == ("memo_created", f"memo:{out['id']}", "secretary")
    mine = menv.tools.create_memo(menv.button(), body="직접 쓴 메모")
    assert set(mine) == {"id", "title", "area", "pinned", "updated_at"}  # `/actions` 결과에도 본문이 없다
    assert menv.memos.get(mine["id"]).origin == "user"
    long_ctx = menv.chat()
    menv.tools.create_memo(long_ctx, body="가나다라마바사아자차카타파하 스물한 글자를 넘는 제목")
    assert render_confirmations(long_ctx.events, menv.tools.today()) == (
        "✓ 메모를 만들었어요: 가나다라마바사아자차카타파하 스물한 글"  # 원문 기록에도 제목 앞 20자만(6.1)
    )
    run = RunContext(conversation_id=7, run_id=3, activity_channel="scheduler", channel="app")
    assert menv.tools.create_memo(run, body="비서가 먼저") == {"error": "사용자가 부탁한 메모만 만들 수 있어요."}
    assert menv.tools.create_memo(ctx, body="  \n ")["error"] == "메모가 비어 있어요."
    assert menv.tools.create_memo(ctx, body="x" * 20001)["error"] == "메모는 20,000자까지 쓸 수 있어요."
    assert "area는" in menv.tools.create_memo(ctx, body="가", area="money")["error"]


def test_read_memo_redacts(menv):
    secret = "통장 110-123-456789, 비밀번호는 abc123!"
    m = menv.memos.create(f"은행 정보 {secret}\n둘째 줄 " + "가" * 9000, None, "user", NOW)
    got = menv.tools.read_memo(menv.chat(), id=m.id)
    assert "110-123-456789" not in json.dumps(got, ensure_ascii=False) and "abc123" not in got["body"]
    assert "[가림]" in got["title"] and "[가림]" in got["body"]
    assert len(got["body"]) == 8000 and got["truncated"] is True
    found = menv.tools.search_memos(menv.chat(), query="은행 정보")
    (item,) = found["items"]
    assert item["id"] == m.id and "110-123-456789" not in item["title"] + item["preview"]
    assert len(item["preview"]) <= 200 and set(item) == {"id", "title", "preview", "updated_at"}
    assert menv.tools.read_memo(menv.chat(), id=999) == {"error": "없는 메모예요."}
    menv.memos.delete(m.id, NOW)
    assert menv.tools.read_memo(menv.chat(), id=m.id) == {"error": "없는 메모예요."}
    assert menv.tools.search_memos(menv.chat(), query="은행 정보") == {"items": []}


def test_logs_and_activity_have_no_body(menv, caplog):
    body = "아주 길고 개인적인 첫 줄 제목입니다 정말로요\n둘째줄비밀문장XYZ"
    caplog.set_level(logging.DEBUG)
    m = menv.tools.create_memo(menv.chat(), body=body)
    b = menv.button()
    stamp = menv.memos.get(m["id"]).updated_at.isoformat()
    menv.tools.update_memo(b, id=m["id"], body=body + "\n셋째줄비밀QQQ", updated_at=stamp)
    menv.tools.pin_memo(b, id=m["id"])
    menv.tools.unpin_memo(b, id=m["id"])
    menv.tools.search_memos(menv.chat(), query="비밀문장")
    menv.tools.read_memo(menv.chat(), id=m["id"])
    menv.tools.delete_memo(b, id=m["id"])
    rows = menv.rows()
    assert [r["kind"] for r in rows] == ["memo_created", "memo_updated", "memo_pinned", "memo_unpinned", "memo_deleted"]
    title20 = memo_title(body)[:20]
    for r in rows:
        assert r["summary"].endswith(": " + title20), r["summary"]
        assert len(r["summary"].split(": ", 1)[1]) == 20
    dumped = json.dumps(rows, ensure_ascii=False)
    logs = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for secret in ("둘째줄비밀문장XYZ", "셋째줄비밀QQQ", memo_title(body)[20:]):
        assert secret not in dumped and secret not in logs
    logged = [tuple(r) for r in menv.conn.execute("SELECT kind, data_json FROM tool_events_log ORDER BY id")]
    assert [k for k, _ in logged] == [r["kind"] for r in rows]  # 바꾼 것마다 호출 기록(다시 처리할 때 두뇌를 다시 부르지 않게)
    for _, data in logged:
        assert json.loads(data) == {"memo_id": m["id"], "title": title20}
        assert body not in data and "둘째줄비밀문장XYZ" not in data and "셋째줄비밀QQQ" not in data


def test_update_memo_conflict_and_already(menv):
    m = menv.tools.create_memo(menv.button(), body="처음")
    b = menv.button()
    menv.clock.advance(minutes=1)
    got = menv.tools.update_memo(b, id=m["id"], body="둘째", updated_at=m["updated_at"])
    assert "body" not in got and menv.memos.get(m["id"]).body == "둘째" and got["updated_at"] != m["updated_at"]
    stale = menv.tools.update_memo(b, id=m["id"], body="셋째", updated_at=m["updated_at"])
    assert stale == {"error": "다른 곳에서 바뀌었어요. 새로 불러올게요.", "code": "memo_conflict"}
    same = menv.tools.update_memo(b, id=m["id"], body="둘째", updated_at=got["updated_at"])
    assert same["already"] is True
    assert menv.tools.update_memo(b, id=m["id"], body="넷째", updated_at="2026-10-26")["error"].startswith("updated_at")
    assert [r["kind"] for r in menv.rows()] == ["memo_created", "memo_updated"]
    (upd,) = [r for r in menv.rows() if r["kind"] == "memo_updated"]
    assert upd["undo_json"] is None  # 고치기는 되돌릴 수 없다(이전 본문을 활동에 두지 않는다)


def test_update_memo_area_missing_keeps_null_clears(menv):
    b = menv.button()
    m = menv.tools.create_memo(b, body="운동 계획", area="health")
    menv.clock.advance(minutes=1)
    kept = menv.tools.update_memo(b, id=m["id"], body="운동 계획 고침", updated_at=m["updated_at"])
    assert kept["area"] == "health" and menv.memos.get(m["id"]).area is Area.health
    menv.clock.advance(minutes=1)
    cleared = menv.tools.update_memo(b, id=m["id"], body="운동 계획 고침", area=None, updated_at=kept["updated_at"])
    assert cleared["area"] is None and menv.memos.get(m["id"]).area is None


def test_pin_cap_10(menv):
    ids = [menv.tools.create_memo(menv.button(), body=f"메모 {i}")["id"] for i in range(11)]
    for i in ids[:10]:
        assert menv.tools.pin_memo(menv.button(), id=i)["pinned"] is True
    assert menv.tools.pin_memo(menv.button(), id=ids[0])["already"] is True
    out = menv.tools.pin_memo(menv.button(), id=ids[10])
    assert out == {"error": "고정은 10개까지예요. 다른 메모의 고정을 풀면 더 고정할 수 있어요.", "code": "too_many_pinned"}
    menv.tools.unpin_memo(menv.button(), id=ids[0])
    assert menv.tools.pin_memo(menv.button(), id=ids[10])["pinned"] is True


def test_memo_cap_2000(menv):
    at = "2026-10-26T05:00:00.000000+00:00"
    menv.conn.executemany(
        "INSERT INTO memos (body, origin, created_at, updated_at) VALUES (?, 'user', ?, ?)",
        [(f"메모 {i}", at, at) for i in range(1999)],
    )
    assert "error" not in menv.tools.create_memo(menv.button(), body="2000번째")
    out = menv.tools.create_memo(menv.chat(), body="2001번째")
    assert out["code"] == "too_many_memos" and out["error"].startswith("메모는 2,000개까지")
    menv.memos.delete(1, NOW)  # 지운 메모는 세지 않는다
    assert "error" not in menv.tools.create_memo(menv.chat(), body="다시 2000번째")


# --- API 동작, 되돌리기, 하루 한 번 작업 ---


async def _create(env, body="읽을 책\n- [ ] 사피엔스", **extra):
    status, out = await env.action("create_memo", {"body": body, **extra})
    assert status == 200, out
    return out


async def test_update_conflict_409(tmp_path):
    from be_env import BeEnv
    from test_api_actions import _validate

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        made = await _create(env)
        m = made["result"]
        env.clock.advance(minutes=1)
        args = {"id": m["id"], "body": "읽을 책\n- [x] 사피엔스", "area": None, "updated_at": m["updated_at"]}
        status, first = await env.action("update_memo", args)  # 기기 A
        status2, second = await env.action("update_memo", {**args, "body": "읽을 책\n- 총균쇠"})  # 옛 값의 기기 B
        stored = env.parts.memos.get(m["id"]).body

    assert made["confirmation"] == "✓ 메모를 만들었어요: 읽을 책" and "body" not in m
    assert m["updated_at"].endswith("Z")  # API 경계에서 UTC
    assert status == 200 and "body" not in first["result"] and "undo_id" not in first
    assert status2 == 409
    _validate("Error", second)
    assert second == {"error": {"code": "memo_conflict", "message": "다른 곳에서 바뀌었어요. 새로 불러올게요."}}
    assert stored == "읽을 책\n- [x] 사피엔스"


async def test_caps_are_422_codes(tmp_path):
    from be_env import BeEnv
    from test_api_actions import _validate

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        ids = [(await _create(env, f"메모 {i}"))["result"]["id"] for i in range(11)]
        for i in ids[:10]:
            await env.action("pin_memo", {"id": i})
        status, body = await env.action("pin_memo", {"id": ids[10]})
    assert status == 422
    _validate("ActionRejected", body)
    assert body["error"]["code"] == "too_many_pinned"


async def test_delete_undo_restores(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        m = (await _create(env))["result"]
        status, deleted = await env.action("delete_memo", {"id": m["id"]})
        gone = await env.get(f"/memos/{m['id']}")
        listed = await (await env.get("/memos?q=사피")).json()
        resp = await env.post(f"/activity/{deleted['undo_id']}/undo", json={"client_msg_id": "u-1"})
        undone = await resp.json()
        back = await (await env.get(f"/memos/{m['id']}")).json()
        found = await (await env.get("/memos?q=사피엔스")).json()

    assert status == 200 and deleted["confirmation"] == "✓ 메모를 지웠어요: 읽을 책"
    assert gone.status == 404 and listed["items"] == []
    assert resp.status == 200 and undone["status"] == "undone"
    assert undone["confirmation"] == "↩ 되돌림: 읽을 책 메모를 지웠어요"
    assert back["body"] == "읽을 책\n- [ ] 사피엔스" and [x["id"] for x in found["items"]] == [m["id"]]


async def test_create_undo_deletes(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        made = await _create(env)
        resp = await env.post(f"/activity/{made['undo_id']}/undo", json={"client_msg_id": "u-2"})
        gone = await env.get(f"/memos/{made['result']['id']}")
    assert resp.status == 200 and gone.status == 404


def test_export_memos_md(tmp_path, conn, memos):
    from my_planner.store.exports import export_memos

    a = memos.create("읽을 책\n- [ ] 사피엔스", Area.learning, "chat", NOW)
    b = memos.create("장보기\n- 우유", None, "user", NOW + timedelta(minutes=1))
    c = memos.create("지운 메모", None, "user", NOW)
    memos.pin(a.id, NOW)
    memos.delete(c.id, NOW)
    path = tmp_path / "data" / "exports" / "memos.md"
    export_memos(memos, path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 메모\n")
    assert text.index("## 고정됨") < text.index(f"### #{a.id} 읽을 책 · 배움 · 비서") < text.index("## 메모\n")
    assert text.index("## 메모\n") < text.index(f"### #{b.id} 장보기") and "- [ ] 사피엔스" in text and "- 우유" in text
    assert "지운 메모" not in text
    export_memos(memos, path)
    assert path.read_text(encoding="utf-8") == text  # 같은 데이터면 같은 파일


async def test_daily_job_registered(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        jobs = {getattr(j, "__name__", ""): j for j in env.parts.runner._daily}
        old = (await _create(env, "오래전에 지운 것"))["result"]["id"]
        live = (await _create(env, "남는 것\n본문"))["result"]["id"]
        await env.action("delete_memo", {"id": old})
        env.clock.advance(timedelta(days=30, minutes=1))
        jobs["memos_daily"](env.parts.tools.today())
        rows = [r[0] for r in env.conn.execute("SELECT id FROM memos")]
        text = (env.settings.paths.data_dir / "exports" / "memos.md").read_text(encoding="utf-8")
    assert "memos_daily" in jobs
    assert rows == [live] and f"### #{live} 남는 것" in text and "오래전에" not in text


async def _undo(env, activity_id):
    resp = await env.post(f"/activity/{activity_id}/undo", json={"client_msg_id": f"u-{activity_id}"})
    return resp.status, await resp.json()


async def _pin_new(env, n):
    ids = [(await _create(env, f"고정용 {i}"))["result"]["id"] for i in range(n)]
    for i in ids:
        status, _ = await env.action("pin_memo", {"id": i})
        assert status == 200
    return ids


async def test_undo_delete_of_pinned_memo_restores_unpinned_when_10_pinned(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        m = (await _create(env))["result"]["id"]
        await env.action("pin_memo", {"id": m})
        _, deleted = await env.action("delete_memo", {"id": m})
        await _pin_new(env, 10)
        status, body = await _undo(env, deleted["undo_id"])
        back = env.parts.memos.get(m)
        pinned = env.parts.memos.count_pinned()
    assert status == 200 and body["status"] == "undone"
    assert back is not None and back.pinned is False and pinned == 10


async def test_undo_delete_of_pinned_memo_keeps_pin_when_room(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        m = (await _create(env))["result"]["id"]
        await env.action("pin_memo", {"id": m})
        _, deleted = await env.action("delete_memo", {"id": m})
        status, _ = await _undo(env, deleted["undo_id"])
        back = env.parts.memos.get(m)
    assert status == 200 and back.pinned is True


async def test_undo_unpin_refused_when_10_pinned(tmp_path):
    from be_env import BeEnv
    from test_api_actions import _validate

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        ids = await _pin_new(env, 10)
        _, unpinned = await env.action("unpin_memo", {"id": ids[0]})
        await _pin_new(env, 1)
        status, body = await _undo(env, unpinned["undo_id"])
        still = env.parts.memos.get(ids[0]).pinned
        row = env.conn.execute("SELECT undone_at FROM activity WHERE id = ?", (unpinned["undo_id"],)).fetchone()
    assert status == 422
    _validate("Error", body)
    assert body["error"] == {"code": "too_many_pinned", "message": "고정은 10개까지예요. 다른 메모의 고정을 풀면 더 고정할 수 있어요."}
    assert still is False and row["undone_at"] is None


async def test_undo_delete_refused_when_2000_alive(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        m = (await _create(env))["result"]["id"]
        _, deleted = await env.action("delete_memo", {"id": m})
        at = "2026-10-26T05:00:00.000000+00:00"
        env.conn.executemany(
            "INSERT INTO memos (body, origin, created_at, updated_at) VALUES (?, 'user', ?, ?)",
            [(f"메모 {i}", at, at) for i in range(2000)],
        )
        env.conn.commit()
        status, body = await _undo(env, deleted["undo_id"])
        gone = env.parts.memos.get(m)
    assert status == 422 and body["error"]["code"] == "too_many_memos"
    assert body["error"]["message"] == "메모는 2,000개까지 둘 수 있어요. 안 쓰는 메모를 지우면 새로 만들 수 있어요."
    assert gone is None


async def test_reprocessing_same_inbound_leaves_one_memo(tmp_path, conn, state):
    """두뇌 호출 도중 멈춘 뒤 다시 처리: 호출 기록이 있어 두뇌를 다시 부르지 않고 메모는 하나(스펙 5.4-3)."""
    import asyncio

    from test_dispatcher_messages import Env
    from test_inbound_recovery import START, _kill, _receive

    from my_planner.harness.dispatcher import FALLBACK_REPLY
    from my_planner.loop.runner import resubmit_inbound

    make = ("create_memo", {"body": "읽을 책\n- [ ] 사피엔스"})
    first = Env(tmp_path, conn, state, script=[FakeTurn([make], "", hang=True)], start=START, with_tools=True)
    first.tools.memos = MemosRepo(conn, first.clock)
    first.dispatcher.start()
    await _receive(first, state, 51, "읽을 책 사피엔스 메모해줘")
    while not first.brain.calls:
        await asyncio.sleep(0)
    await _kill(first)

    second = Env(tmp_path, conn, state, script=[], start=START + timedelta(minutes=5), with_tools=True)
    second.tools.memos = MemosRepo(conn, second.clock)
    assert resubmit_inbound(state, second.dispatcher) == 1
    await second.process()

    assert second.brain.calls == []
    assert conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 1
    assert [o.text for o in second.sender.sent] == [f"{FALLBACK_REPLY}\n\n✓ 메모를 만들었어요: 읽을 책"]


def test_memo_copy_has_no_banned_words():
    """10장 금지어 검사: 이 티켓이 쓴 메모 문구 전부(확인 문구, 상한, 오류)."""
    from my_planner.store.repos.memos import UNTITLED
    from my_planner.tools import memos as mt
    from my_planner.tools.confirmations import _MEMO_LINES
    from my_planner.tools.ui import banned_words

    copy = [*_MEMO_LINES.values(), UNTITLED, *(v for k, v in vars(mt).items() if k.startswith("MSG_"))]
    assert len(copy) == 5 + 1 + 12
    words = banned_words()
    assert [(c, w) for c in copy for w in words if w in c] == []

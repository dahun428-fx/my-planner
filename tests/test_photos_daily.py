"""사진의 하루 한 번 작업 (SP10 스펙 5.6 1~5번, 5.2 파일 지우기, 5.7 롤백 뒤 고아, 14장 `photos.cleanup`, 12장
`test_photos_daily.py`, Review Focus 5).

하루 한 번 작업 `memos_daily`(SP9 6.1)가 지운 메모를 먼저 완전히 지우고, 같은 실행에서 사진을 정리한다: 그래서
메모와 함께 CASCADE로 연결이 풀린 사진도 같은 날 지워진다. 파일은 행 지우기가 커밋된 뒤에만 지운다.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

import pytest
from be_env import BeEnv
from fakes import FakeTurn
from test_chat_photos import _conv_of, _parts, _photo, _send
from test_dispatcher_messages import kst

from my_planner.config import PhotosConfig

MON_1400 = kst(2026, 10, 26, 14, 0)


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_1400) as e:
        yield e


def _daily(env) -> dict:
    """하루 한 번 작업 중 메모·사진 정리(`memos_daily`)만 부른다. 결과(개수)를 돌려준다."""
    res = env.parts.dispatcher.apply_action(_req())
    assert res.status == "applied", res.body
    return res.body["result"]


def _req():
    from my_planner.loop.runner import _scheduler

    return _scheduler("memos_daily", {})


def _row(env, pid):
    return env.parts.tools.photos.get(env.conn, pid)


def _files(env, pid) -> list[bool]:
    """그 사진 행의 큰 사진·작은 사진 파일이 있는가. 행이 없으면 지울 때 기억한 경로로 본다."""
    p = _row(env, pid)
    root = env.parts.tools.photo_files.root
    return [(root / p.path).exists(), (root / p.thumb_path).exists()]


def _paths(env, pid) -> tuple[str, str]:
    p = _row(env, pid)
    return p.path, p.thumb_path


def _exists(env, *rels: str) -> list[bool]:
    root = env.parts.tools.photo_files.root
    return [(root / r).exists() for r in rels]


async def _memo_with(env, *photo_ids) -> int:
    status, made = await env.action("create_memo", {"body": "사진 메모", "photo_ids": list(photo_ids)})
    assert status == 200, made
    return made["result"]["id"]


def _age(env, rel: str, days: float) -> None:
    """파일 고친 시각을 지금(가짜 시계)보다 `days`일 전으로."""
    t = (env.clock.now() - timedelta(days=days)).timestamp()
    os.utime(env.parts.tools.photo_files.root / rel, (t, t))


def _orphan(env, rel: str, days: float) -> None:
    p = env.parts.tools.photo_files.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xff\xd8 orphan \xff\xd9")
    _age(env, rel, days)


# --- 5.6 1번: 완전히 지울 사진 (Review Focus 5) ---


async def test_chat_photo_on_memo_survives_conversation_delete(env):
    """메모에 붙은 채팅 사진은 대화를 지워도 남고, 메모가 30일 뒤 완전히 지워질 때 같은 실행에서 함께 지워진다."""
    a, b = await _photo(env), await _photo(env)
    env.brain.script.append(FakeTurn([("create_memo", {"body": "남길 메모", "photo_ids": [a]})], "만들었어요."))
    _, chunks = await _send(env, _parts(None, a, b))
    resp = await env.delete(f"/conversations/{_conv_of(chunks)}")
    assert resp.status == 204
    a_paths, b_paths = _paths(env, a), _paths(env, b)
    env.clock.advance(timedelta(days=31))
    first = _daily(env)
    kept_a, gone_b = _row(env, a), _row(env, b)
    a_files_day1, b_files_day1 = _exists(env, *a_paths), _exists(env, *b_paths)

    memo = env.conn.execute("SELECT memo_id FROM memo_photos WHERE photo_id = ?", (a,)).fetchone()[0]
    await env.action("delete_memo", {"id": memo})
    env.clock.advance(timedelta(days=30, minutes=1))
    second = _daily(env)
    assert kept_a is not None and a_files_day1 == [True, True]
    assert gone_b is None and b_files_day1 == [False, False]  # 대화만 있던 사진은 30일 지나 지운다
    assert first["photos_purged"] == 1
    # 메모 완전 지우기(CASCADE) 뒤 같은 실행에서 사진 행과 파일 둘이 지워진다
    assert second["purged"] == 1 and second["photos_purged"] == 1
    assert _row(env, a) is None and _exists(env, *a_paths) == [False, False]


async def test_unlinked_new_photo_not_purged(env):
    """아직 어디에도 붙지 않은 새 사진(메모 쓰기 중, 채팅 연결 직전)은 지우지 않는다."""
    memo_new = await _photo(env, origin="memo")
    chat_new = await _photo(env, origin="chat")
    env.clock.advance(timedelta(days=29, hours=23))
    out = _daily(env)
    assert out["photos_purged"] == 0
    assert _row(env, memo_new) is not None and _files(env, memo_new) == [True, True]
    assert _row(env, chat_new) is not None and _files(env, chat_new) == [True, True]


async def test_photo_without_links_purged_after_30_days(env):
    """연결이 없고 `created_at`과 `unlinked_at`이 모두 30일보다 오래된 사진은 행과 파일 둘을 지운다."""
    pid = await _photo(env, origin="memo")
    paths = _paths(env, pid)
    env.clock.advance(timedelta(days=30, minutes=1))
    out = _daily(env)
    assert out["photos_purged"] == 1
    assert _row(env, pid) is None and _exists(env, *paths) == [False, False]


async def test_detached_photo_kept_30_days(env):
    """메모에서 뺀 사진은 되돌리기를 기다리므로 `unlinked_at`에서 30일을 센다(`created_at`이 오래돼도)."""
    pid = await _photo(env, origin="memo")
    memo = await _memo_with(env, pid)
    env.clock.advance(timedelta(days=40))
    status, out = await env.action("detach_photo", {"memo_id": memo, "photo_id": pid})
    assert status == 200, out
    env.clock.advance(timedelta(days=29, hours=23))
    day29 = _daily(env)
    still = _row(env, pid)
    paths = _paths(env, pid)
    env.clock.advance(timedelta(hours=2))
    day30 = _daily(env)
    assert day29["photos_purged"] == 0 and still is not None
    assert day30["photos_purged"] == 1 and _row(env, pid) is None and _exists(env, *paths) == [False, False]


async def test_photo_on_soft_deleted_memo_kept_until_memo_purge(env):
    """지운 메모(소프트 삭제)의 사진은 연결이 그대로라 남는다. 메모를 되돌리면 그대로 보인다(5.1)."""
    pid = await _photo(env, origin="memo")
    memo = await _memo_with(env, pid)
    await env.action("delete_memo", {"id": memo})
    env.clock.advance(timedelta(days=29))
    out = _daily(env)
    assert out["purged"] == 0 and out["photos_purged"] == 0 and _row(env, pid) is not None


async def test_files_removed_only_after_commit(env, monkeypatch):
    """사진 정리가 중간에 실패하면 사진 쓰기만 되돌려지고(파일은 커밋 뒤에만 지운다) 메모 지우기·내보내기는 그대로다."""
    pid = await _photo(env, origin="memo")
    paths = _paths(env, pid)
    _, made = await env.action("create_memo", {"body": "지울 메모"})
    await env.action("delete_memo", {"id": made["result"]["id"]})
    env.clock.advance(timedelta(days=31))
    repo = env.parts.tools.photos

    def boom(*a, **k):
        raise RuntimeError("after purge")

    monkeypatch.setattr(repo, "file_rows", boom)  # 행을 지운 뒤, 커밋 전에 실패
    out = _daily(env)
    assert out["purged"] == 1 and out["exported"] is True and out["photos_failed"] is True
    assert env.conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 0
    assert _row(env, pid) is not None and _exists(env, *paths) == [True, True]


async def test_remove_permission_error_retried_next_day(env, monkeypatch):
    """파일 잠김(`PermissionError`): 세 번 다시 해 보고 안 되면 남겨 두고, 다음 날 고아 파일로 다시 지운다(5.2)."""
    from pathlib import Path

    import my_planner.store.photos as photos_mod

    monkeypatch.setattr(photos_mod, "_RETRY_SLEEP", 0)
    pid = await _photo(env, origin="memo")
    paths = _paths(env, pid)
    root = env.parts.tools.photo_files.root
    locked = (root / paths[0]).resolve()
    tries = []
    real_unlink = Path.unlink

    def unlink(self, missing_ok=False):
        if Path(self).resolve() == locked:
            tries.append(1)
            raise PermissionError(13, "locked")
        return real_unlink(self, missing_ok=missing_ok)

    env.clock.advance(timedelta(days=31))
    monkeypatch.setattr(Path, "unlink", unlink)
    day1 = _daily(env)
    left = _exists(env, *paths)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    env.clock.advance(timedelta(days=1))
    _daily(env)
    assert day1["photos_purged"] == 1 and _row(env, pid) is None
    assert len(tries) == 3 and left == [True, False]  # 작은 사진은 지웠다
    assert _exists(env, *paths) == [False, False]  # 다음 날 고아로 지웠다


# --- 5.6 2번: 고아 파일, 5.7 롤백 뒤 ---


async def test_orphan_files_deleted_after_7_days(env):
    pid = await _photo(env, origin="memo")
    await _memo_with(env, pid)
    live = _paths(env, pid)
    _age(env, live[0], 100)  # 행이 있는 파일은 오래돼도 남는다
    _orphan(env, "2026/10/900-deadbeef.jpg", 8)
    _orphan(env, "2026/10/901-deadbeef.jpg", 6)  # 7일이 안 됐다
    _orphan(env, ".incoming/abc.tmp", 8)  # 쓰다 실패한 tmp
    _orphan(env, ".incoming/def-t.tmp", 1)  # 지금 올리는 중일 수 있다
    out = _daily(env)
    assert _exists(env, *live) == [True, True]
    assert _exists(env, "2026/10/900-deadbeef.jpg", "2026/10/901-deadbeef.jpg") == [False, True]
    assert _exists(env, ".incoming/abc.tmp", ".incoming/def-t.tmp") == [False, True]
    assert out["photos_purged"] == 0


async def test_rollback_leftover_files_deleted_after_7_days(env):
    """배포 롤백으로 행이 사라지면 파일만 남는다(5.7): 7일이 지나야 고아로 지운다."""
    pid = await _photo(env, origin="memo")
    paths = _paths(env, pid)
    env.conn.execute("DELETE FROM photos WHERE id = ?", (pid,))  # 백업으로 돌아간 DB에는 이 행이 없다
    env.conn.commit()
    for rel in paths:
        _age(env, rel, 6)
    _daily(env)
    day6 = _exists(env, *paths)
    env.clock.advance(timedelta(days=1, minutes=1))
    _daily(env)
    assert day6 == [True, True] and _exists(env, *paths) == [False, False]


# --- 5.6 3번: 없는 파일 ---


async def test_missing_file_logs_photo_missing(env, caplog):
    pid = await _photo(env, origin="memo")
    await _memo_with(env, pid)
    ok = await _photo(env, origin="memo")
    await _memo_with(env, ok)
    root = env.parts.tools.photo_files.root
    (root / _row(env, pid).thumb_path).unlink()
    caplog.set_level(logging.INFO, logger="my_planner")
    out = _daily(env)
    missing = [r for r in caplog.records if r.getMessage() == "photo_missing"]
    assert [r.photo_id for r in missing] == [pid] and missing[0].levelno == logging.WARNING
    assert out["photos_missing"] == 1
    assert _row(env, pid) is not None  # 행은 그대로(파일이 돌아오면 다시 보인다)


# --- 5.6 5번: 내보내기 ---


async def test_memos_export_has_photo_lines(env):
    a, b = await _photo(env, origin="memo"), await _photo(env, origin="memo")
    memo = await _memo_with(env, a, b)
    status, _ = await env.action("create_memo", {"body": "사진 없는 메모"})
    assert status == 200
    _daily(env)
    text = (env.settings.paths.data_dir / "exports" / "memos.md").read_text(encoding="utf-8")
    pa, pb = _paths(env, a)[0], _paths(env, b)[0]
    start = text.index(f"### #{memo} ")
    nxt = text.find("### ", start + 4)
    block = text[start:nxt if nxt != -1 else len(text)]
    assert f"![사진](../photos/{pa})\n![사진](../photos/{pb})" in block  # 위치 순
    assert "-t.jpg" not in text  # 작은 사진은 넣지 않는다
    assert text.count("![사진]") == 2


# --- 14장: photos.cleanup = false ---


async def test_cleanup_off_keeps_photos_and_orphans(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_1400, overrides={"photos": PhotosConfig(cleanup=False)}) as env:
        pid = await _photo(env, origin="memo")
        paths = _paths(env, pid)
        _orphan(env, "2026/10/900-deadbeef.jpg", 30)
        _orphan(env, ".incoming/abc.tmp", 30)
        env.clock.advance(timedelta(days=31))
        out = _daily(env)
        assert _row(env, pid) is not None and _exists(env, *paths) == [True, True]
        assert _exists(env, "2026/10/900-deadbeef.jpg", ".incoming/abc.tmp") == [True, True]
        assert out["photos_purged"] == 0 and out["photos_cleanup"] is False


async def test_cleanup_off_after_tables_dropped(tmp_path):
    """14장 되돌림: 020 표를 지우고 `cleanup = false`면 하루 작업은 사진 없이 메모만 내보낸다(오류 없음)."""
    async with BeEnv.start(tmp_path, start=MON_1400, overrides={"photos": PhotosConfig(cleanup=False)}) as env:
        _, made = await env.action("create_memo", {"body": "남는 메모"})
        for table in ("memo_photos", "message_photos", "photos"):
            env.conn.execute(f"DROP TABLE {table}")
        env.conn.commit()
        out = _daily(env)
        text = (env.settings.paths.data_dir / "exports" / "memos.md").read_text(encoding="utf-8")
    assert out["exported"] is True and "photos_failed" not in out and out["photos_cleanup"] is False
    assert f"### #{made['result']['id']} 남는 메모" in text and "![사진]" not in text


# --- 6장: 로그에는 id와 개수만 ---


async def test_daily_logs_have_ids_and_counts_only(env, caplog):
    pid = await _photo(env, origin="memo")
    gone = await _photo(env, origin="memo")
    memo = await _memo_with(env, pid)
    env.parts.tools.photos.set_read_text(env.conn, pid, "영수증 비밀 합계 12,000원")
    root = env.parts.tools.photo_files.root
    (root / _row(env, pid).path).unlink()  # photo_missing
    _orphan(env, "2026/10/900-deadbeef.jpg", 8)
    env.clock.advance(timedelta(days=31))
    caplog.set_level(logging.DEBUG)
    jobs = {getattr(j, "__name__", ""): j for j in env.parts.runner._daily}
    jobs["memos_daily"](env.parts.tools.today())
    std = set(vars(logging.makeLogRecord({})))  # 원본 파일 위치 같은 기본 속성은 빼고 메시지와 덧붙인 값만
    dumped = json.dumps([{"msg": r.getMessage(), **{k: v for k, v in vars(r).items() if k not in std}}
                         for r in caplog.records], ensure_ascii=False, default=str)
    activity = json.dumps([dict(r) for r in env.conn.execute("SELECT * FROM activity")], ensure_ascii=False)
    assert _row(env, gone) is None and memo
    for leak in (".jpg", ".tmp", "photos/", "deadbeef", "영수증 비밀", str(root)):
        assert leak not in dumped, leak
        assert leak not in activity, leak
    daily = next(r for r in caplog.records if r.getMessage() == "memos_daily")
    assert daily.photos_purged == 1 and daily.photos_missing == 1

"""사진 저장 (SP10 스펙 5.1·5.2·5.3 `/actions`·5.7, 12장 `test_photos_store.py`): 020, `PhotoFiles`, `PhotosRepo`,
즉시 갈래 `store_photo`·`attach_photo`·`detach_photo`, `create_memo(photo_ids)`. 사진 바이트는 꾸며 낸 JPEG 머리다."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest
from test_dispatcher_messages import kst

from my_planner.store.db import (
    after_commit,
    after_rollback,
    migrate,
    open_db,
    transaction,
)
from my_planner.store.photos import (
    PhotoFileConflict,
    PhotoFiles,
    PhotoNotJpeg,
    PhotoTooLarge,
    PhotoUnreadable,
    check_photo,
)
from my_planner.store.repos.memos import MemosRepo
from my_planner.store.repos.photos import PhotoInUse, PhotosRepo, TooManyPhotos
from my_planner.tools.actions import ActionRequest

NOW = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)  # 10/26(월) 14:00 KST
TZ = "Asia/Seoul"
BOUNDARY = time(4, 0)
MON_1400 = kst(2026, 10, 26, 14, 0)


def jpeg(w: int = 640, h: int = 480, pad: int = 16, *, sof: int = 0xC0, eoi: bool = True) -> bytes:
    """SOI, APP0, SOFn(크기), SOS, 채움, EOI만 있는 JPEG 머리."""
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sofn = bytes([0xFF, sof]) + b"\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + (
        b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    sos = b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    return b"\xff\xd8" + app0 + sofn + sos + b"\x5a" * pad + (b"\xff\xd9" if eoi else b"")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def files(tmp_path):
    return PhotoFiles(tmp_path / "data" / "photos")


@pytest.fixture
def repo():
    return PhotosRepo(TZ, BOUNDARY)


def _insert(conn, repo, n=1, origin="memo", now=NOW):
    out = []
    for _ in range(n):
        i = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        out.append(repo.insert(
            conn, sha256=f"{i:064x}", path=f"2026/10/{i}-x.jpg", thumb_path=f"2026/10/{i}-x-t.jpg",
            bytes=100, width=10, height=10, origin=origin, now=now,
        ))
    return out


def _memo(conn, body="메모"):
    return MemosRepo(conn, None).create(body, None, "user", NOW)  # type: ignore[arg-type]


def _files_under(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


# --- 020 (5.1) ---


def test_020_tables_checks_and_photo_reads(tmp_path):
    conn = open_db(tmp_path / "planner.db")
    assert migrate(conn, upto=19) == 19
    conn.execute("INSERT INTO usage_state (date) VALUES ('2026-10-25')")
    conn.commit()
    assert migrate(conn) == 20
    assert conn.execute("SELECT photo_reads FROM usage_state").fetchone()[0] == 0  # 019까지 있던 행도 0
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"photos", "memo_photos", "message_photos", "idx_message_photos_conv"} <= names
    cols = ("sha256", "path", "thumb_path", "bytes", "width", "height", "origin")
    ins = f"INSERT INTO photos ({', '.join(cols)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'a')"
    good = ("a" * 64, "p.jpg", "p-t.jpg", 5_000_000, 2048, 2048, "memo")
    bad = {"sha256": "a" * 63, "bytes": 5_000_001, "width": 2049, "height": 0, "origin": "brain"}
    for i, (col, value) in enumerate([*bad.items(), ("bytes", 0), ("width", 0)]):
        row = dict(zip(cols, good, strict=True), path=f"{i}.jpg", thumb_path=f"{i}-t.jpg")
        row[col] = value
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ins, tuple(row[c] for c in cols))
    conn.execute(ins, good)
    with pytest.raises(sqlite3.IntegrityError):  # 경로는 겹치지 않는다
        conn.execute(ins, good)
    with pytest.raises(sqlite3.IntegrityError):  # 사진 읽기 결과 8,000자
        conn.execute("UPDATE photos SET read_text = ?", ("가" * 8001,))
    conn.close()


# --- JPEG 머리 (5.2) ---


def test_020_rebuilds_api_idempotency_with_photos(tmp_path):
    """5.1 끝·14장: CHECK에 'photos'를 더하려고 표를 다시 만든다. 열·행은 그대로, 다른 경로도 그대로, 엉뚱한 값은 거절."""
    conn = open_db(tmp_path / "planner.db")
    assert migrate(conn, upto=19) == 19
    ins = (
        "INSERT INTO api_idempotency (client_msg_id, endpoint, status_code, response_json, conversation_id, at) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    old = [
        ("c-1", "chat", 200, '{"conversation_id": 3, "reply_text": "네"}', 3, "2026-10-26T01:00:00+00:00"),
        ("a-1", "actions", 422, '{"status": "rejected"}', None, "2026-10-26T02:00:00+00:00"),
        ("u-1", "undo", 200, None, None, "2026-10-26T03:00:00+00:00"),
    ]
    conn.executemany(ins, old)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # 019까지는 'photos'를 받지 않았다
        conn.execute(ins, ("p-0", "photos", 201, None, None, "a"))
    conn.rollback()
    cols_before = [tuple(r) for r in conn.execute("PRAGMA table_info(api_idempotency)")]
    assert migrate(conn) == 20
    rows = [tuple(r) for r in conn.execute("SELECT * FROM api_idempotency ORDER BY at")]
    cols_after = [tuple(r) for r in conn.execute("PRAGMA table_info(api_idempotency)")]
    conn.execute(ins, ("p-1", "photos", 201, '{"id": 1}', None, "b"))
    for i, ep in enumerate(("chat", "actions", "undo")):
        conn.execute(ins, (f"n-{i}", ep, 200, None, None, "c"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("x-1", "bogus", 200, None, None, "d"))
    with pytest.raises(sqlite3.IntegrityError):  # client_msg_id는 그대로 기본 키
        conn.execute(ins, ("c-1", "chat", 200, None, None, "e"))
    assert rows == old and cols_after == cols_before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "api_idempotency_new" not in names and "api_idempotency_old" not in names


def test_jpeg_size_from_sof(files):
    assert files.jpeg_size(jpeg(640, 480)) == (640, 480)
    assert files.jpeg_size(jpeg(1536, 2048, sof=0xC2)) == (1536, 2048)  # 프로그레시브(SOF2)


def test_png_not_jpeg_and_missing_eoi_unreadable(files):
    with pytest.raises(PhotoNotJpeg):
        files.jpeg_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    with pytest.raises(PhotoNotJpeg):
        files.jpeg_size(b"")
    with pytest.raises(PhotoUnreadable):
        files.jpeg_size(jpeg(eoi=False))  # 끝(EOI)이 없다: 올리다 잘렸다
    with pytest.raises(PhotoUnreadable):
        files.jpeg_size(b"\xff\xd8\xff\xd9")  # 크기(SOFn)가 없다
    with pytest.raises(PhotoUnreadable):
        files.jpeg_size(jpeg(0, 480))


def test_check_photo_limits():
    assert check_photo(jpeg(2048, 1536)) == (2048, 1536)
    with pytest.raises(PhotoTooLarge):
        check_photo(jpeg(2049, 100))  # 긴 변 2,049 → 413
    with pytest.raises(PhotoTooLarge):
        check_photo(jpeg(100, 2049))
    big = jpeg(100, 100, pad=5_000_001 - len(jpeg(100, 100, pad=0)))
    assert len(big) == 5_000_001
    with pytest.raises(PhotoTooLarge):
        check_photo(big)  # 5,000,001바이트 → 413
    with pytest.raises(PhotoTooLarge):
        check_photo(jpeg(100, 100, pad=256 * 1024), max_bytes=256 * 1024)  # 작은 사진 256 KiB


# --- 파일 (5.2) ---


def test_write_incoming_then_place_path_rule(files):
    image, thumb = jpeg(), jpeg(80, 60)
    tmp_img, tmp_thumb = files.write_incoming(image, thumb)
    assert tmp_img.parent == files.root / ".incoming" and tmp_img.name.endswith(".tmp")
    assert tmp_thumb.name == tmp_img.name.replace(".tmp", "-t.tmp")
    assert tmp_img.read_bytes() == image and tmp_thumb.read_bytes() == thumb
    rel = files.place((tmp_img, tmp_thumb), 12, sha(image), datetime(2026, 11, 1).date())
    h8 = sha(image)[:8]
    assert rel == (f"2026/11/12-{h8}.jpg", f"2026/11/12-{h8}-t.jpg")
    assert (files.root / rel[0]).read_bytes() == image and (files.root / rel[1]).read_bytes() == thumb
    assert not tmp_img.exists() and not tmp_thumb.exists()


def test_place_same_sha_reuses_existing_file(files):
    image = jpeg()
    first = files.place(files.write_incoming(image, jpeg(80, 60)), 12, sha(image), NOW.date())
    again = files.write_incoming(image, jpeg(81, 60))  # 롤백 뒤 같은 id, 같은 사진(5.7)
    assert files.place(again, 12, sha(image), NOW.date()) == first
    assert not again[0].exists() and not again[1].exists()  # tmp는 지운다
    assert files.jpeg_size((files.root / first[1]).read_bytes()) == (80, 60)  # 있던 파일 그대로


def test_place_different_sha_fails(files):
    a, b = jpeg(pad=1), jpeg(pad=2)
    first = files.place(files.write_incoming(a, jpeg(80, 60)), 12, sha(a), NOW.date())
    target = files.root / first[0]
    target.write_bytes(b)  # 같은 이름, 다른 내용(sha 앞 8자가 같은 다른 사진)
    tmp = files.write_incoming(a, jpeg(80, 60))
    with pytest.raises(PhotoFileConflict):
        files.place(tmp, 12, sha(a), NOW.date())
    assert target.read_bytes() == b  # 덮어쓰지 않는다
    assert not tmp[0].exists() and not tmp[1].exists()


def test_failed_write_leaves_no_tmp(files, monkeypatch):
    def boom(fd):
        raise OSError("disk")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        files.write_incoming(jpeg(), jpeg(80, 60))
    assert _files_under(files.root) == []


def test_remove_retries_permission_error(files, monkeypatch):
    image = jpeg()
    rel = files.place(files.write_incoming(image, jpeg(80, 60)), 1, sha(image), NOW.date())
    real = Path.unlink
    calls = []

    def flaky(self, missing_ok=False):
        calls.append(self.name)
        if len(calls) <= 2:
            raise PermissionError("locked")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky)
    monkeypatch.setattr("my_planner.store.photos._RETRY_SLEEP", 0)
    files.remove(rel[0])
    assert not (files.root / rel[0]).exists() and len(calls) == 3


def test_after_rollback_runs_only_on_rollback(conn):
    ran = []
    with transaction(conn):
        after_rollback(conn, lambda: ran.append("commit"))
    assert ran == []
    with pytest.raises(RuntimeError), transaction(conn):
        after_rollback(conn, lambda: ran.append("outer"))
        raise RuntimeError
    assert ran == ["outer"]
    with transaction(conn):
        try:
            with transaction(conn):
                after_rollback(conn, lambda: ran.append("inner"))
                raise RuntimeError
        except RuntimeError:
            pass
        with transaction(conn):
            after_rollback(conn, lambda: ran.append("kept"))  # 안쪽이 풀리면 바깥이 커밋되니 부르지 않는다
    assert ran == ["outer", "inner"]
    with pytest.raises(RuntimeError), transaction(conn):
        with transaction(conn):
            after_rollback(conn, lambda: ran.append("released"))  # 풀린 안쪽의 일은 바깥이 롤백되면 부른다
        raise RuntimeError
    assert ran == ["outer", "inner", "released"]


def test_after_callback_failures_logged_by_kind(conn, caplog):
    """커밋 뒤 일의 실패는 `after_commit_error`, 롤백 때 일의 실패는 `after_rollback_error`. 나머지 일은 그대로 부른다."""
    ran = []

    def boom() -> None:
        raise OSError("locked")

    with caplog.at_level("WARNING", logger="my_planner.store.db"), pytest.raises(RuntimeError), transaction(conn):
        after_rollback(conn, boom)
        after_rollback(conn, lambda: ran.append("rb"))
        raise RuntimeError
    rollback_msgs = [r.getMessage() for r in caplog.records]
    caplog.clear()
    with caplog.at_level("WARNING", logger="my_planner.store.db"), transaction(conn):
        after_commit(conn, boom)
        after_commit(conn, lambda: ran.append("ac"))
    commit_msgs = [r.getMessage() for r in caplog.records]
    assert rollback_msgs == ["after_rollback_error"] and commit_msgs == ["after_commit_error"]
    assert ran == ["rb", "ac"]


# --- 저장소 (5.1) ---


def test_positions_smallest_free(conn, repo):
    m = _memo(conn)
    photos = _insert(conn, repo, 11)
    assert [repo.attach(conn, m.id, p.id) for p in photos[:10]] == list(range(10))
    with pytest.raises(TooManyPhotos):
        repo.attach(conn, m.id, photos[10].id)
    repo.detach(conn, m.id, photos[3].id, NOW)
    assert repo.get(conn, photos[3].id).unlinked_at == NOW
    assert repo.attach(conn, m.id, photos[10].id) == 3  # 0~9 찬 상태에서 3을 빼고 붙이면 3
    assert [p.id for p in repo.for_memo(conn, m.id)][3] == photos[10].id


def test_same_photo_two_memos_rejected(conn, repo):
    a, b = _memo(conn, "가"), _memo(conn, "나")
    (p,) = _insert(conn, repo)
    repo.attach(conn, a.id, p.id)
    with pytest.raises(PhotoInUse):
        repo.attach(conn, b.id, p.id)
    assert repo.attach(conn, a.id, p.id) == 0  # 같은 메모에 다시 붙이면 그 자리


def test_is_live(conn, repo):
    memos = MemosRepo(conn, None)  # type: ignore[arg-type]
    m = _memo(conn)
    a, b, c = _insert(conn, repo, 3)
    assert not repo.is_live(conn, a.id)  # 아직 어디에도 붙지 않았다
    repo.attach(conn, m.id, a.id)
    assert repo.is_live(conn, a.id)
    memos.delete(m.id, NOW)  # 소프트 삭제: 연결은 그대로, 사진은 안 보인다
    assert not repo.is_live(conn, a.id) and repo.get(conn, a.id) is not None
    memos.restore(m.id)
    assert repo.is_live(conn, a.id)
    conv = conn.execute(
        "INSERT INTO conversations (kind, channel, logical_date, opened_at, last_message_at) "
        "VALUES ('chat', 'app', '2026-10-26', 'a', 'a')"
    ).lastrowid
    repo.link_message(conn, 501, conv, [b.id])
    repo.link_message(conn, 501, conv, [b.id])  # INSERT OR IGNORE
    assert repo.is_live(conn, b.id) and [p.id for p in repo.for_message(conn, 501)] == [b.id]
    assert repo.in_conversation(conn, conv, [b.id]) and not repo.in_conversation(conn, conv, [b.id, c.id])
    conn.execute("UPDATE conversations SET deleted_at = 'x' WHERE id = ?", (conv,))
    assert not repo.is_live(conn, b.id)
    assert not repo.is_live(conn, 999)


def test_purge_memo_with_photos_cascades(conn, repo):
    """Review Focus 6: `foreign_keys=ON`에서 사진 붙은 메모의 30일 purge가 CASCADE로 성공한다."""
    memos = MemosRepo(conn, None)  # type: ignore[arg-type]
    m = _memo(conn)
    ps = _insert(conn, repo, 2)
    for p in ps:
        repo.attach(conn, m.id, p.id)
    memos.delete(m.id, NOW - timedelta(days=31))
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert memos.purge_deleted(NOW - timedelta(days=30)) == 1
    assert conn.execute("SELECT COUNT(*) FROM memo_photos").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 2  # 사진 행·파일은 하루 작업(5.6)이 지운다


def test_uploaded_on_logical_day_and_read_text(conn, repo):
    _insert(conn, repo, 1, now=datetime(2026, 10, 25, 18, 59, tzinfo=UTC))  # 10/26 03:59 KST → 10/25
    _insert(conn, repo, 2, now=datetime(2026, 10, 25, 19, 0, tzinfo=UTC))  # 10/26 04:00 KST → 10/26
    assert repo.uploaded_on(conn, NOW.date()) == 2
    assert repo.uploaded_on(conn, (NOW - timedelta(days=1)).date()) == 1
    p = repo.get(conn, 1)
    repo.set_read_text(conn, p.id, "영수증 12,000원")
    assert repo.get(conn, p.id).read_text == "영수증 12,000원"


# --- 즉시 갈래 (5.2 쓰기 순서, 5.3 `/actions`) ---


def _store_req(tmp, image, origin="memo"):
    w, h = check_photo(image)
    return ActionRequest(
        "store_photo",
        {"image_tmp": str(tmp[0]), "thumb_tmp": str(tmp[1]), "sha256": sha(image), "bytes": len(image),
         "width": w, "height": h, "origin": origin},
        actor="user", channel="app", endpoint="photos",
    )


def _store(env, image=None, origin="memo"):
    image = image if image is not None else jpeg(pad=env.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0])
    tmp = env.parts.tools.photo_files.write_incoming(image, jpeg(80, 60))
    res = env.parts.dispatcher.apply_action(_store_req(tmp, image, origin))
    assert res.status == "applied", res.body
    return res.body["result"]


async def test_store_photo_writes_row_and_files(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        image = jpeg(1024, 768)
        out = _store(env, image)
        root = env.parts.tools.photo_files.root
        row = dict(env.conn.execute("SELECT * FROM photos").fetchone())
        status, _ = await env.action("store_photo", {})  # 밖(`/actions`)에서는 부를 수 없다
        activity = env.conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0]
    assert out == {"id": row["id"], "width": 1024, "height": 768, "bytes": len(image)}
    assert row["path"] == f"2026/10/{row['id']}-{sha(image)[:8]}.jpg" and row["origin"] == "memo"
    assert _files_under(root) == sorted([row["path"], row["thumb_path"]])  # .incoming은 비었다
    assert row["unlinked_at"] is None and status == 400 and activity == 0


async def test_store_photo_replays_client_msg_id(tmp_path):
    """5.3: 같은 `client_msg_id`로 다시 오면 처음 응답 그대로(행·파일은 하나). 다른 경로에 쓴 id면 409."""
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        files = env.parts.tools.photo_files
        image = jpeg(800, 600)
        first = env.parts.dispatcher.apply_action(
            replace(_store_req(files.write_incoming(image, jpeg(80, 60)), image), client_msg_id="p-1")
        )
        again = env.parts.dispatcher.apply_action(
            replace(_store_req(files.write_incoming(image, jpeg(80, 60)), image), client_msg_id="p-1")
        )
        stored = env.conn.execute("SELECT endpoint, status_code FROM api_idempotency").fetchall()
        count = env.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        status, other = await env.action("create_memo", {"body": "x"}, client_msg_id="p-1")
    assert first.status == "applied" and (again.status, again.http_status, again.body) == (
        first.status, first.http_status, first.body
    )
    assert [tuple(r) for r in stored] == [("photos", first.http_status)] and count == 1
    assert status == 409 and other["error"]["code"] == "conflict"


async def test_store_photo_replay_removes_this_requests_tmps(tmp_path):
    """다시 받은 요청의 `.incoming/` tmp는 쓰이지 않는다: 재생(같은 응답)이든 다른 경로 id(409)든 지운다.
    `.incoming/` 밖의 파일은 건드리지 않는다."""
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        files = env.parts.tools.photo_files
        image = jpeg(800, 600)
        env.parts.dispatcher.apply_action(
            replace(_store_req(files.write_incoming(image, jpeg(80, 60)), image), client_msg_id="p-1")
        )
        placed = _files_under(files.root)
        again = env.parts.dispatcher.apply_action(
            replace(_store_req(files.write_incoming(image, jpeg(80, 60)), image), client_msg_id="p-1")
        )
        after_replay = _files_under(files.root)
        await env.action("create_memo", {"body": "x"}, client_msg_id="m-1")
        crossed = env.parts.dispatcher.apply_action(
            replace(_store_req(files.write_incoming(image, jpeg(80, 60)), image), client_msg_id="m-1")
        )
        after_conflict = _files_under(files.root)
        outside = tmp_path / "keep.tmp"
        outside.write_bytes(image)
        img_tmp, thumb_tmp = files.write_incoming(image, jpeg(80, 60))
        thumb_tmp.unlink()  # 이 요청의 썸네일 자리에 `.incoming/` 밖의 파일을 둔다
        req = replace(_store_req((img_tmp, thumb_tmp), image), client_msg_id="p-1")
        req.args["thumb_tmp"] = str(outside)
        env.parts.dispatcher.apply_action(req)
        after_outside = _files_under(files.root)
    assert again.status == "applied" and crossed.http_status == 409
    assert after_replay == placed and after_conflict == placed
    assert outside.exists() and after_outside == placed  # 밖의 파일은 그대로, 안의 tmp는 지웠다


async def test_failed_insert_removes_file(tmp_path, monkeypatch):
    """Review Focus 1: 행 트랜잭션이 실패하면 최종 파일도 tmp도 없다."""
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        files = env.parts.tools.photo_files
        image = jpeg()
        tmp = files.write_incoming(image, jpeg(80, 60))
        monkeypatch.setattr(PhotosRepo, "insert", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("x")))
        with pytest.raises(sqlite3.OperationalError):
            env.parts.dispatcher.apply_action(_store_req(tmp, image))
        monkeypatch.undo()
        assert _files_under(files.root) == []
        # 이름 바꾸기까지 한 뒤 바깥 트랜잭션이 실패해도 바꾼 파일을 지운다
        tmp2 = files.write_incoming(image, jpeg(80, 60))
        placed = []
        with pytest.raises(RuntimeError), transaction(env.conn):
            res = env.parts.dispatcher.apply_action(_store_req(tmp2, image))
            assert res.status == "applied"
            placed = _files_under(files.root)
            raise RuntimeError("after")
        rows = env.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        left = _files_under(files.root)
    assert rows == 0 and left == [] and len(placed) == 2


async def test_failed_write_leaves_no_row(tmp_path, monkeypatch):
    """Review Focus 1: 파일 쓰기(이름 바꾸기)가 실패하면 행이 없다."""
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        files = env.parts.tools.photo_files
        image = jpeg()
        tmp = files.write_incoming(image, jpeg(80, 60))
        tmp[1].unlink()  # 작은 사진 tmp가 사라졌다: 큰 사진은 이름을 바꾼 뒤 실패
        with pytest.raises(OSError):
            env.parts.dispatcher.apply_action(_store_req(tmp, image))
        rows = env.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        left = _files_under(files.root)
        outside = tmp_path / "elsewhere.jpg"
        outside.write_bytes(image)
        res = env.parts.dispatcher.apply_action(_store_req((outside, outside), image))  # .incoming 밖은 받지 않는다
    assert rows == 0 and left == []
    assert res.status == "rejected" and outside.exists()


async def test_attach_detach_actions_and_undo(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        made = (await env.action("create_memo", {"body": "영수증"}))[1]["result"]
        ids = [_store(env)["id"] for _ in range(11)]
        env.clock.advance(minutes=5)
        for pid in ids[:10]:
            status, att = await env.action("attach_photo", {"memo_id": made["id"], "photo_id": pid})
            assert status == 200, att
        status, over = await env.action("attach_photo", {"memo_id": made["id"], "photo_id": ids[10]})
        stamp = env.conn.execute("SELECT updated_at FROM memos").fetchone()[0]
        _, out = await env.action("detach_photo", {"memo_id": made["id"], "photo_id": ids[3]})
        _, again = await env.action("attach_photo", {"memo_id": made["id"], "photo_id": ids[10]})
        resp = await env.post(f"/activity/{out['undo_id']}/undo", json={"client_msg_id": "u-photo"})
        undone = await resp.json()
        repo = env.parts.tools.photos
        positions = {p.id: i for i, p in enumerate(repo.for_memo(env.conn, made["id"]))}
        back = repo.get(env.conn, ids[3])
        rows = [dict(r) for r in env.conn.execute("SELECT kind, target, summary, undo_json FROM activity")]
        memo_stamp = env.conn.execute("SELECT updated_at FROM memos").fetchone()[0]
        created = env.conn.execute("SELECT created_at FROM memos").fetchone()[0]
        status_gone, gone = await env.action("detach_photo", {"memo_id": made["id"], "photo_id": 999})
        other = (await env.action("create_memo", {"body": "다른 메모"}))[1]["result"]["id"]
        status_other, not_here = await env.action("detach_photo", {"memo_id": other, "photo_id": ids[0]})
    assert status == 422 and over["error"]["code"] == "too_many_photos"
    assert over["error"]["message"] == "사진은 메모 하나에 10장까지예요."
    assert att["result"] == {"memo_id": made["id"], "photo_id": ids[9], "position": 9} and "undo_id" not in att
    assert att["confirmation"] == "✓ 사진을 붙였어요"  # 8장 "사진 보기"(v2.5)
    assert out["confirmation"] == "✓ 사진을 뺐어요" and out["undo_id"]
    assert again["result"]["position"] == 3
    # 되돌릴 때 원래 자리(3)가 차 있으면 가장 작은 빈 자리: 0~9가 다 차 있어 10장 상한이다
    assert resp.status == 422 and undone["error"]["code"] == "too_many_photos"
    assert back.unlinked_at is not None and ids[3] not in positions
    assert memo_stamp == stamp == created  # 붙이기·빼기·되돌리기는 updated_at을 바꾸지 않는다
    # 그 메모에 없는 사진(없는 사진, 다른 메모의 사진)은 일반 거절(8장: `photo_not_found`가 아니다)
    assert status_gone == 422 and gone["error"]["code"] == "rejected"
    assert status_other == 422 and not_here["error"] == gone["error"]
    dumped = json.dumps(rows, ensure_ascii=False)
    assert ".jpg" not in dumped and "incoming" not in dumped  # 파일 경로는 활동에 없다(6장)
    detached = next(r for r in rows if r["kind"] == "photo_detached")
    assert detached["target"] == f"photo:{ids[3]}" and json.loads(detached["undo_json"]) == {
        "memo_id": made["id"], "photo_id": ids[3], "position": 3,
    }
    assert {r["kind"] for r in rows} == {"memo_created", "photo_attached", "photo_detached"}
    assert {r["summary"] for r in rows if r["kind"] == "photo_attached"} == {"✓ 사진을 붙였어요"}


async def test_detach_undo_restores_original_or_smallest_free(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        memo = (await env.action("create_memo", {"body": "사진 셋"}))[1]["result"]["id"]
        a, b, c, d = (_store(env)["id"] for _ in range(4))
        for pid in (a, b, c):
            await env.action("attach_photo", {"memo_id": memo, "photo_id": pid})
        _, out_b = await env.action("detach_photo", {"memo_id": memo, "photo_id": b})
        resp = await env.post(f"/activity/{out_b['undo_id']}/undo", json={"client_msg_id": "u-b"})
        undone = await resp.json()
        repo = env.parts.tools.photos
        first = [p.id for p in repo.for_memo(env.conn, memo)]
        _, out_a = await env.action("detach_photo", {"memo_id": memo, "photo_id": a})
        await env.action("attach_photo", {"memo_id": memo, "photo_id": d})  # a의 자리 0을 d가 차지
        _, out_c = await env.action("detach_photo", {"memo_id": memo, "photo_id": c})  # 2가 빈다
        resp_a = await env.post(f"/activity/{out_a['undo_id']}/undo", json={"client_msg_id": "u-a"})
        pos = dict(env.conn.execute("SELECT photo_id, position FROM memo_photos").fetchall())
        unlinked = repo.get(env.conn, a).unlinked_at
    assert resp.status == 200 and undone["status"] == "undone" and first == [a, b, c]
    assert resp_a.status == 200 and pos == {d: 0, b: 1, a: 2} and unlinked is None
    assert out_c["undo_id"]


async def test_attach_rejects_in_use_and_missing(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        one = (await env.action("create_memo", {"body": "하나"}))[1]["result"]["id"]
        two = (await env.action("create_memo", {"body": "둘"}))[1]["result"]["id"]
        p = _store(env)["id"]
        chat = _store(env, origin="chat")["id"]
        await env.action("attach_photo", {"memo_id": one, "photo_id": p})
        s_use, use = await env.action("attach_photo", {"memo_id": two, "photo_id": p})
        s_same, same = await env.action("attach_photo", {"memo_id": one, "photo_id": p})
        conv = env.conn.execute(
            "INSERT INTO conversations (kind, channel, logical_date, opened_at, last_message_at) "
            "VALUES ('chat', 'app', '2026-10-26', 'a', 'a')"
        ).lastrowid
        env.parts.tools.photos.link_message(env.conn, 77, conv, [chat])
        env.conn.commit()
        s_msg, msg = await env.action("attach_photo", {"memo_id": two, "photo_id": chat})
        s_none, none = await env.action("attach_photo", {"memo_id": two, "photo_id": 999})
        s_memo, nomemo = await env.action("attach_photo", {"memo_id": 999, "photo_id": p})
    assert s_use == 409 and use["error"] == {"code": "photo_in_use", "message": "이 사진은 다른 곳에 이미 붙어 있어요."}
    assert s_same == 200 and same["result"]["already"] is True and "undo_id" not in same
    assert s_msg == 409 and msg["error"]["code"] == "photo_in_use"
    assert s_none == 422 and none["error"]["code"] == "photo_not_found"
    assert s_memo == 422 and nomemo["error"]["message"] == "없는 메모예요."


async def test_create_memo_with_photo_ids(tmp_path):
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        a, b = _store(env)["id"], _store(env)["id"]
        status, made = await env.action("create_memo", {"body": "영수증 정리", "photo_ids": [b, a]})
        memo = made["result"]["id"]
        repo = env.parts.tools.photos
        order = [p.id for p in repo.for_memo(env.conn, memo)]
        s_use, use = await env.action("create_memo", {"body": "또", "photo_ids": [a]})
        many = [_store(env)["id"] for _ in range(11)]
        s_many, too_many = await env.action("create_memo", {"body": "많이", "photo_ids": many})
        s_dup, dup = await env.action("create_memo", {"body": "겹침", "photo_ids": [many[0], many[0]]})
        chat = _store(env, origin="chat")["id"]
        s_chat, wrong = await env.action("create_memo", {"body": "채팅", "photo_ids": [chat]})
        s_none, none = await env.action("create_memo", {"body": "없음", "photo_ids": [999]})
        s_bad, _ = await env.action("create_memo", {"body": "모양", "photo_ids": "1"})
        count = env.conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0]
        s_upd, _ = await env.action(
            "update_memo", {"id": memo, "body": "x", "updated_at": made["result"]["updated_at"], "photo_ids": [a]}
        )
        resp = await env.post(f"/activity/{made['undo_id']}/undo", json={"client_msg_id": "u-memo"})
        undone = await resp.json()
        hidden = repo.is_live(env.conn, a)
        links = env.conn.execute("SELECT COUNT(*) FROM memo_photos WHERE memo_id = ?", (memo,)).fetchone()[0]
    assert status == 200 and order == [b, a]
    assert made["confirmation"] == "✓ 메모를 만들었어요: 영수증 정리 (사진 2장)"
    assert s_use == 409 and use["error"]["code"] == "photo_in_use"
    assert s_many == 422 and too_many["error"]["code"] == "too_many_photos"
    assert s_dup == 422 and s_chat == 422 and wrong["error"]["code"] == "photo_not_found"
    assert s_none == 422 and none["error"]["code"] == "photo_not_found" and s_bad == 422
    assert count == 1  # 거절된 만들기는 메모를 남기지 않는다
    assert s_upd == 400  # `update_memo`는 사진을 받지 않는다
    assert resp.status == 200 and hidden is False and links == 2  # 되돌리기는 지우기: 연결은 그대로, 사진은 숨김
    assert dup["error"]["code"] == "rejected"
    assert undone["confirmation"] == "↩ 되돌림: 영수증 정리 메모를 만들었어요"  # 사진 수는 만들기 확인에만


async def test_undo_text_keeps_a_title_that_looks_like_the_photo_tail(tmp_path):
    """사진 없이 만든 메모의 제목이 `(사진 3장)`으로 끝나도 되돌림 문구는 제목 그대로다(꼬리를 글자로 떼지 않는다)."""
    from be_env import BeEnv

    async with BeEnv.start(tmp_path, start=MON_1400) as env:
        _, plain = await env.action("create_memo", {"body": "영수증 (사진 3장)"})
        resp = await env.post(f"/activity/{plain['undo_id']}/undo", json={"client_msg_id": "u-plain"})
        undone = await resp.json()
        ids = [_store(env)["id"] for _ in range(2)]
        _, with_photos = await env.action("create_memo", {"body": "영수증 (사진 3장)", "photo_ids": ids})
        resp2 = await env.post(f"/activity/{with_photos['undo_id']}/undo", json={"client_msg_id": "u-photos"})
        undone2 = await resp2.json()
    assert plain["confirmation"] == "✓ 메모를 만들었어요: 영수증 (사진 3장)"
    assert undone["confirmation"] == "↩ 되돌림: 영수증 (사진 3장) 메모를 만들었어요"
    assert with_photos["confirmation"] == "✓ 메모를 만들었어요: 영수증 (사진 3장) (사진 2장)"
    assert undone2["confirmation"] == "↩ 되돌림: 영수증 (사진 3장) 메모를 만들었어요"


def test_photo_copy_has_no_banned_words():
    """8장 문구는 금지어 검사에 넣는다."""
    from my_planner.tools import photos as pt
    from my_planner.tools.ui import banned_words

    copy = [v for k, v in vars(pt).items() if k.startswith("MSG_")] + [pt.ATTACHED, pt.DETACHED]
    words = banned_words()
    assert len(copy) == 11 and [(c, w) for c in copy for w in words if w in c] == []

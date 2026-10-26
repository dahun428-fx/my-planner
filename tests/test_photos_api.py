"""사진 HTTP API (SP10 스펙 5.3, 5.6 4번, 8장, 12장 `test_photos_api.py`, Review Focus 2).

`POST /photos`(multipart 스트림, 같은 `client_msg_id` 재생, 하루 100장 429, 507), 경로별 본문 상한(다른 경로는 길이 없는
본문도 64KB), `GET /photos/{id}`(바이트, `no-store`, 살아 있지 않으면 404, 토큰은 헤더로만), `GET /memos` 항목 `photos`,
`/health`의 `disk_low`. 사진 바이트는 꾸며 낸 JPEG 머리다(`test_photos_store.jpeg`).
"""

from __future__ import annotations

import logging
import os

import aiohttp
import jsonschema
import pytest
from be_env import DISK_FREE, TEST_TOKEN, BeEnv
from test_dispatcher_messages import kst
from test_photos_store import jpeg, sha

from my_planner.api.models import schema_bundle
from my_planner.api.photos import DISK_FULL_BELOW, DISK_LOW_BELOW, PHOTO_BODY_MAX
from my_planner.config import LimitsConfig
from my_planner.store.photos import IMAGE_MAX_BYTES, THUMB_MAX_BYTES

MON_1400 = kst(2026, 10, 26, 14, 0)

MSG_TOO_LARGE = "사진이 너무 커요."
MSG_CANT_OPEN = "이 사진은 열 수 없어요."
MSG_LIMIT = "오늘은 사진을 더 올릴 수 없어요. 내일 다시 올려 주세요."
MSG_DISK = "노트북 저장 공간이 부족해 사진을 올릴 수 없어요."


def _validate(model, body):
    jsonschema.Draft202012Validator(schema_bundle()["models"][model]).validate(body)


@pytest.fixture
async def env(tmp_path):
    async with BeEnv.start(tmp_path, start=MON_1400) as e:
        yield e


def form(image=None, thumb=None, *, origin="memo", client_msg_id="p-1", skip=()):
    f = aiohttp.FormData()
    fields = {
        "image": image if image is not None else jpeg(1024, 768),
        "thumb": thumb if thumb is not None else jpeg(400, 300),
        "origin": origin, "client_msg_id": client_msg_id,
    }
    for name, value in fields.items():
        if name in skip:
            continue
        if isinstance(value, bytes):
            f.add_field(name, value, filename=f"{name}.jpg", content_type="image/jpeg")
        else:
            f.add_field(name, value)
    return f


async def upload(env, *args, **kw):
    resp = await env.post("/photos", data=form(*args, **kw))
    return resp.status, await resp.json()


def padded(size: int, w=1024, h=768) -> bytes:
    """크기가 정확히 `size`바이트인 JPEG 머리."""
    base = jpeg(w, h, pad=0)
    return jpeg(w, h, pad=size - len(base))


def incoming(env) -> list[str]:
    d = env.parts.tools.photo_files.incoming
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def photo_count(env) -> int:
    return env.conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]


# --- POST /photos (5.3) ---


async def test_post_photo_201_and_client_msg_id_replay(env, caplog):
    caplog.set_level(logging.INFO)
    image = jpeg(1024, 768)
    status, body = await upload(env, image, client_msg_id="p-1")
    again_status, again = await upload(env, image, client_msg_id="p-1")
    row = dict(env.conn.execute("SELECT * FROM photos").fetchone())
    stored = env.conn.execute("SELECT endpoint FROM api_idempotency").fetchall()
    assert status == 201 and body == {"id": row["id"], "width": 1024, "height": 768, "bytes": len(image)}
    _validate("PhotoUploaded", body)
    assert (again_status, again) == (201, body) and photo_count(env) == 1
    assert row["sha256"] == sha(image) and row["origin"] == "memo"
    assert [r[0] for r in stored] == ["photos"]
    assert incoming(env) == []  # 재생한 요청의 tmp도 지웠다
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert ".jpg" not in logged and ".tmp" not in logged  # 파일 경로는 로그에 없다(6장)


async def test_post_photo_largest_allowed_body_passes(env):
    """`client_max_size`(64KB)는 그대로인데 사진 경로만 큰 본문을 받는다(S4): 5,000,000바이트 + 작은 사진 256KiB."""
    image = padded(IMAGE_MAX_BYTES)
    thumb = padded(THUMB_MAX_BYTES, 400, 300)
    status, body = await upload(env, image, thumb, origin="chat")
    assert status == 201 and body["bytes"] == IMAGE_MAX_BYTES
    assert env.conn.execute("SELECT origin FROM photos").fetchone()[0] == "chat"


@pytest.mark.parametrize(
    ("image", "thumb", "status", "code", "message"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"x" * 64, None, 415, "photo_not_jpeg", MSG_CANT_OPEN),
        (jpeg(eoi=False), None, 422, "photo_unreadable", MSG_CANT_OPEN),
        (jpeg(2049, 1000), None, 413, "photo_too_large", MSG_TOO_LARGE),
        (padded(IMAGE_MAX_BYTES + 1), None, 413, "photo_too_large", MSG_TOO_LARGE),
        (None, padded(THUMB_MAX_BYTES + 1, 400, 300), 413, "photo_too_large", MSG_TOO_LARGE),
        (None, b"GIF89a" + b"x" * 32, 415, "photo_not_jpeg", MSG_CANT_OPEN),
    ],
    ids=["png", "no-eoi", "side-2049", "bytes-5000001", "thumb-256k+1", "thumb-gif"],
)
async def test_post_photo_rejects_bad_images(env, image, thumb, status, code, message):
    got_status, body = await upload(env, image, thumb)
    assert (got_status, body["error"]) == (status, {"code": code, "message": message})
    assert photo_count(env) == 0 and incoming(env) == []


@pytest.mark.parametrize(
    "kw",
    [
        {"skip": ("thumb",)},
        {"skip": ("image",)},
        {"skip": ("client_msg_id",)},
        {"origin": "note"},
        {"client_msg_id": ""},
    ],
    ids=["no-thumb", "no-image", "no-client-msg-id", "bad-origin", "empty-client-msg-id"],
)
async def test_post_photo_bad_form_400(env, kw):
    status, body = await upload(env, **kw)
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert photo_count(env) == 0 and incoming(env) == []


async def test_post_photo_not_multipart_400(env):
    resp = await env.post("/photos", json={"image": "x"})
    assert resp.status == 400 and (await resp.json())["error"]["code"] == "invalid_request"


async def test_post_photo_needs_header_token(env):
    resp = await env.post("/photos", data=form(), token=None)
    assert resp.status == 401 and photo_count(env) == 0


async def test_daily_photo_limit_429_on_logical_day(tmp_path):
    """하루 올리기 상한(`limits.daily_photos`, 5.1): 논리적 날짜(04:00 경계)로 센다."""
    async with BeEnv.start(tmp_path, start=MON_1400, overrides={"limits": LimitsConfig(daily_photos=2)}) as env:
        first = [(await upload(env, jpeg(pad=i), client_msg_id=f"p-{i}"))[0] for i in range(2)]
        status, body = await upload(env, jpeg(pad=9), client_msg_id="p-9")
        left = incoming(env)
        env.clock.advance(hours=13, minutes=30)  # 화 03:30: 아직 월요일(논리적 날짜)
        still, _ = await upload(env, jpeg(pad=10), client_msg_id="p-10")
        env.clock.advance(minutes=31)  # 화 04:01
        next_day, _ = await upload(env, jpeg(pad=11), client_msg_id="p-11")
        count = photo_count(env)
    assert first == [201, 201]
    assert status == 429 and body["error"] == {"code": "photo_limit", "message": MSG_LIMIT}
    assert left == [] and still == 429 and next_day == 201 and count == 3


async def test_disk_full_507_and_health_disk_low(env):
    """5.6 4번: 남은 공간이 2GB 아래면 507 `disk_full`, 5GB 아래면 `/health`의 `disk_low`."""
    assert env.deps.disk_free(env.settings.paths.data_dir) == DISK_FREE  # BeEnv: 시험 기계의 디스크와 뗀다
    plenty = await (await env.get("/health")).json()
    env.deps.disk_free = lambda _path: DISK_LOW_BELOW - 1
    low = await (await env.get("/health")).json()
    ok_status, _ = await upload(env, client_msg_id="p-low")  # 5GB 아래라도 2GB 위면 올린다
    env.deps.disk_free = lambda _path: DISK_FULL_BELOW - 1
    status, body = await upload(env, jpeg(pad=3), client_msg_id="p-full")
    assert plenty["disk_low"] is False and low["disk_low"] is True and low["status"] == plenty["status"]
    _validate("Health", low)
    assert ok_status == 201
    assert status == 507 and body["error"] == {"code": "disk_full", "message": MSG_DISK}
    assert photo_count(env) == 1 and incoming(env) == []


# --- 경로별 본문 상한 (5.3, S4, Review Focus 2) ---


async def _chunks(total: int, step: int = 16 * 1024):
    sent = 0
    while sent < total:
        n = min(step, total - sent)
        sent += n
        yield b"x" * n


async def test_chunked_body_over_64k_rejected_on_actions(env):
    """`POST /photos`가 큰 본문을 받아도 다른 경로의 상한은 64KB 그대로다: 길이 없는(chunked) 본문도."""
    results = {}
    for path in ("/actions", "/chat"):
        try:
            resp = await env.post(path, data=_chunks(65 * 1024), headers={"Content-Type": "application/json"})
            results[f"{path} chunked"] = resp.status
        except aiohttp.ClientError as e:  # 서버가 읽기를 멈추고 닫아도 받아들이지 않은 것이다
            results[f"{path} chunked"] = type(e).__name__
        resp = await env.post(path, data=b"x" * (65 * 1024), headers={"Content-Type": "application/json"})
        results[f"{path} length"] = resp.status
    assert results == {
        "/actions chunked": 413, "/actions length": 413, "/chat chunked": 413, "/chat length": 413,
    }


async def test_photo_route_body_limit_by_length_and_stream(env):
    """사진 경로는 `Content-Length` 5.5MiB(미들웨어), 길이 없는 본문은 처리기가 세며 413."""
    big = os.urandom(PHOTO_BODY_MAX + 1024)
    f = aiohttp.FormData()
    f.add_field("image", big, filename="a.jpg", content_type="image/jpeg")
    resp = await env.post("/photos", data=f)
    by_length = (resp.status, (await resp.json())["error"]["code"])

    boundary = "b" * 16

    async def stream():
        yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"a.jpg\"\r\n"
               "Content-Type: image/jpeg\r\n\r\n").encode()
        async for c in _chunks(PHOTO_BODY_MAX + 64 * 1024, 64 * 1024):
            yield c
        yield f"\r\n--{boundary}--\r\n".encode()

    try:
        resp = await env.post("/photos", data=stream(),
                              headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        chunked = (resp.status, (await resp.json())["error"]["code"])
    except aiohttp.ClientError as e:
        chunked = (type(e).__name__, None)
    assert by_length == (413, "photo_too_large")
    assert chunked == (413, "photo_too_large")
    assert photo_count(env) == 0 and incoming(env) == []


# --- GET /photos/{id} (5.3, 7.3) ---


async def _memo_with_photo(env, image=None, thumb=None):
    _, up = await upload(env, image, thumb, client_msg_id=f"m-{photo_count(env)}")
    status, made = await env.action("create_memo", {"body": "영수증"})
    assert status == 200, made
    memo = made["result"]["id"]
    status, att = await env.action("attach_photo", {"memo_id": memo, "photo_id": up["id"]})
    assert status == 200, att
    return memo, up["id"]


async def test_get_photo_bytes_and_no_store(env):
    image, thumb = jpeg(1024, 768, pad=40), jpeg(400, 300, pad=7)
    _, pid = await _memo_with_photo(env, image, thumb)
    full = await env.get(f"/photos/{pid}")
    full_body = await full.read()
    small = await env.get(f"/photos/{pid}?size=thumb")
    small_body = await small.read()
    explicit = await env.get(f"/photos/{pid}?size=full")
    bad = await env.get(f"/photos/{pid}?size=huge")
    assert full.status == 200 and full_body == image
    assert full.headers["Content-Type"] == "image/jpeg"
    assert full.headers["Cache-Control"] == "private, no-store"
    assert small.status == 200 and small_body == thumb and small.headers["Cache-Control"] == "private, no-store"
    assert explicit.status == 200 and await explicit.read() == image
    assert bad.status == 400


async def test_get_photo_not_live_404(env):
    """살아 있지 않은 사진(붙기 전, 지운 메모, 뺀 사진, 없는 id)은 404(5.1)."""
    _, loose = await upload(env, client_msg_id="loose")
    memo, pid = await _memo_with_photo(env, jpeg(pad=5))
    live = (await env.get(f"/photos/{pid}")).status
    await env.action("delete_memo", {"id": memo})
    deleted = (await env.get(f"/photos/{pid}?size=thumb")).status
    memo2, pid2 = await _memo_with_photo(env, jpeg(pad=6))
    await env.action("detach_photo", {"memo_id": memo2, "photo_id": pid2})
    detached = (await env.get(f"/photos/{pid2}")).status
    statuses = [(await env.get(p)).status for p in (f"/photos/{loose['id']}", "/photos/999", "/photos/abc")]
    assert live == 200 and deleted == 404 and detached == 404 and statuses == [404, 404, 404]


async def test_get_photo_missing_file_404_and_warns(env, caplog):
    _, pid = await _memo_with_photo(env)
    rel = env.conn.execute("SELECT path FROM photos WHERE id = ?", (pid,)).fetchone()[0]
    (env.parts.tools.photo_files.root / rel).unlink()
    with caplog.at_level(logging.WARNING):
        resp = await env.get(f"/photos/{pid}")
    warn = [r for r in caplog.records if r.msg == "photo_missing"]
    assert resp.status == 404 and len(warn) == 1 and warn[0].photo_id == pid
    assert rel not in f"{warn[0].__dict__}"


async def test_get_photo_token_only_in_header(env):
    _, pid = await _memo_with_photo(env)
    none = (await env.get(f"/photos/{pid}", token=None)).status
    in_query = [
        (await env.get(f"/photos/{pid}?{key}={TEST_TOKEN}", token=None)).status
        for key in ("token", "access_token", "key")
    ]
    assert none == 401 and in_query == [401, 401, 401]


# --- /actions로 붙이기 (5.3 표) ---


async def test_attach_uploaded_photos_limits_and_keeps_updated_at(env):
    _, made = await env.action("create_memo", {"body": "사진 열한 장"})
    memo = made["result"]["id"]
    ids = [(await upload(env, jpeg(pad=i), client_msg_id=f"a-{i}"))[1]["id"] for i in range(11)]
    env.clock.advance(minutes=5)
    for pid in ids[:10]:
        assert (await env.action("attach_photo", {"memo_id": memo, "photo_id": pid}))[0] == 200
    over_status, over = await env.action("attach_photo", {"memo_id": memo, "photo_id": ids[10]})
    other = (await env.action("create_memo", {"body": "다른 메모"}))[1]["result"]["id"]
    use_status, use = await env.action("attach_photo", {"memo_id": other, "photo_id": ids[0]})
    detail = await (await env.get(f"/memos/{memo}")).json()
    assert over_status == 422 and over["error"]["code"] == "too_many_photos"
    assert use_status == 409 and use["error"]["code"] == "photo_in_use"
    assert detail["updated_at"] == made["result"]["updated_at"]  # 붙이기는 `updated_at`을 바꾸지 않는다


# --- GET /memos 항목 photos (5.3) ---


async def test_memos_items_carry_photos(env):
    ids = [(await upload(env, jpeg(800 + i, 600, pad=i), client_msg_id=f"c-{i}"))[1]["id"] for i in range(3)]
    status, made = await env.action("create_memo", {"body": "세 장", "photo_ids": [ids[2], ids[0], ids[1]]})
    assert status == 200, made
    memo = made["result"]["id"]
    plain = (await env.action("create_memo", {"body": "사진 없음"}))[1]["result"]["id"]
    listing = await (await env.get("/memos")).json()
    detail = await (await env.get(f"/memos/{memo}")).json()
    bare = await (await env.get(f"/memos/{plain}")).json()
    _validate("MemoList", listing)
    _validate("Memo", detail)
    items = {i["id"]: i for i in listing["items"]}
    assert items[memo]["photos"] == [{"id": ids[2], "width": 802, "height": 600}]  # 목록은 첫 장만
    assert items[plain]["photos"] == [] and bare["photos"] == []
    assert detail["photos"] == [
        {"id": ids[2], "width": 802, "height": 600},
        {"id": ids[0], "width": 800, "height": 600},
        {"id": ids[1], "width": 801, "height": 600},
    ]


def test_upload_copy_has_no_banned_words():
    """8장 문구는 금지어 검사에 넣는다."""
    from my_planner.api import photos as ap
    from my_planner.tools import photos as pt
    from my_planner.tools.ui import banned_words

    copy = [v for k, v in vars(ap).items() if k.startswith("MSG_")] + [pt.MSG_PHOTO_LIMIT]
    words = banned_words()
    assert len(copy) >= 5 and [(c, w) for c in copy for w in words if w in c] == []
    assert {MSG_TOO_LARGE, MSG_CANT_OPEN, MSG_DISK, MSG_LIMIT} <= set(copy)


def test_photo_config_keys():
    """config.toml의 사진 설정(5.1·5.4·14장). `daily_photo_reads`·`reader`·`cleanup`은 뒤 티켓이 쓴다."""
    from pathlib import Path

    from my_planner.config import Settings

    text = (Path(__file__).resolve().parents[1] / "config.toml").read_text(encoding="utf-8")
    for line in ("max_photo_bytes = 5000000", "daily_photos = 100", "daily_photo_reads = 30",
                 'reader = "claude"', "cleanup = true"):
        assert line in text, line
    defaults = Settings.model_fields
    assert "photos" in defaults
    lim = LimitsConfig()
    assert (lim.daily_photos, lim.daily_photo_reads) == (100, 30)


def test_body_limit_constants():
    assert PHOTO_BODY_MAX == int(5.5 * 1024 * 1024)
    assert DISK_FULL_BELOW < DISK_LOW_BELOW

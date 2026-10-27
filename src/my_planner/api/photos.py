"""사진 HTTP API (SP10 스펙 5.3, 5.6 4번): `POST /photos`, `GET /photos/{id}`.

- 본문 크기: 앱 전체 `client_max_size`(64KB)는 그대로다. `POST /photos`만 `request.multipart()` 스트림으로 읽으며
  바이트를 세어, 부분별 상한(`image` `api.max_photo_bytes`, `thumb` 256KiB)이나 합계 5.5MiB를 넘는 순간 413을 낸다
  (스파이크 S4: 스트림 리더는 `client_max_size`를 받지 않는다). `Content-Length`는 `body_limit` 미들웨어가 이 경로
  틀에서 5.5MiB로 본다(`/body` 4KB와 같은 방식).
- 쓰기 순서(5.2): JPEG 확인 → `.incoming/` tmp 쓰기(`asyncio.to_thread`, 즉시 갈래 밖) → 즉시 갈래의 `store_photo`
  (`/actions`와 같은 `Dispatcher.apply_action`, `endpoint="photos"`)가 행과 최종 이름을 한 트랜잭션에 쓴다. 같은
  `client_msg_id`는 처음 응답을 그대로 돌려주고 이번 tmp는 지운다(`on_replay`). 적용하지 않은 요청의 tmp는 여기서 지운다.
- 남은 공간: 데이터 폴더 드라이브가 2GB 아래면 507 `disk_full`, 5GB 아래면 `/health`의 `disk_low`(5.6 4번).
- `GET /photos/{id}`: 읽기 전용 연결로 살아 있는 사진(5.1)만 찾고 파일 바이트를 준다. `Cache-Control: private, no-store`
  (앱 메모리 캐시만, 7.3). 토큰은 헤더로만(쿼리 토큰은 인증이 아니다, SP3-4 6.1).
- `POST /photos/{id}/read`(5.4): 이미 읽었으면(`read_text`) 두뇌 없이 그 값. 아니면 파일 바이트를 읽어 디스패처의 두뇌
  큐(`Dispatcher.read_photo`)에 넣는다. 같은 사진의 동시 요청은 한 호출을 함께 기다린다. 하루 상한 429
  `photo_read_limit`, 두뇌가 답하지 못하면 503(앱은 "다시 읽기"). 아직 붙지 않은 새 사진도 읽는다(새 메모는 저장 때 붙는다).
- 로그에는 사진 id와 코드만 남긴다. 사진 바이트, 파일 경로, sha256은 남기지 않는다(6장).
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import BodyPartReader, web

from my_planner.api.models import (
    ErrorCode,
    PhotoRead,
    PhotoUploaded,
    dump,
    error_response,
)
from my_planner.harness.photo_reader import (
    PhotoGone,
    PhotoReadFailed,
    PhotoReadLimit,
    ReadResult,
)
from my_planner.store.photos import (
    THUMB_MAX_BYTES,
    PhotoFileConflict,
    PhotoFiles,
    PhotoNotJpeg,
    PhotoTooLarge,
    PhotoUnreadable,
    check_photo,
)
from my_planner.store.repos.activity import IdempotencyRepo
from my_planner.store.repos.photos import PhotosRepo
from my_planner.tools.actions import ActionRequest, ActionResult

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

log = logging.getLogger(__name__)

PHOTOS_PATH = "/api/v1/photos"  # `body_limit`의 경로 틀
# 5.3 합계 5.5MiB(머리·경계 포함). 부분 상한의 합(5,000,000 + 256KiB + 글 둘 400)이 이보다 작아 처리기의 합계 검사는
# 닿지 않는 안전판이다. 실제로 쓰이는 곳은 `body_limit`의 `Content-Length` 검사다
PHOTO_BODY_MAX = int(5.5 * 1024 * 1024)
FIELD_MAX = 200  # `origin`, `client_msg_id` 글 부분(`client_msg_id`는 다른 경로처럼 200자)
CHUNK = 64 * 1024
GB = 1024**3  # 2GB·5GB는 GiB(1024³)로 센다: Windows 탐색기가 보이는 값과 같다
DISK_FULL_BELOW = 2 * GB  # 5.6 4번: 이 아래면 `POST /photos` 507
DISK_LOW_BELOW = 5 * GB  # 5.6 4번: 이 아래면 `/health`의 `disk_low`
ORIGINS = ("memo", "chat")
SIZES = ("full", "thumb")
_INT = re.compile(r"^[0-9]{1,18}$")

# 스펙 8장 문구
MSG_TOO_LARGE = "사진이 너무 커요."
MSG_CANT_OPEN = "이 사진은 열 수 없어요."
MSG_UPLOAD_FAILED = "사진을 올리지 못했어요. 다시 보내 주세요."
MSG_DISK_FULL = "노트북 저장 공간이 부족해 사진을 올릴 수 없어요."
BAD_BODY = "요청 형식이 맞지 않아요."  # `/actions`와 같은 글
NO_PHOTO = "없는 사진이에요."
TRY_LATER = "잠시 뒤에 다시 해 주세요."
BAD_SIZE = "size는 full 또는 thumb이어야 해요."
MSG_READ_LIMIT = "오늘은 사진 읽기를 더 할 수 없어요. 사진은 붙여 둘 수 있어요."  # 스펙 8장


def disk_free_bytes(path: Path) -> int:
    """`path`가 있는 드라이브의 남은 바이트. 아직 없는 폴더면 있는 윗폴더로 본다."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def disk_low(deps: ApiDeps) -> bool:
    return deps.disk_free(deps.settings.paths.data_dir) < DISK_LOW_BELOW


class _Refused(Exception):
    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


def _too_large() -> _Refused:
    return _Refused(413, "photo_too_large", MSG_TOO_LARGE)


def _bad() -> _Refused:
    return _Refused(400, "invalid_request", BAD_BODY)


async def _read_parts(request: web.Request, image_max: int) -> dict[str, bytes]:
    """multipart 부분을 이름별 바이트로. 세면서 읽어 상한을 넘으면 그 자리에서 413(남은 본문은 읽지 않는다)."""
    limits = {"image": image_max, "thumb": THUMB_MAX_BYTES, "origin": FIELD_MAX, "client_msg_id": FIELD_MAX}
    try:
        reader = await request.multipart()
    except (AssertionError, ValueError, LookupError):  # multipart가 아니거나 경계가 없다
        raise _bad() from None
    parts: dict[str, bytes] = {}
    total = 0
    try:
        while (part := await reader.next()) is not None:
            if not isinstance(part, BodyPartReader) or part.name not in limits or part.name in parts:
                raise _bad()
            name, buf = part.name, bytearray()
            while chunk := await part.read_chunk(CHUNK):
                total += len(chunk)
                buf += chunk
                if total > PHOTO_BODY_MAX:  # 닿지 않는 안전판(위 `PHOTO_BODY_MAX` 설명)
                    raise _too_large()
                if len(buf) > limits[name]:
                    raise _too_large() if name in ("image", "thumb") else _bad()
            parts[name] = bytes(buf)
    except (AssertionError, ValueError, LookupError):  # 깨진 multipart
        raise _bad() from None
    return parts


def _check(parts: dict[str, bytes], image_max: int) -> tuple[bytes, bytes, str, str, int, int]:
    """부분 모양 → JPEG 확인(5.3 순서: 바이트, 머리, 긴 변). (사진, 작은 사진, origin, client_msg_id, 너비, 높이)."""
    image, thumb = parts.get("image"), parts.get("thumb")
    try:
        origin = parts.get("origin", b"").decode("utf-8")
        cmid = parts.get("client_msg_id", b"").decode("utf-8")
    except UnicodeDecodeError:
        raise _bad() from None
    if not image or not thumb or origin not in ORIGINS or not 1 <= len(cmid) <= FIELD_MAX:
        raise _bad()
    try:
        w, h = check_photo(image, max_bytes=image_max)
        check_photo(thumb, max_bytes=THUMB_MAX_BYTES)
    except PhotoTooLarge:
        raise _too_large() from None
    except PhotoNotJpeg:
        raise _Refused(415, "photo_not_jpeg", MSG_CANT_OPEN) from None
    except PhotoUnreadable:
        raise _Refused(422, "photo_unreadable", MSG_CANT_OPEN) from None
    return image, thumb, origin, cmid, w, h


def _write(files: PhotoFiles, image: bytes, thumb: bytes) -> tuple[tuple[Path, Path], str]:
    """갈래 밖(스레드)에서: tmp 둘을 쓰고 `fsync`, 사진의 sha256."""
    return files.write_incoming(image, thumb), hashlib.sha256(image).hexdigest()


def _discard(files: PhotoFiles, tmp: tuple[Path, Path]) -> None:
    for p in tmp:
        if files.is_incoming(p):
            try:
                p.unlink(missing_ok=True)
            except OSError:  # 남으면 하루 한 번 작업의 고아 정리(5.6 2번)
                pass


def _photo_files(deps: ApiDeps) -> PhotoFiles:
    tools = deps.dispatcher.tools if deps.dispatcher is not None else None
    files = tools.photo_files if tools is not None else None
    assert files is not None, "안전 모드가 아니면 사진 폴더가 있다"
    return files


def _stored(deps: ApiDeps, cmid: str) -> bool:
    """이 `client_msg_id`의 응답이 이미 있나(읽기 전용 연결). 있으면 즉시 갈래가 도구 없이 그대로 돌려준다."""
    assert deps.read_conn is not None, "안전 모드가 아니면 읽기 연결이 있다"
    conn = deps.read_conn()
    try:
        return IdempotencyRepo(conn, deps.clock).get(cmid) is not None
    finally:
        conn.close()


def _store(deps: ApiDeps, args: dict[str, Any], cmid: str) -> ActionResult:
    assert deps.dispatcher is not None
    return deps.dispatcher.apply_action(
        ActionRequest("store_photo", args, actor="user", channel="app", client_msg_id=cmid, endpoint="photos")
    )


def _answer(res: ActionResult) -> web.Response:
    if res.status == "applied":
        return web.json_response(dump(PhotoUploaded, res.body["result"]), status=201)
    err = res.body.get("error") or {}
    return error_response(res.http_status, err.get("code", "rejected"), err.get("message", MSG_UPLOAD_FAILED))


async def post_photos(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    image_max = deps.settings.api.max_photo_bytes
    try:
        image, thumb, origin, cmid, w, h = _check(await _read_parts(request, image_max), image_max)
    except _Refused as e:
        return error_response(e.status, e.code, e.message)
    if deps.disk_free(deps.settings.paths.data_dir) < DISK_FULL_BELOW:
        # 이미 저장한 요청을 다시 받은 것이면 파일을 쓰지 않고 처음 응답을 돌려준다(남은 공간과 무관)
        if _stored(deps, cmid):
            return _answer(_store(deps, {}, cmid))
        log.warning("photo_disk_full")
        return error_response(507, "disk_full", MSG_DISK_FULL)
    files = _photo_files(deps)
    try:
        tmp, digest = await asyncio.to_thread(_write, files, image, thumb)
    except OSError as e:
        log.warning("photo_write_failed", extra={"error_type": type(e).__name__})
        if e.errno == errno.ENOSPC:
            return error_response(507, "disk_full", MSG_DISK_FULL)
        return error_response(500, "internal", MSG_UPLOAD_FAILED)
    args: dict[str, Any] = {
        "image_tmp": str(tmp[0]), "thumb_tmp": str(tmp[1]), "sha256": digest, "bytes": len(image),
        "width": w, "height": h, "origin": origin,
    }
    try:
        return _answer(_store(deps, args, cmid))
    except (PhotoFileConflict, OSError) as e:  # 트랜잭션은 되돌려졌다
        log.warning("photo_store_failed", extra={"error_type": type(e).__name__})
        return error_response(500, "internal", MSG_UPLOAD_FAILED)
    finally:
        # 5.2 3번: 어느 단계에서 끝나든(적용 안 함, 재생, 예외, 취소) 남은 tmp를 지운다. 적용했으면 이미 최종 이름으로
        # 바뀌어 없다(`missing_ok`). 그 밖의 예외는 그대로 올라가 500(`call_json`)
        _discard(files, tmp)


def _find(conn: Any, deps: ApiDeps, photo_id: int, size: str) -> tuple[int, str] | None:
    repo = PhotosRepo(deps.settings.timezone, deps.settings.day_boundary)
    p = repo.get(conn, photo_id)
    if p is None or not repo.is_live(conn, photo_id):
        return None
    return p.id, (p.thumb_path if size == "thumb" else p.path)


def _read_file(root: Path, rel: str) -> bytes | None:
    """파일 바이트. 없으면 None. 잠긴 파일(백신 등, 5.2)이나 그 밖의 읽기 실패는 `OSError`를 올린다."""
    path = (root / rel).resolve()
    if root not in path.parents:  # DB 값이어도 사진 폴더 밖은 열지 않는다
        return None
    try:
        return path.read_bytes()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return None


async def get_photo(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    raw = request.match_info["id"]
    size = request.query.get("size", "full")
    if size not in SIZES:
        return error_response(400, "invalid_request", BAD_SIZE)
    if not _INT.match(raw):
        return error_response(404, "not_found", NO_PHOTO)
    assert deps.read_conn is not None, "안전 모드가 아니면 읽기 연결이 있다"
    conn = deps.read_conn()
    try:
        found = _find(conn, deps, int(raw), size)
    finally:
        conn.close()
    if found is None:
        return error_response(404, "not_found", NO_PHOTO)
    photo_id, rel = found
    try:
        data = await asyncio.to_thread(_read_file, _photo_files(deps).root, rel)
    except OSError as e:  # 잠긴 파일(`PermissionError`) 등: 잠시 뒤 다시. 경로는 남기지 않는다
        log.warning("photo_read_failed", extra={"photo_id": photo_id, "error_type": type(e).__name__})
        return error_response(503, "unavailable", TRY_LATER)
    if data is None:  # 행은 있는데 파일이 없다(5.6 3번, 10장): 경로는 남기지 않는다
        log.warning("photo_missing", extra={"photo_id": photo_id})
        return error_response(404, "not_found", NO_PHOTO)
    return web.Response(
        body=data, content_type="image/jpeg", headers={"Cache-Control": "private, no-store"},
    )


def _read_answer(got: ReadResult) -> web.Response:
    return web.json_response(dump(PhotoRead, {"text": got.text, "unreadable": got.unreadable}))


async def post_photo_read(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    raw = request.match_info["id"]
    if not _INT.match(raw):
        return error_response(404, "not_found", NO_PHOTO)
    photo_id = int(raw)
    assert deps.read_conn is not None and deps.dispatcher is not None, "안전 모드가 아니면 읽기 연결과 디스패처가 있다"
    conn = deps.read_conn()
    try:
        repo = PhotosRepo(deps.settings.timezone, deps.settings.day_boundary)
        p = repo.get(conn, photo_id)
        readable = p is not None and repo.is_readable(conn, photo_id)
    finally:
        conn.close()
    if p is None or not readable:
        return error_response(404, "not_found", NO_PHOTO)
    if p.read_text is not None:  # 이미 읽었다: 두뇌를 부르지 않는다(5.3)
        return _read_answer(ReadResult(text=p.read_text, unreadable=p.read_text == ""))
    try:
        image = await asyncio.to_thread(_read_file, _photo_files(deps).root, p.path)
    except OSError as e:
        log.warning("photo_read_failed", extra={"photo_id": photo_id, "error_type": type(e).__name__})
        return error_response(503, "unavailable", TRY_LATER)
    if image is None:
        log.warning("photo_missing", extra={"photo_id": photo_id})
        return error_response(404, "not_found", NO_PHOTO)
    try:
        got = await deps.dispatcher.read_photo(photo_id, image)
    except PhotoReadLimit:
        return error_response(429, "photo_read_limit", MSG_READ_LIMIT)
    except PhotoGone:
        return error_response(404, "not_found", NO_PHOTO)
    except PhotoReadFailed:
        return error_response(503, "unavailable", TRY_LATER)
    return _read_answer(got)

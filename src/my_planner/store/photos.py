"""사진 파일 `data/photos/` (SP10 스펙 5.2, ADR 0017). 바이트는 여기에만 두고 DB(`photos`)에는 경로와 정보만.

- 경로: `<YYYY>/<MM>/<id>-<sha256 앞 8자>.jpg`와 `-t.jpg`(작은 사진). 연·월은 현지 달력 날짜(폴더 이름일 뿐).
- 쓰기 순서: `write_incoming`(즉시 갈래 밖, `asyncio.to_thread`)이 `.incoming/<uuid>.tmp`·`<uuid>-t.tmp`를 쓰고
  `fsync`한다 → 즉시 갈래의 `store_photo`가 한 트랜잭션에서 행을 넣고 `place`로 덮어쓰지 않는 이름 바꾸기를 한다.
- 파일은 한 번 쓰고 바꾸지 않는다. 지우기는 하루 한 번 작업(5.6)만 `remove`로 한다(쓰다 실패한 파일 정리는 예외).
- JPEG 확인은 그림 라이브러리 없이 머리(SOI·SOFn)와 끝(EOI)만 본다. 작은 사진은 앱이 만든다(7.2).
- 이 모듈은 로그에 경로를 남기지 않는다(6장).
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path

IMAGE_MAX_BYTES = 5_000_000  # 5.3 `image`
THUMB_MAX_BYTES = 256 * 1024  # 5.3 `thumb`
SIDE_MAX = 2048  # 긴 변(5.1)
INCOMING = ".incoming"
_RETRIES = 3  # `remove`의 `PermissionError`(백신 등) 다시 하기(5.2)
_RETRY_SLEEP = 0.2

# 크기를 담은 SOFn 표지(DHT C4, JPG C8, DAC CC는 아니다)
_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
_STANDALONE = frozenset({0x01, *range(0xD0, 0xD8)})  # 길이 없는 표지(TEM, RSTn)


class PhotoNotJpeg(ValueError):
    """JPEG 머리(SOI)가 아니다(415 `photo_not_jpeg`)."""


class PhotoUnreadable(ValueError):
    """JPEG로 시작하지만 크기를 읽을 수 없거나 끝(EOI)이 없다(422 `photo_unreadable`)."""


class PhotoTooLarge(ValueError):
    """바이트 또는 긴 변이 상한을 넘는다(413 `photo_too_large`)."""


class PhotoFileConflict(OSError):
    """최종 이름에 다른 내용(sha256)의 파일이 이미 있다(5.2 2번, 5.7 롤백 뒤)."""


def jpeg_size(data: bytes) -> tuple[int, int]:
    """JPEG 머리에서 (너비, 높이). SOI가 아니면 `PhotoNotJpeg`, SOFn이 없거나 크기가 0이거나 EOI가 없으면 `PhotoUnreadable`."""
    if data[:2] != b"\xff\xd8":
        raise PhotoNotJpeg
    if data[-2:] != b"\xff\xd9":
        raise PhotoUnreadable
    i, n = 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            raise PhotoUnreadable
        while i < n and data[i] == 0xFF:  # 채움 0xFF
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker in _STANDALONE:
            continue
        if marker in (0xD9, 0xDA) or i + 2 > n:  # 크기 전에 끝이나 그림 자료가 나왔다
            break
        length = int.from_bytes(data[i:i + 2], "big")
        if length < 2 or i + length > n:
            break
        if marker in _SOF:
            if length < 7:
                break
            height = int.from_bytes(data[i + 3:i + 5], "big")
            width = int.from_bytes(data[i + 5:i + 7], "big")
            if width == 0 or height == 0:
                break
            return width, height
        i += length
    raise PhotoUnreadable


def check_photo(data: bytes, *, max_bytes: int = IMAGE_MAX_BYTES, max_side: int = SIDE_MAX) -> tuple[int, int]:
    """바이트 상한 → JPEG 머리 → 긴 변 상한 순서로 본다(5.3). (너비, 높이)."""
    if len(data) > max_bytes:
        raise PhotoTooLarge
    w, h = jpeg_size(data)
    if max(w, h) > max_side:
        raise PhotoTooLarge
    return w, h


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_synced(p: Path, data: bytes) -> None:
    with p.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _rename_no_overwrite(src: Path, dst: Path) -> None:
    """있으면 `FileExistsError`. Windows의 `os.rename`은 덮어쓰지 않는다. 그 밖은 링크 뒤 원래 이름을 지운다."""
    if os.name == "nt":
        os.rename(src, dst)
    else:
        os.link(src, dst)
        os.unlink(src)


class PhotoFiles:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()  # data/photos

    @property
    def incoming(self) -> Path:
        return self.root / INCOMING

    def jpeg_size(self, data: bytes) -> tuple[int, int]:
        return jpeg_size(data)

    def is_incoming(self, p: Path) -> bool:
        """`.incoming/` 바로 아래의 tmp인가(`store_photo`가 다른 파일 이름을 바꾸지 않게)."""
        p = Path(p).resolve()
        return p.parent == self.incoming and p.suffix == ".tmp"

    def write_incoming(self, image: bytes, thumb: bytes) -> tuple[Path, Path]:
        """`.incoming/<uuid>.tmp`와 `<uuid>-t.tmp`를 쓰고 `fsync`한다(즉시 갈래 밖, `asyncio.to_thread`). 실패하면 쓴 것을 지운다."""
        self.incoming.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex
        paths = (self.incoming / f"{name}.tmp", self.incoming / f"{name}-t.tmp")
        try:
            _write_synced(paths[0], image)
            _write_synced(paths[1], thumb)
        except BaseException:
            for p in paths:
                p.unlink(missing_ok=True)
            raise
        return paths

    def final_names(self, photo_id: int, sha256: str, local_day: date) -> tuple[str, str]:
        base = f"{local_day.year:04d}/{local_day.month:02d}/{photo_id}-{sha256[:8]}"
        return f"{base}.jpg", f"{base}-t.jpg"

    def place(
        self, incoming: tuple[Path, Path], photo_id: int, sha256: str, local_day: date,
        *, created: list[Path] | None = None,
    ) -> tuple[str, str]:
        """tmp 둘을 최종 이름으로 덮어쓰지 않고 바꾼다(즉시 갈래 안, `store_photo` 트랜잭션). 상대 경로 둘.

        최종 이름이 이미 있으면(5.7 롤백 뒤 같은 id): 큰 사진은 sha256이 같으면 그 파일을 그대로 쓰고 tmp를 지우며,
        다르면 `PhotoFileConflict`. 작은 사진은 큰 사진에서 만든 것이라 큰 사진이 맞으면 있던 것을 그대로 쓴다.
        실패하면 이번에 만든 파일과 tmp를 지우고 올린다. `created`에는 이번에 새로 만든 최종 파일을 더한다(롤백 정리용).
        """
        rel = self.final_names(photo_id, sha256, local_day)
        made: list[Path] = []
        try:
            (self.root / rel[0]).parent.mkdir(parents=True, exist_ok=True)
            for i, (src, name) in enumerate(zip(incoming, rel, strict=True)):
                dst = self.root / name
                try:
                    _rename_no_overwrite(Path(src), dst)
                    made.append(dst)
                except FileExistsError:
                    if i == 0 and _sha256_file(dst) != sha256:
                        raise PhotoFileConflict(photo_id) from None
                    Path(src).unlink()
        except BaseException:
            for p in (*made, *map(Path, incoming)):
                p.unlink(missing_ok=True)
            raise
        if created is not None:
            created.extend(made)
        return rel

    def read(self, rel: str) -> bytes | None:
        """최종 파일 바이트(두뇌 입력, 5.5). 없거나 사진 폴더 밖이면 None. 그 밖의 읽기 실패는 `OSError`."""
        path = (self.root / rel).resolve()
        if self.root not in path.parents:  # DB 값이어도 사진 폴더 밖은 열지 않는다
            return None
        try:
            return path.read_bytes()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None

    def exists(self, rel: str) -> bool:
        """최종 파일이 있는가(5.6 3번 없는 파일). 사진 폴더 밖이면 False."""
        path = (self.root / rel).resolve()
        return self.root in path.parents and path.is_file()

    def remove(self, *rel_paths: str) -> None:
        """상대 경로의 파일을 지운다(하루 한 번 작업). 없으면 그만. `PermissionError`면 세 번까지 다시 해 보고 올린다."""
        for rel in rel_paths:
            p = self.root / rel
            for attempt in range(_RETRIES):
                try:
                    p.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt == _RETRIES - 1:
                        raise
                    time.sleep(_RETRY_SLEEP)

    def orphans(self, known: set[str], older_than: datetime) -> list[str]:
        """`known`(행의 경로들)에 없고 `older_than`보다 먼저 고친 파일의 상대 경로(5.6 2번). `.incoming/`의 tmp도 포함."""
        if not self.root.exists():
            return []
        cutoff = older_than.timestamp()
        out: list[str] = []
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(self.root).as_posix()
            if rel not in known and p.stat().st_mtime < cutoff:
                out.append(rel)
        return sorted(out)

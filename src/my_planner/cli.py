"""명령줄 `python -m my_planner [명령]` (SP3-4 스펙 6.1, 15).

인자가 없으면 BE를 띄운다(`app.main()`). `gen-token`은 API 토큰 하나를 출력한다(`.env`의 `API_TOKEN`에 넣는다).
`schema`는 `GET /schema`와 같은 JSON 스키마 묶음을 출력한다(운영 앱이 빌드 때 쓴다).
`gen-vapid`는 웹 푸시 VAPID 키 한 쌍을 `.env` 줄 모양으로 출력한다(사용자가 `.env`에 붙여 넣는다. 파일에 쓰지 않는다).
`seed-life <파일> [--dry-run]`은 검토한 인생 곡선 시드를 가져온다(12장, `curve/seed.py`). 출력은 개수뿐이다.
"""

from __future__ import annotations

import secrets
import sys
from collections.abc import Sequence

USAGE = "사용법: python -m my_planner [gen-token | gen-vapid | schema | seed-life <파일> [--dry-run]]"
EXIT_USAGE = 2


def gen_token() -> str:
    """32바이트 무작위(43자, URL-safe base64)."""
    return secrets.token_urlsafe(32)


def gen_vapid() -> tuple[str, str]:
    """새 P-256 키 한 쌍: (공개키 = base64url(비압축 점 65바이트), 비밀키 = base64url(원시 32바이트)). 패딩 없음.

    공개키는 브라우저 `applicationServerKey`, 비밀키는 `pywebpush`(`py_vapid.Vapid.from_string`)가 받는 모양이다.
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    raw_private = key.private_numbers().private_value.to_bytes(32, "big")
    raw_public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    return b64(raw_public), b64(raw_private)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        from my_planner import app  # 명령만 쓸 때는 텔레그램·SDK를 불러오지 않는다

        return app.main()
    if args == ["gen-token"]:
        print(gen_token())
        return 0
    if args == ["gen-vapid"]:
        public, private = gen_vapid()
        print(f"VAPID_PUBLIC_KEY={public}")
        print(f"VAPID_PRIVATE_KEY={private}")
        print("VAPID_SUBJECT=mailto:… 줄도 .env에 직접 적어 주세요(받을 수 있는 주소).", file=sys.stderr)
        return 0
    if args == ["schema"]:
        import json

        from my_planner.api.models import (
            schema_bundle,  # 텔레그램·SDK 없이 모델만 불러온다
        )

        print(json.dumps(schema_bundle(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args[0] == "seed-life":
        return seed_life(args[1:])
    print(USAGE, file=sys.stderr)
    return EXIT_USAGE


def seed_life(argv: Sequence[str]) -> int:
    """`seed-life <파일> [--dry-run]`. 루트는 BE와 같다(`MY_PLANNER_ROOT` 또는 저장소 루트)."""
    import argparse
    from pathlib import Path

    from my_planner.config import resolve_root
    from my_planner.curve.seed import run_seed_life

    parser = argparse.ArgumentParser(
        prog="python -m my_planner seed-life",
        description="검토한 인생 곡선 시드(meta.reviewed: true)를 한 번만 가져온다. 출력은 개수뿐이다. "
        "BE가 돌고 있으면 거절한다(코드 3).",
        epilog="종료 코드: 0 가져옴(또는 --dry-run 끝남), 3 BE 실행 중, 4 이미 가져옴, "
        "5 meta.reviewed가 true가 아님, 6 읽을 수 없거나 JSON 객체가 아닌 파일.",
    )
    parser.add_argument("file", type=Path, help="시드 JSON 파일(노트북의 data/seed/ 아래)")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 가져올 개수와 건너뛸 개수만 출력한다")
    ns = parser.parse_args(list(argv))
    return run_seed_life(resolve_root(), ns.file, dry_run=ns.dry_run, out=sys.stdout)

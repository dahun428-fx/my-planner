"""명령줄 `python -m my_planner [명령]` (SP3-4 스펙 6.1, 15).

인자가 없으면 BE를 띄운다(`app.main()`). `gen-token`은 API 토큰 하나를 출력한다(`.env`의 `API_TOKEN`에 넣는다).
`schema`는 `GET /schema`와 같은 JSON 스키마 묶음을 출력한다(운영 앱이 빌드 때 쓴다).
`gen-vapid`는 웹 푸시 VAPID 키 한 쌍을 `.env` 줄 모양으로 출력한다(사용자가 `.env`에 붙여 넣는다. 파일에 쓰지 않는다).
`seed-life <파일> [--dry-run]`은 검토한 인생 곡선 시드를 가져온다(12장, `curve/seed.py`). 출력은 개수뿐이다.
`seed-life --update-history <파일> [--dry-run]`은 이미 가져온 시드의 빈 히스토리 칸(사건 영역, 챕터 사다리)만
채운다(SP8 8.1).
`pair`는 새 기기에 넣을 연결 코드(6자리, 5분, 한 번)를 돌고 있는 BE에서 받아 출력한다(기기 연결 스펙 4.7).
"""

from __future__ import annotations

import secrets
import sys
from collections.abc import Sequence

USAGE = ("사용법: python -m my_planner [gen-token | gen-vapid | schema | pair | "
         "seed-life [--update-history] <파일> [--dry-run]]")
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
    if args == ["pair"]:
        return pair()
    if args[0] == "seed-life":
        return seed_life(args[1:])
    print(USAGE, file=sys.stderr)
    return EXIT_USAGE


def seed_life(argv: Sequence[str]) -> int:
    """`seed-life [--update-history] <파일> [--dry-run]`. 루트는 BE와 같다(`MY_PLANNER_ROOT` 또는 저장소 루트)."""
    import argparse
    from pathlib import Path

    from my_planner.config import resolve_root
    from my_planner.curve.seed import run_seed_life, run_update_history

    parser = argparse.ArgumentParser(
        prog="python -m my_planner seed-life",
        description="검토한 인생 곡선 시드(meta.reviewed: true)를 한 번만 가져온다. 출력은 개수뿐이다. "
        "BE가 돌고 있으면 거절한다(코드 3).",
        epilog="종료 코드: 0 가져옴(또는 --dry-run 끝남), 3 BE 실행 중, 4 이미 가져옴(--update-history는 이미 채움), "
        "5 meta.reviewed가 true가 아님, 6 읽을 수 없거나 JSON 객체가 아닌 파일, "
        "7 --update-history인데 아직 가져온 시드가 없음.",
    )
    parser.add_argument("file", type=Path, help="시드 JSON 파일(노트북의 data/seed/ 아래)")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 가져올 개수와 건너뛸 개수만 출력한다")
    parser.add_argument(
        "--update-history", action="store_true",
        help="이미 가져온 시드의 빈 칸(사건 영역, 챕터 사다리)만 같은 파일에서 채운다. 한 번만 돈다",
    )
    ns = parser.parse_args(list(argv))
    run = run_update_history if ns.update_history else run_seed_life
    return run(resolve_root(), ns.file, dry_run=ns.dry_run, out=sys.stdout)


PAIR_TIMEOUT_S = 10


def _post_local(url: str, token: str) -> tuple[int, dict[str, object]]:
    """`127.0.0.1`의 BE에 `POST`. 프록시를 거치지 않는다. 닿지 않으면 `OSError`."""
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=b"", method="POST", headers={"Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=PAIR_TIMEOUT_S) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:  # JSON이 아니거나 UTF-8이 아닌 본문
        body = {}
    return status, body if isinstance(body, dict) else {}


def pair() -> int:
    """연결 코드를 만든다. 토큰은 출력하지 않는다. 결과별 문구와 끝 코드는 기기 연결 스펙 4.7 표."""
    from my_planner.config import load_settings, resolve_root

    try:
        settings = load_settings(resolve_root())
    except (OSError, ValueError):  # 파일 없음·TOML 오류·검증 실패(pydantic ValidationError는 ValueError)
        print("설정을 읽지 못했어요. config.toml과 .env를 확인해 주세요.", file=sys.stderr)
        return 1
    token = settings.api_token.get_secret_value() if settings.api_token is not None else ""
    if not token:
        print(".env에 API_TOKEN이 없어요.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{settings.api.port}/api/v1/devices/pair"
    try:
        status, body = _post_local(url, token)
    except OSError:
        print("BE가 꺼져 있어요. 작업을 켜고 다시 해 주세요.", file=sys.stderr)
        return 1
    code = body.get("code")
    if status == 201 and isinstance(code, str) and len(code) == 6:
        print(f"연결 코드: {code[:3]} {code[3:]} (5분 동안, 한 번만)")
        return 0
    error = body.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    if status == 401:
        print(".env의 API_TOKEN이 BE와 달라요.", file=sys.stderr)
    elif status == 429:
        print("잠시 뒤에 다시 해 주세요.", file=sys.stderr)
    elif status == 503 and error_code == "safe_mode":
        print("BE가 안전 모드예요. 상태부터 확인해 주세요.", file=sys.stderr)
    else:
        print(f"코드를 만들지 못했어요 ({status}).", file=sys.stderr)
    return 1

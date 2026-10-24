"""명령줄 `python -m my_planner [명령]` (SP3-4 스펙 6.1, 15).

인자가 없으면 BE를 띄운다(`app.main()`). `gen-token`은 API 토큰 하나를 출력한다(`.env`의 `API_TOKEN`에 넣는다).
뒤 티켓이 더한다: `schema`(02), `gen-vapid`(08), `seed-life`(12).
"""

from __future__ import annotations

import secrets
import sys
from collections.abc import Sequence

USAGE = "사용법: python -m my_planner [gen-token]"
EXIT_USAGE = 2


def gen_token() -> str:
    """32바이트 무작위(43자, URL-safe base64)."""
    return secrets.token_urlsafe(32)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        from my_planner import app  # 명령만 쓸 때는 텔레그램·SDK를 불러오지 않는다

        return app.main()
    if args == ["gen-token"]:
        print(gen_token())
        return 0
    print(USAGE, file=sys.stderr)
    return EXIT_USAGE

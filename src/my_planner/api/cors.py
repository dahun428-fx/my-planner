"""CORS: 출처 허용 목록, 사전 요청, 사설망 접근(PNA) 헤더 (SP3-4 스펙 14, S9).

허용 출처는 `api.cors_origins`(정확한 문자열)와 선택 `api.cors_origin_regex`(전체 일치)뿐이다.
`*.vercel.app` 전체는 허용하지 않는다(누구나 그 주소에 배포할 수 있다). 허용 밖 출처에는 CORS 헤더를
하나도 주지 않는다(토큰 검사는 그대로). 자격 증명(쿠키)은 허용하지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable

from aiohttp import web

from my_planner.api.models import call_json

ALLOW_METHODS = "GET, POST, PUT, DELETE"
ALLOW_HEADERS = "Authorization, Content-Type"
EXPOSE_HEADERS = "x-conversation-id"

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class CorsPolicy:
    def __init__(self, origins: Iterable[str], origin_regex: str = "") -> None:
        """틀린 설정은 `ValueError`: `build_app`에서 나므로 `_open_api`가 받아 API만 열지 않는다."""
        origins = list(origins)
        if any("*" in o for o in origins):  # 정확한 문자열만(스펙 14). 미리보기 주소는 cors_origin_regex로
            raise ValueError("api.cors_origins에는 와일드카드를 쓰지 않는다")
        try:
            self._regex = re.compile(origin_regex) if origin_regex else None
        except re.error as e:
            raise ValueError("api.cors_origin_regex가 정규식이 아니다") from e
        self.origins = frozenset(origins)

    def allows(self, origin: str | None) -> bool:
        if not origin:
            return False
        if origin in self.origins:
            return True
        return self._regex is not None and self._regex.fullmatch(origin) is not None


def is_preflight(request: web.Request) -> bool:
    return request.method == "OPTIONS"


def cors_middleware(policy: CorsPolicy) -> Callable[[web.Request, Handler], Awaitable[web.StreamResponse]]:
    """사전 요청(`OPTIONS`)은 토큰 없이 여기서 `204`로 끝낸다. 그 밖의 응답에는 허용 출처일 때만 헤더를 붙인다.

    안쪽의 예외는 여기서 JSON 오류로 바꾼다(`call_json`): 오류 응답에도 CORS 헤더가 붙어야 브라우저가 401을 읽는다.
    """

    @web.middleware
    async def cors(request: web.Request, handler: Handler) -> web.StreamResponse:
        origin = request.headers.get("Origin")
        allowed = policy.allows(origin)
        if is_preflight(request):
            resp = web.Response(status=204)
            if allowed:
                assert origin is not None
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Methods"] = ALLOW_METHODS
                resp.headers["Access-Control-Allow-Headers"] = ALLOW_HEADERS
                if request.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
                    resp.headers["Access-Control-Allow-Private-Network"] = "true"
                resp.headers["Vary"] = "Origin"
            return resp
        resp = await call_json(handler, request)
        if allowed:
            assert origin is not None
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Expose-Headers"] = EXPOSE_HEADERS
            resp.headers["Vary"] = "Origin"
        return resp

    return cors

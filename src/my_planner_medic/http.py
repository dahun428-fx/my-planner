"""HTTP 이음매. 표준 라이브러리 `urllib`만 쓴다.

로그에는 메서드, 호스트·경로, 예외 종류만 남긴다. 요청·응답 본문, 헤더(토큰), 쿼리는 남기지 않는다.
"""

from __future__ import annotations

import http.client
import json as _json
import logging
import urllib.error
import urllib.request
from email.message import Message
from typing import Any, Protocol
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

Body = dict[str, Any] | list[Any] | None
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


class Http(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        timeout: float = 10,
    ) -> tuple[int, Body, dict[str, str]]:
        """(상태, JSON 본문, 소문자 키 응답 헤더). 연결 실패·시간 초과는 `(0, None, {})`. 예외를 올리지 않는다."""
        ...


def _decode(raw: bytes) -> Body:
    if not raw:
        return None
    try:
        value = _json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict | list) else None


def _headers(msg: Message | None) -> dict[str, str]:
    return {k.lower(): v for k, v in msg.items()} if msg is not None else {}


def _where(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname}{parts.path}"


class UrllibHttp:
    def __init__(self) -> None:
        self._direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._default = urllib.request.build_opener()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        timeout: float = 10,
    ) -> tuple[int, Body, dict[str, str]]:
        hdrs = dict(headers or {})
        data = None
        if json is not None:
            data = _json.dumps(json, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
        # 자기 BE(127.0.0.1)는 시스템 프록시를 거치지 않는다
        opener = self._direct if urlsplit(url).hostname in _LOOPBACK else self._default
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, _decode(resp.read()), _headers(resp.headers)
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except (OSError, http.client.HTTPException):
                raw = b""
            return exc.code, _decode(raw), _headers(exc.headers)
        except (OSError, http.client.HTTPException, ValueError) as exc:  # URLError·시간 초과는 OSError
            log.warning("http_failed %s %s (%s)", method.upper(), _where(url), type(exc).__name__)
            return 0, None, {}

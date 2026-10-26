"""텔레그램 직접 보내기 (스펙 6장 "Actions가 텔레그램 API로 직접").

이름이 `telegram.py`가 아닌 것은 pytest `pythonpath`에서 python-telegram-bot의 `telegram` 패키지를 가리지 않게.
봇 토큰은 URL 경로에 들어가므로 URL·응답 본문·예외 글은 찍지 않는다(medic `http._where`와 같은 규칙).
"""

from __future__ import annotations

import os

from gh import Http, UrllibHttp

URL = "https://api.telegram.org/bot{token}/sendMessage"


def send(text: str, *, http: Http | None = None, token: str | None = None, chat_id: str | None = None) -> bool:
    """보냈으면 True. 토큰은 인자가 없으면 `TELEGRAM_BOT_TOKEN`, 받는 사람은 `OWNER_TELEGRAM_ID`."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "") if token is None else token
    chat_id = os.environ.get("OWNER_TELEGRAM_ID", "") if chat_id is None else chat_id
    if not token or not chat_id:
        print("telegram: not configured")
        return False
    status, _, _ = (http or UrllibHttp()).request(
        "POST", URL.format(token=token), json={"chat_id": chat_id, "text": text}, timeout=20,
    )
    if status != 200:
        print(f"telegram: send failed ({status})")
        return False
    print("telegram: sent")
    return True

"""결과 알림 (스펙 6장). 이 티켓은 프로토콜만 둔다. 구현(`Notifier`)은 티켓 08."""

from __future__ import annotations

from typing import Protocol


class NotifierLike(Protocol):
    def fixed(self, pr_title: str, pr_url: str) -> None:
        """"🔧 자동으로 고쳤어요: <PR 제목>. <PR 링크>"."""
        ...

    def gave_up(self, fingerprint: str, rolled_back: bool, issue_url: str, *, direct: bool = False) -> None:
        """"⚠️ 자동으로 못 고쳤어요: …". `direct`면 BE를 거치지 않고 텔레그램으로 바로."""
        ...

    def daily(self, text: str, key: str) -> None:
        """같은 `key`는 하루(논리적 날짜) 한 번만 보낸다(상한은 08이 지킨다)."""
        ...

"""지난 대화 찾기 도구 `find_conversations` (SP9 스펙 7.5, ADR 0014). `Tools`가 이 mixin을 상속한다.

- 앱 대화의 두뇌에게만 준다(`APP_ONLY_TOOLS`). 앱 통로의 끝난 대화(닫힘, 답장 창이 끝난 회차) 가운데 `query`가 제목·요약에
  맞는 것, 없으면 최근 것. 결과는 `id`, 날짜(논리적 날짜), 제목, 요약뿐이고 **원문은 주지 않는다**.
- 제목·요약은 `redact()`를 거친다(7.5, 6.3). 지운 대화는 나오지 않는다(7.7).
- 아무것도 바꾸지 않는다(활동·도구 이벤트 없음). 로그에는 개수만 남긴다.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from my_planner.domain import RunContext
from my_planner.harness.redact import redact
from my_planner.tools._base import _err, _tool

if TYPE_CHECKING:
    from my_planner.clock import Clock
    from my_planner.store.repos.conversations import ConversationsRepo

log = logging.getLogger(__name__)

FIND_DAYS_DEFAULT, FIND_DAYS_MAX = 14, 90
FIND_LIMIT_DEFAULT, FIND_LIMIT_MAX = 5, 20
FIND_QUERY_MAX = 100

MSG_NO_CONVERSATIONS = "대화를 찾을 수 없어요."
MSG_DAYS = f"days는 1~{FIND_DAYS_MAX} 사이 정수예요."
MSG_LIMIT = f"limit은 1~{FIND_LIMIT_MAX} 사이 정수예요."
MSG_QUERY = f"query는 {FIND_QUERY_MAX}자까지의 글이에요."


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


class ConversationTools:
    """`Tools`의 지난 대화 찾기. `self.conversations`가 None이면 거절한다."""

    conversations: ConversationsRepo | None

    if TYPE_CHECKING:
        clock: Clock

    @_tool
    def find_conversations(
        self, ctx: RunContext, query: Any = None, days: Any = FIND_DAYS_DEFAULT, limit: Any = FIND_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        """최근 `days`일 안에 말이 있었던 앱 통로의 끝난 대화, 마지막 메시지가 최근인 것부터 `limit`개(7.5).

        부른 대화의 상대(`ctx.agent`)와 같은 상대의 대화만 찾는다(SP12 5.3)."""
        repo = self.conversations
        if repo is None:
            return _err(MSG_NO_CONVERSATIONS)
        if query is not None and (not isinstance(query, str) or len(query) > FIND_QUERY_MAX):
            return _err(MSG_QUERY)
        d = FIND_DAYS_DEFAULT if days is None else days
        if not _is_int(d) or not 1 <= d <= FIND_DAYS_MAX:
            return _err(MSG_DAYS)
        n = FIND_LIMIT_DEFAULT if limit is None else limit
        if not _is_int(n) or not 1 <= n <= FIND_LIMIT_MAX:
            return _err(MSG_LIMIT)
        since = self.clock.now() - timedelta(days=d)
        found = repo.recent(channel="app", limit=n, q=query, closed_only=True, since=since, agent=ctx.agent)
        items = [
            {
                "id": c.id,
                "date": c.logical_date.isoformat(),
                "title": redact(c.title)[0] if c.title else None,
                "summary": redact(c.summary)[0] if c.summary else None,
            }
            for c in found
        ]
        log.info("conversations_found", extra={"count": len(items)})
        return {"items": items}

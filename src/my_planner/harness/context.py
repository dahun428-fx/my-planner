"""두뇌에 넘기는 컨텍스트 조각. 이 티켓은 매 호출 맨 앞의 알림만 다룬다 (스펙 5.3)."""

from __future__ import annotations


def build_notices(*, redacted: bool, stale_hours: float | None, truncated: bool) -> str:
    """`## 알림` 섹션. 해당하는 것이 없으면 빈 문자열."""
    lines: list[str] = []
    if redacted:
        lines.append("- 인증·식별 정보를 가렸어요.")
    if stale_hours is not None:
        lines.append(f"- 약 {max(1, round(stale_hours))}시간 전에 보낸 메시지예요.")
    if truncated:
        lines.append("- 메시지가 길어 앞 8000자만 넘겼어요.")
    if not lines:
        return ""
    return "## 알림\n" + "\n".join(lines)

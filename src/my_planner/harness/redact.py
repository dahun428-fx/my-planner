"""인증·식별 정보 가리기 (스펙 5.8). 부작용 없는 순수 함수."""

from __future__ import annotations

import re

MASK = "[가림]"

# 휴대전화 번호는 계좌번호로 보지 않는다. 가리기 전에 먼저 빼 둔다.
_PHONE = re.compile(r"(?<![\d-])01[016-9]-?\d{3,4}-?\d{4}(?![\d-])")

# 주민등록번호(외국인등록번호 포함) 형식: 6자리-7자리, 뒷자리 첫 숫자 1~8
_RRN = re.compile(r"(?<![\d-])\d{6}-?[1-8]\d{6}(?![\d-])")

# "비밀번호/비번/password/PIN" 뒤의 값.
# - 구분: 조사(은/는/이/가/도), 영어 is/was, `:`/`=`. PIN 뒤의 "번호"는 키워드에 포함한다.
# - 값: 공백 없는 덩어리에서 마지막 비한글 글자까지. 그 뒤의 한글(조사 "야" 등)은 남긴다.
#   영문자나 숫자(ASCII)가 하나도 없는 덩어리("바꿨어요", "변경했어?")는 값으로 보지 않는다.
_HANGUL = "가-힣ㄱ-ㅎㅏ-ㅣ"
_SECRET_CONTEXT = re.compile(
    r"(?P<key>비밀번호|비번|패스워드|핀번호"
    r"|(?<![A-Za-z])(?i:password|passwd)(?![A-Za-z])"
    r"|(?<![A-Za-z])(?i:pin)(?![A-Za-z])(?:\s*번호|\s+(?i:number|code))?)"
    r"(?P<sep>(?:\s*(?:은|는|이|가|도)|\s+(?i:is|was)(?![A-Za-z]))?\s*[:=：]?\s*)"
    rf"(?P<val>(?=[^\s]*[A-Za-z0-9])[^\s]*[^\s{_HANGUL}])"
)

# 계좌번호로 보이는 숫자열: 숫자와 하이픈으로 이어진 덩어리 중 숫자가 10~14자리인 것
_DIGIT_RUN = re.compile(r"(?<![\d-])\d[\d-]*\d(?![\d-])")


def _mask_account(m: re.Match[str]) -> str:
    digits = sum(c.isdigit() for c in m.group(0))
    return MASK if 10 <= digits <= 14 else m.group(0)


def redact(text: str) -> tuple[str, bool]:
    """가린 자리는 `[가림]`으로 바꾼다. (가린 결과, 가린 일이 있었는지)를 돌려준다."""
    kept: list[str] = []

    def _keep(m: re.Match[str]) -> str:
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    out = _PHONE.sub(_keep, text)
    out = _SECRET_CONTEXT.sub(lambda m: m.group("key") + m.group("sep") + MASK, out)
    out = _RRN.sub(MASK, out)
    out = _DIGIT_RUN.sub(_mask_account, out)
    out = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], out)
    return out, out != text

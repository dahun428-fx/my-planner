"""인증·식별 정보 가리기 (스펙 5.8). 부작용 없는 순수 함수."""

from __future__ import annotations

import re

MASK = "[가림]"

# 휴대전화 번호는 계좌번호로 보지 않는다. 가리기 전에 먼저 빼 둔다.
_PHONE = re.compile(r"(?<![\d-])01[016-9]-?\d{3,4}-?\d{4}(?![\d-])")

# 주민등록번호(외국인등록번호 포함) 형식: 6자리-7자리, 뒷자리 첫 숫자 1~8
_RRN = re.compile(r"(?<![\d-])\d{6}-?[1-8]\d{6}(?![\d-])")

# "비밀번호/비번/password/PIN" 뒤의 값. 값은 공백과 한글이 아닌 글자 덩어리다(조사 "야" 등은 남긴다).
_SECRET_CONTEXT = re.compile(
    r"(?P<key>비밀번호|비번|패스워드|핀번호|(?<![A-Za-z])(?i:password|passwd)(?![A-Za-z])|(?<![A-Za-z])PIN(?![A-Za-z]))"
    r"(?P<sep>\s*(?:은|는|이|가|도)?\s*[:=：]?\s*)"
    r"(?P<val>[^\s가-힣ㄱ-ㅎㅏ-ㅣ]+)"
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

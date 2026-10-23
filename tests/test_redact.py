from my_planner.harness.redact import redact


def test_redact_rrn():
    assert redact("900101-1234567") == ("[가림]", True)
    assert redact("주민번호 9001011234567 입니다") == ("주민번호 [가림] 입니다", True)


def test_redact_account_number():
    assert redact("110-123-456789") == ("[가림]", True)
    assert redact("계좌 3333012345678로 보내 주세요") == ("계좌 [가림]로 보내 주세요", True)


def test_redact_password_context():
    assert redact("비번은 hunter2야") == ("비번은 [가림]야", True)
    assert redact("password: abc") == ("password: [가림]", True)
    assert redact("PIN 1234") == ("PIN [가림]", True)
    assert redact("비밀번호=Qw!9x 바꿨어요") == ("비밀번호=[가림] 바꿨어요", True)


def test_redact_keeps_phone_and_dates():
    for text in ["010-1234-5678", "01012345678", "2026-10-23", "14:00", "내일 14:00 치과, 2026-10-23"]:
        assert redact(text) == (text, False)
    assert redact("비밀번호 바꾸는 날") == ("비밀번호 바꾸는 날", False)

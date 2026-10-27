import json
import logging

from my_planner.logging_setup import setup_logging


def _entries(path):
    for h in logging.getLogger().handlers:
        h.flush()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_third_party_fstring_message_dropped(tmp_path):
    path = setup_logging(tmp_path / "state", 30)
    body = '{"type":"assistant","message":"비서 답장 본문 조각"}'
    try:
        raise ValueError(f"Failed to decode JSON: {body}")
    except ValueError as e:
        # SDK의 .error(..., exc_info=True)와 같은 기록. 본문이 든 f-string 메시지가 이 테스트의 대상이다
        logging.getLogger("claude_agent_sdk._internal.query").exception(
            f"Fatal error in message reader: {e}"  # noqa: TRY401
        )
    logging.getLogger("my_planner.x").info("own_event", extra={"n": 1})

    raw = path.read_text(encoding="utf-8")
    assert "비서 답장 본문 조각" not in raw
    entries = _entries(path)
    sdk = [e for e in entries if e["logger"] == "claude_agent_sdk._internal.query"]
    assert len(sdk) == 1
    assert sdk[0]["level"] == "ERROR" and sdk[0]["exc_type"] == "ValueError"
    assert sdk[0]["msg"] == "third_party_log"
    own = [e for e in entries if e["logger"] == "my_planner.x"]
    assert own[0]["msg"] == "own_event" and own[0]["n"] == 1


def _poll_error(exc: Exception) -> None:
    try:
        raise exc
    except Exception:
        # PTB Updater가 폴링 오류를 재시도하며 남기는 기록과 같다
        logging.getLogger("telegram.ext.Updater").exception("Exception happened while polling for updates.")


def test_transient_polling_error_is_not_an_error_record(tmp_path):
    from telegram.error import BadRequest, NetworkError, TimedOut

    path = setup_logging(tmp_path / "state", 30)
    _poll_error(NetworkError("httpx.ReadError"))
    _poll_error(TimedOut())
    _poll_error(BadRequest("x"))

    levels = {e["exc_type"]: e["level"] for e in _entries(path) if e["logger"] == "telegram.ext.Updater"}
    assert levels["NetworkError"] == "INFO" and levels["TimedOut"] == "INFO"
    assert levels["BadRequest"] == "ERROR"

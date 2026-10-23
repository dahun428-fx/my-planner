"""JSON 줄 로그 `state/logs/my-planner.jsonl`, 하루 단위 회전 (스펙 7).

메시지 본문과 도구 인자는 남기지 않는다. 그래서:
- 로그 메시지는 `%` 서식을 적용하지 않고 이름(`msg`) 그대로 쓴다. 값은 `extra=`로 넘긴다.
- `text`, `args`, `input` 키는 지운다.
- 예외는 종류와 호출 위치만 남기고, 예외 메시지(입력값이 들어 있을 수 있다)는 남기지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "my-planner.jsonl"
DROPPED_KEYS = frozenset({"text", "args", "input"})

_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}
_MARK = "_my_planner_handler"

# httpx는 INFO에서 요청 URL을 남긴다. 텔레그램 URL에는 봇 토큰이 들어 있다.
_QUIET_LOGGERS = ("httpx", "httpcore", "telegram", "apscheduler")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.msg if isinstance(record.msg, str) else type(record.msg).__name__,
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key in DROPPED_KEYS or key.startswith("_"):
                continue
            entry[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _, tb = record.exc_info
            entry["exc_type"] = exc_type.__name__
            entry["exc_where"] = [
                f"{f.filename}:{f.lineno} {f.name}" for f in traceback.extract_tb(tb)[-5:]
            ]
        for key in DROPPED_KEYS:
            entry.pop(key, None)
        return json.dumps(entry, ensure_ascii=False, default=str)


def _ensure_std_streams() -> bool:
    """pythonw에서는 sys.stdout/stderr가 None이다. devnull로 바꿔 둔다. 콘솔이 있었는지 돌려준다."""
    had_console = sys.stderr is not None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    return had_console


def setup_logging(state_dir: Path, keep_days: int) -> Path:
    """로그를 설정하고 로그 파일 경로를 돌려준다. 여러 번 불러도 된다."""
    had_console = _ensure_std_streams()
    log_dir = Path(state_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = (log_dir / LOG_FILE_NAME).resolve()

    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _MARK, False):
            root.removeHandler(h)
            h.close()

    formatter = JsonFormatter()
    file_handler = TimedRotatingFileHandler(
        path, when="midnight", backupCount=keep_days, encoding="utf-8", utc=False
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MARK, True)
    root.addHandler(file_handler)

    if had_console:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        setattr(console, _MARK, True)
        root.addHandler(console)

    root.setLevel(logging.INFO)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return path

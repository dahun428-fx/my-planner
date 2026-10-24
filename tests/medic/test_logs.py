from __future__ import annotations

import hashlib
import json
from pathlib import Path

from my_planner_medic.logs import ACTIVE, LogCursor, read_new_lines


def line(i: int) -> str:
    return json.dumps({"ts": f"2026-10-26T00:00:0{i}+00:00", "level": "INFO", "msg": f"e{i}"}) + "\n"


def write(path: Path, text: str, mode: str = "a") -> None:
    with path.open(mode, encoding="utf-8", newline="") as fh:
        fh.write(text)


def cursor_at(first_line: str, offset: int) -> LogCursor:
    return LogCursor(f"{ACTIVE}#{hashlib.sha1(first_line.encode()).hexdigest()[:12]}", offset)


def msgs(records: list[dict]) -> list[str]:
    return [r["msg"] for r in records]


def test_first_read_starts_at_end_of_complete_lines(tmp_path: Path) -> None:
    write(tmp_path / ACTIVE, line(1) + line(2))
    recs, cur, bad = read_new_lines(tmp_path, None)
    assert (recs, bad) == ([], 0)
    write(tmp_path / ACTIVE, line(3))
    recs, cur, bad = read_new_lines(tmp_path, cur)
    assert msgs(recs) == ["e3"]


def test_missing_log_file_is_empty(tmp_path: Path) -> None:
    recs, cur, bad = read_new_lines(tmp_path, None)
    assert (recs, cur, bad) == ([], LogCursor(ACTIVE, 0), 0)


def test_rotation_reads_tail_of_rotated_then_new_once(tmp_path: Path) -> None:
    active = tmp_path / ACTIVE
    write(active, line(1) + line(2))
    _, cur, _ = read_new_lines(tmp_path, LogCursor(ACTIVE, 0))
    write(active, line(3))  # 회전 직전에 쓴 줄
    active.rename(tmp_path / f"{ACTIVE}.2026-10-25")  # 자정 회전
    (tmp_path / f"{ACTIVE}.2026-10-24").write_text(line(9), encoding="utf-8")  # 더 오래된 회전 파일
    write(active, line(4), mode="w")
    recs, cur, bad = read_new_lines(tmp_path, cur)
    assert msgs(recs) == ["e3", "e4"]
    assert bad == 0
    assert cur == cursor_at(line(4), len(line(4).encode()))
    recs, cur, _ = read_new_lines(tmp_path, cur)
    assert recs == []
    write(active, line(5))
    recs, _, _ = read_new_lines(tmp_path, cur)
    assert msgs(recs) == ["e5"]


def test_partial_last_line_deferred(tmp_path: Path) -> None:
    active = tmp_path / ACTIVE
    whole = line(2)
    write(active, line(1) + whole[:10])
    recs, cur, bad = read_new_lines(tmp_path, LogCursor(ACTIVE, 0))
    assert (msgs(recs), bad) == (["e1"], 0)
    assert cur.offset == len(line(1).encode())
    write(active, whole[10:])
    recs, cur, bad = read_new_lines(tmp_path, cur)
    assert (msgs(recs), bad) == (["e2"], 0)


def test_bad_json_line_skipped(tmp_path: Path) -> None:
    active = tmp_path / ACTIVE
    write(active, line(1) + "{not json\n" + "[1, 2]\n" + "\n")
    with active.open("ab") as fh:
        fh.write(b"\xff\xfe\n")  # UTF-8이 아닌 줄
    write(active, line(2))
    recs, cur, bad = read_new_lines(tmp_path, LogCursor(ACTIVE, 0))
    assert msgs(recs) == ["e1", "e2"]
    assert bad == 3
    assert cur.offset == active.stat().st_size


def test_crlf_lines_are_read(tmp_path: Path) -> None:
    write(tmp_path / ACTIVE, line(1).replace("\n", "\r\n"))
    recs, _, bad = read_new_lines(tmp_path, LogCursor(ACTIVE, 0))
    assert (msgs(recs), bad) == (["e1"], 0)


def test_rotation_detected_when_new_file_grew_past_offset(tmp_path: Path) -> None:
    active = tmp_path / ACTIVE
    write(active, line(1))
    _, cur, _ = read_new_lines(tmp_path, LogCursor(ACTIVE, 0))
    assert cur == cursor_at(line(1), len(line(1).encode()))
    write(active, line(2))
    active.rename(tmp_path / f"{ACTIVE}.2026-10-25")
    write(active, line(3) + line(4) + line(5), mode="w")  # 새 파일이 이미 옛 위치보다 크다
    recs, cur, bad = read_new_lines(tmp_path, cur)
    assert (msgs(recs), bad) == (["e2", "e3", "e4", "e5"], 0)
    assert read_new_lines(tmp_path, cur)[0] == []


def test_two_rotations_while_down(tmp_path: Path) -> None:
    active = tmp_path / ACTIVE
    write(active, line(1))
    _, cur, _ = read_new_lines(tmp_path, LogCursor(ACTIVE, 0))
    write(active, line(2))
    active.rename(tmp_path / f"{ACTIVE}.2026-10-24")
    write(active, line(3), mode="w")
    with active.open("a", encoding="utf-8") as fh:
        fh.write(line(4).rstrip("\n"))  # 회전 직전 줄 끝 없이 끝난 파일
    active.rename(tmp_path / f"{ACTIVE}.2026-10-25")
    write(active, line(5), mode="w")
    recs, cur, bad = read_new_lines(tmp_path, cur)
    assert (msgs(recs), bad) == (["e2", "e3", "e4", "e5"], 0)
    assert cur == cursor_at(line(5), len(line(5).encode()))


def test_unmatched_signature_reads_active_from_start(tmp_path: Path) -> None:
    write(tmp_path / ACTIVE, line(1) + line(2))
    (tmp_path / f"{ACTIVE}.2026-10-25").write_text(line(7) + line(8), encoding="utf-8")
    recs, _, bad = read_new_lines(tmp_path, LogCursor(f"{ACTIVE}#deadbeef0000", 5))
    assert (msgs(recs), bad) == (["e1", "e2"], 0)


def test_partial_first_line_has_no_signature(tmp_path: Path) -> None:
    write(tmp_path / ACTIVE, line(1)[:8])
    _, cur, _ = read_new_lines(tmp_path, LogCursor(ACTIVE, 0))
    assert cur == LogCursor(ACTIVE, 0)
    write(tmp_path / ACTIVE, line(1)[8:] + line(2))
    recs, cur, _ = read_new_lines(tmp_path, cur)
    assert msgs(recs) == ["e1", "e2"]
    assert cur == cursor_at(line(1), len((line(1) + line(2)).encode()))

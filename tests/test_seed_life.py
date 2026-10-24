"""`seed-life` 시드 가져오기 (SP3-4 스펙 12장, 티켓 12). 고정 자료는 꾸며 낸 내용만 쓴다."""

from __future__ import annotations

import copy
import io
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Self

import pytest

from my_planner.clock import FakeClock
from my_planner.curve import seed
from my_planner.curve.seed import (
    EXIT_ALREADY,
    EXIT_BAD_FILE,
    EXIT_NOT_REVIEWED,
    EXIT_OK,
    EXIT_RUNNING,
    RUNNING_MESSAGE,
    load_seed,
    plan_import,
    run_seed_life,
)
from my_planner.platform.windows import AlreadyRunning, SingleInstanceLock
from my_planner.store.db import open_db

FIXTURE = Path(__file__).parent / "fixtures" / "life_seed_example.json"
NOW = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)


class NoLock:
    """잠금 없는 대신(Windows가 아니면 진짜 잠금도 아무것도 하지 않는다). 잡은 경로를 남긴다."""

    paths: ClassVar[list[Path]] = []

    def __init__(self, path: Path) -> None:
        NoLock.paths.append(path)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


class HeldLock(NoLock):
    def __enter__(self) -> Self:
        raise AlreadyRunning("held")


def fixture_seed() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def write_seed(tmp_path: Path, data: dict, name: str = "my.seed.json") -> Path:
    p = tmp_path / "data" / "seed" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def run(root: Path, file: Path, *, dry_run: bool = False, lock=NoLock) -> tuple[int, str]:
    out = io.StringIO()
    code = run_seed_life(root, file, dry_run=dry_run, out=out, lock_factory=lock, clock=FakeClock(NOW))
    return code, out.getvalue()


def db(root: Path) -> sqlite3.Connection:
    return open_db(root / "state" / "planner.db")


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


CURVE_TABLES = ("curve_chapters", "curve_milestones", "curve_area_defaults", "curve_questions",
                "curve_area_scores", "curve_ladder_scores", "status_titles", "status_xp_ledger")


def table_counts(root: Path) -> dict[str, int]:
    path = root / "state" / "planner.db"
    if not path.exists():
        return {}
    c = db(root)
    try:
        have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        out = {t: count(c, t) for t in CURVE_TABLES if t in have}
        if "app_state" in have:
            out["seeded"] = c.execute(
                "SELECT COUNT(*) FROM app_state WHERE key = 'life_seed_imported_at'").fetchone()[0]
        return out
    finally:
        c.close()


# --- 1. 검토 표시, 확인 규칙, 가져오지 않는 것 ---


def test_not_reviewed_imports_nothing_code_5(tmp_path):
    for reviewed in (False, None, "true", 1):
        data = fixture_seed()
        if reviewed is None:
            del data["meta"]["reviewed"]
        else:
            data["meta"]["reviewed"] = reviewed
        code, out = run(tmp_path, write_seed(tmp_path, data))
        assert code == EXIT_NOT_REVIEWED == 5
        assert "가져올 것" not in out
        assert not any(table_counts(tmp_path).values())


def test_sensitive_and_storage_only_when_confirmed(tmp_path):
    plan = plan_import(fixture_seed())
    assert plan.skipped["sensitive_unconfirmed"] == 1
    assert plan.skipped["storage_unconfirmed"] == 1
    # 확인한 민감 사건은 들어가고, 확인한 민감·storage 영역 퀘스트도 들어간다
    assert [e.sensitive for e in plan.events].count(True) == 1
    assert set(plan.quests) == {"career", "finance", "health", "relationships", "learning", "quality_of_life"}

    data = fixture_seed()
    del data["areas"][1]["confirmed"]  # finance: 민감, 확인 안 함
    del data["areas"][3]["confirmed"]  # relationships: storage, 확인 안 함
    data["chapters"][0]["storage"] = "local_only"  # 챕터도 같은 규칙
    data["events"][3]["confirmed"] = False  # true만 확인이다
    plan = plan_import(data)
    assert set(plan.quests) == {"career", "health", "learning", "quality_of_life"}
    assert [c.seed_key for c in plan.chapters] == ["C2", "C3"]
    assert plan.skipped["sensitive_unconfirmed"] == 3
    assert plan.skipped["storage_unconfirmed"] == 3
    assert not any(e.sensitive for e in plan.events)


def test_scores_and_ladder_not_imported(tmp_path):
    code, _ = run(tmp_path, FIXTURE)
    assert code == EXIT_OK
    c = db(tmp_path)
    assert count(c, "curve_area_scores") == 0
    assert count(c, "curve_ladder_scores") == 0
    quests = dict(c.execute("SELECT area, recovery_quest FROM curve_area_defaults").fetchall())
    assert quests["career"] == fixture_seed()["areas"][0]["quest"]
    assert len(quests) == 6


# --- 2. 옮기는 규칙 ---


def test_turning_maps_to_turning_point_and_certainty_mapping(tmp_path):
    assert run(tmp_path, FIXTURE)[0] == EXIT_OK
    c = db(tmp_path)
    rows = c.execute("SELECT date_text, precision, sort_date, kind, certainty, kind_certainty, status, origin, "
                     "confirmed_at, draft_since FROM curve_milestones ORDER BY sort_date").fetchall()
    assert [(r["date_text"], r["kind"], r["certainty"], r["kind_certainty"]) for r in rows] == [
        ("2012", "high", "fact", "fact"),
        ("2014-03", "turning_point", "estimate", "estimate"),
        ("2016-07", "low", "fact", "fact"),
        ("2021-05", "low", "fact", "estimate"),
    ]
    assert rows[0]["precision"] == "year" and rows[0]["sort_date"] == "2012-01-01"
    assert all((r["status"], r["origin"], r["draft_since"]) == ("confirmed", "seed", None) for r in rows)
    assert all(r["confirmed_at"] for r in rows)
    chapters = c.execute("SELECT seed_key, certainty, status, origin, theme, end_month, source_ref "
                         "FROM curve_chapters ORDER BY start_month").fetchall()
    assert [(r["seed_key"], r["certainty"]) for r in chapters] == [("C1", "fact"), ("C2", "estimate"), ("C3", "fact")]
    assert all((r["status"], r["origin"]) == ("confirmed", "seed") for r in chapters)
    assert chapters[0]["theme"] == fixture_seed()["chapters"][0]["note"]
    assert chapters[0]["source_ref"] == fixture_seed()["chapters"][0]["source"]
    assert chapters[2]["end_month"] is None


def test_skipped_chapter_nulls_event_chapter_id(tmp_path):
    data = fixture_seed()
    data["chapters"][1]["sensitive"] = True  # C2: 민감, 확인 안 함 → 건너뜀
    data["events"][5]["chapter_id"] = "C9"  # 없는 챕터도 NULL (이 사건은 어차피 건너뛴다)
    data["events"][0]["chapter_id"] = "C9"
    plan = plan_import(data)
    by_date = {e.date_text: e.chapter_key for e in plan.events}
    assert by_date == {"2012": None, "2014-03": None, "2016-07": None, "2021-05": "C3"}
    assert run(tmp_path, write_seed(tmp_path, data))[0] == EXIT_OK
    c = db(tmp_path)
    got = dict(c.execute(
        "SELECT m.date_text, ch.seed_key FROM curve_milestones m LEFT JOIN curve_chapters ch ON ch.id = m.chapter_id"
    ).fetchall())
    assert got == {"2012": None, "2014-03": None, "2016-07": None, "2021-05": "C3"}


def test_titles_for_high_and_turning_no_xp(tmp_path):
    code, _ = run(tmp_path, FIXTURE)
    assert code == EXIT_OK
    c = db(tmp_path)
    titled = c.execute(
        "SELECT m.kind FROM status_titles t JOIN curve_milestones m ON m.id = t.milestone_id ORDER BY m.sort_date"
    ).fetchall()
    assert [r[0] for r in titled] == ["high", "turning_point"]
    assert count(c, "status_xp_ledger") == 0
    assert count(c, "activity") == 0  # 활동 기록·칭호 이벤트를 남기지 않는다
    # 칭호가 겹치지 않는다(사건마다 하나)
    assert c.execute("SELECT COUNT(DISTINCT milestone_id) FROM status_titles").fetchone()[0] == 2


def test_questions_are_open(tmp_path):
    assert run(tmp_path, FIXTURE)[0] == EXIT_OK
    c = db(tmp_path)
    rows = c.execute("SELECT text, status, asked_at, answered_at FROM curve_questions ORDER BY id").fetchall()
    assert [r["text"] for r in rows] == fixture_seed()["questions"]
    assert all((r["status"], r["asked_at"], r["answered_at"]) == ("open", None, None) for r in rows)


def test_sketch_goes_to_chapter(tmp_path):
    assert run(tmp_path, FIXTURE)[0] == EXIT_OK
    c = db(tmp_path)
    got = dict(c.execute("SELECT seed_key, sketch FROM curve_chapters").fetchall())
    assert got == {s["chapter_id"]: s["direction"] for s in fixture_seed()["curve_sketch"]}
    # 내보내기 파일이 생기고 민감 사건은 가린다
    exported = (tmp_path / "data" / "curve" / "chapters.md").read_text(encoding="utf-8")
    assert "(민감)" in exported
    assert fixture_seed()["events"][3]["title"] not in exported


# --- 3. 한 번만, 잠금 ---


def test_second_run_code_4(tmp_path):
    assert run(tmp_path, FIXTURE) == (EXIT_OK, run_output(3, 4, 6, 2, 1, 1, 2) + "가져왔어요.\n")
    before = table_counts(tmp_path)
    code, out = run(tmp_path, FIXTURE)
    assert code == EXIT_ALREADY == 4
    assert "가져올 것" not in out
    assert table_counts(tmp_path) == before
    code, _ = run(tmp_path, FIXTURE, dry_run=True)
    assert code == EXIT_ALREADY


def test_running_be_code_3_with_message(tmp_path):
    assert RUNNING_MESSAGE == "my-planner가 실행 중이에요. 작업 스케줄러에서 멈춘 뒤 다시 실행해 주세요."
    NoLock.paths = []
    code, out = run(tmp_path, FIXTURE, lock=HeldLock)
    assert code == EXIT_RUNNING == 3
    assert out == RUNNING_MESSAGE + "\n"
    assert NoLock.paths == [tmp_path.resolve() / "state" / "my-planner.lock"]
    assert not any(table_counts(tmp_path).values())


def test_lock_file_matches_app():
    from my_planner import app

    assert (seed.LOCK_FILE, seed.DB_FILE) == (app.LOCK_FILE, app.DB_FILE)


@pytest.mark.skipif(sys.platform != "win32", reason="msvcrt 잠금은 Windows 전용")
def test_second_instance_real_lock(tmp_path):
    with SingleInstanceLock(tmp_path / "state" / "my-planner.lock"):
        out = io.StringIO()
        code = run_seed_life(tmp_path, FIXTURE, dry_run=False, out=out)
    assert code == EXIT_RUNNING
    assert not any(table_counts(tmp_path).values())


# --- 4. --dry-run ---


def run_output(ch: int, ev: int, q: int, qs: int, sens: int, stor: int, inv: int) -> str:
    return (f"가져올 것: 챕터 {ch}, 사건 {ev}, 영역 퀘스트 {q}, 질문 {qs}\n"
            f"건너뛸 것: {sens + stor + inv} (sensitive_unconfirmed {sens}, storage_unconfirmed {stor}, "
            f"invalid {inv})\n")


def _texts(data: dict) -> list[str]:
    out: list[str] = []
    for c in data["chapters"]:
        out += [c["title"], c["note"], c["source"]]
    for e in data["events"]:
        out += [e["title"], e["source"]] + ([e["note"]] if e.get("note") else [])
    for a in data["areas"]:
        out += [a["quest"], a["evidence"]]
    for s in data["curve_sketch"]:
        out.append(s["direction"])
    return out + data["questions"]


def test_dry_run_counts_only_no_content(tmp_path):
    code, out = run(tmp_path, FIXTURE, dry_run=True)
    assert code == EXIT_OK
    assert out == run_output(3, 4, 6, 2, 1, 1, 2) + "--dry-run: 아무것도 쓰지 않았어요.\n"
    for text in _texts(fixture_seed()):
        assert text not in out
    assert not any(table_counts(tmp_path).values())
    # 정상 실행도 개수만
    code, out = run(tmp_path, FIXTURE)
    assert code == EXIT_OK
    for text in _texts(fixture_seed()):
        assert text not in out


# --- 5. 파일 읽기와 틀린 항목 ---


def test_bom_file_reads(tmp_path):
    p = tmp_path / "data" / "seed" / "bom.seed.json"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\xef\xbb\xbf" + FIXTURE.read_bytes())
    assert load_seed(p)["meta"]["reviewed"] is True
    code, out = run(tmp_path, p, dry_run=True)
    assert code == EXIT_OK and out.startswith("가져올 것: 챕터 3")


def test_invalid_items_counted_not_printed(tmp_path):
    plan = plan_import(fixture_seed())
    assert plan.skipped["invalid"] == 2  # '2019-13', kind 'peak'

    data = fixture_seed()
    data["chapters"].append({"id": "C4", "title": "끝이 시작보다 앞선 챕터", "start": "2025-05", "end": "2024-01"})
    data["chapters"].append({"id": "C1", "title": "겹친 id 챕터", "start": "2025-05"})
    data["chapters"].append({"title": "id 없는 챕터", "start": "2025-05"})
    data["events"].append({"date": "2020-02-30", "title": "없는 날", "kind": "low"})
    data["events"].append({"date": "2020", "kind": "low"})  # 제목 없음
    data["events"].append({"date": "2020", "title": "틀린 확실성", "kind": "low", "certainty": "아마"})
    data["events"].append("문자열 사건")
    data["areas"].append({"key": "hobby", "quest": "모르는 영역"})
    data["areas"].append({"key": "career", "quest": "겹친 영역"})
    data["areas"].append({"key": "health", "quest": "가" * 81})
    data["questions"].append("")
    data["curve_sketch"].append({"chapter_id": "C1", "direction": 3})
    plan = plan_import(data)
    assert plan.skipped["invalid"] == 2 + 12
    assert len(plan.chapters) == 3 and len(plan.events) == 4 and len(plan.quests) == 6
    assert len(plan.questions) == 2

    code, out = run(tmp_path, write_seed(tmp_path, data), dry_run=True)
    assert code == EXIT_OK
    assert "invalid 14)" in out
    for text in ["2019-13", "peak", "hobby", "없는 날", "틀린 확실성", "모르는 영역"]:
        assert text not in out


def test_not_json_code_6(tmp_path):
    p = tmp_path / "data" / "seed" / "bad.seed.json"
    p.parent.mkdir(parents=True)
    cases = [b'{"meta": {"reviewed": true}, "chapters": [', b"[1, 2]", b'"secret words"', b"\xff\xfe\x00bad"]
    for raw in cases:
        p.write_bytes(raw)
        code, out = run(tmp_path, p)
        assert code == EXIT_BAD_FILE == 6
        assert "secret" not in out and "chapters" not in out
    code, _ = run(tmp_path, tmp_path / "missing.seed.json")
    assert code == EXIT_BAD_FILE
    assert not any(table_counts(tmp_path).values())


def test_plan_import_is_pure():
    data = fixture_seed()
    before = copy.deepcopy(data)
    plan_import(data)
    assert data == before


def test_cli_seed_life_dispatch(tmp_path, monkeypatch, capsys):
    from my_planner import cli

    monkeypatch.setenv("MY_PLANNER_ROOT", str(tmp_path))
    assert cli.main(["seed-life", str(FIXTURE), "--dry-run"]) == EXIT_OK
    assert capsys.readouterr().out.endswith("--dry-run: 아무것도 쓰지 않았어요.\n")
    with pytest.raises(SystemExit) as e:
        cli.main(["seed-life", "--help"])
    assert e.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


# --- 리뷰 1차: 필수 키, ASCII 숫자, DB 제약, 한 트랜잭션 ---


@pytest.mark.parametrize(("section", "index", "key"), [
    ("events", 0, "sensitive"), ("events", 0, "certainty"), ("events", 1, "kind_certainty"),
    ("events", 0, "chapter_id"), ("events", 0, "source"),
    ("chapters", 0, "certainty"), ("chapters", 0, "end"), ("chapters", 0, "note"), ("chapters", 0, "source"),
    ("areas", 0, "sensitive"), ("areas", 0, "score"), ("areas", 0, "evidence"), ("areas", 0, "label"),
    ("areas", 0, "quest"), ("curve_sketch", 0, "certainty"),
])
def test_missing_required_key_is_invalid(section, index, key):
    data = fixture_seed()
    del data[section][index][key]
    plan = plan_import(data)
    assert plan.skipped["invalid"] == 2 + 1
    assert plan.skipped["sensitive_unconfirmed"] == 1 and plan.skipped["storage_unconfirmed"] == 1


def test_unconfirmed_sensitive_without_key_is_not_imported():
    data = fixture_seed()
    del data["events"][4]["sensitive"]  # 확인하지 않은 민감 고점에서 키만 빠졌다
    plan = plan_import(data)
    assert len(plan.events) == 4
    assert plan.skipped["invalid"] == 3
    assert data["events"][4]["title"] not in [e.title for e in plan.events]


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_non_bool_sensitive_is_invalid(value):
    data = fixture_seed()
    data["events"][0]["sensitive"] = value
    data["areas"][0]["sensitive"] = value
    plan = plan_import(data)
    assert plan.skipped["invalid"] == 2 + 2
    assert len(plan.events) == 3 and "career" not in plan.quests


def test_full_width_digits_and_day_dates_are_invalid(tmp_path):
    data = fixture_seed()
    data["chapters"][2]["start"] = "２０２０-０１"
    data["events"][0]["date"] = "２０１２"
    data["events"][2]["date"] = "2016-07-03"  # 12장 모양은 'YYYY' | 'YYYY-MM'
    plan = plan_import(data)
    assert plan.skipped["invalid"] == 2 + 3
    code, out = run(tmp_path, write_seed(tmp_path, data))
    assert code == EXIT_OK
    assert "Traceback" not in out
    assert not db(tmp_path).execute("SELECT 1 FROM curve_milestones WHERE date_text NOT GLOB '[0-9]*'").fetchall()


def test_db_error_during_apply_rolls_back_code_6(tmp_path, monkeypatch):
    from my_planner.store.repos.curve import CurveRepo

    def boom(self, text):
        raise sqlite3.IntegrityError("CHECK constraint failed")

    monkeypatch.setattr(CurveRepo, "add_question", boom)
    code, out = run(tmp_path, FIXTURE)
    assert code == EXIT_BAD_FILE
    assert out.endswith(seed.DB_REJECTED_MESSAGE + "\n")
    assert "CHECK" not in out
    counts = table_counts(tmp_path)
    assert counts and not any(counts.values())  # 챕터·사건·칭호·표시 모두 되돌려졌다
    monkeypatch.undo()
    assert run(tmp_path, FIXTURE)[0] == EXIT_OK  # 표시가 없으니 다시 가져올 수 있다

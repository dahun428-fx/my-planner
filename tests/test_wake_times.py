"""`python -m my_planner.wake_times`: 깨우기 작업 트리거 시각 (스펙 5.1, 티켓 13)."""

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run_cli(root: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID")}
    env["MY_PLANNER_ROOT"] = str(root)
    return subprocess.run(
        [sys.executable, "-m", "my_planner.wake_times"],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=60, check=False,
    )


def test_wake_times_output(tmp_path):
    # 저장소의 config.toml(기본 시각) 그대로. .env는 없다: 비밀값 없이 시각만 읽는다
    shutil.copy(REPO / "config.toml", tmp_path / "config.toml")
    out = run_cli(tmp_path)
    assert out.returncode == 0, out.stderr
    # 일요일 회고 18:00은 주말 저녁 18:00과 같아서 한 번만 나온다
    assert out.stdout.splitlines() == [
        "weekday 08:55", "weekday 17:25", "weekend 09:55", "weekend 17:55", "daily 07:25", "daily 21:25",
    ]


def test_wake_times_review_added_when_it_differs(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[schedule.review.week]\nday = "sun"\ntime = "20:00"\n', encoding="utf-8"
    )
    out = run_cli(tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == [
        "weekday 08:55", "weekday 17:25", "weekend 09:55", "weekend 17:55", "weekend 19:55", "daily 07:25", "daily 21:25",
    ]


def test_wake_times_follow_changed_run_times(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[schedule.morning_brief]\nweekday = "07:30"\nweekend = "11:00"\n'
        '[schedule.evening_checkin]\nweekday = "21:00"\nweekend = "19:10"\n',
        encoding="utf-8",
    )
    out = run_cli(tmp_path)
    assert out.returncode == 0, out.stderr
    # 회고(일 18:00 기본)는 주말 저녁 19:10과 달라서 따로 나온다
    assert out.stdout.splitlines() == [
        "weekday 07:25", "weekday 20:55", "weekend 10:55", "weekend 17:55", "weekend 19:05", "daily 07:25", "daily 21:25",
    ]


def write_digest_db(root: Path, value: str) -> None:
    (root / "state").mkdir()
    conn = sqlite3.connect(root / "state" / "planner.db")
    conn.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO app_state VALUES ('digest_settings', ?)", (value,))
    conn.commit()
    conn.close()


def test_digest_times_are_daily_lines_and_off_ones_are_dropped(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[schedule.digest]\nmorning = "08:00"\nnight_on = false\n', encoding="utf-8"
    )
    out = run_cli(tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[-1:] == ["daily 07:55"]
    assert not any(line.startswith("daily 21") for line in out.stdout.splitlines())


def test_digest_db_settings_override_config(tmp_path):
    shutil.copy(REPO / "config.toml", tmp_path / "config.toml")
    write_digest_db(
        tmp_path, '{"morning": {"on": false, "time": "07:30"}, "night": {"on": true, "time": "22:00"}}'
    )
    out = run_cli(tmp_path)
    assert out.returncode == 0, out.stderr
    daily = [line for line in out.stdout.splitlines() if line.startswith("daily")]
    assert daily == ["daily 21:55"]


def test_digest_db_json_broken_falls_back_to_config(tmp_path):
    shutil.copy(REPO / "config.toml", tmp_path / "config.toml")
    write_digest_db(tmp_path, "{not json")
    out = run_cli(tmp_path)
    assert out.returncode == 0, out.stderr
    assert [line for line in out.stdout.splitlines() if line.startswith("daily")] == ["daily 07:25", "daily 21:25"]


def test_daily_and_weekday_same_time_both_kept_but_same_kind_deduped(tmp_path):
    from datetime import time

    from my_planner.config import ScheduleConfig
    from my_planner.loop.digests import DigestSetting
    from my_planner.wake_times import wake_times

    sched = ScheduleConfig.model_validate({"evening_checkin": {"weekday": "21:30", "weekend": "19:00"}})
    digests = {
        "morning": DigestSetting(True, time(21, 30)),
        "night": DigestSetting(True, time(21, 30)),
    }
    out = wake_times(sched, digests=digests)
    assert ("weekday", time(21, 25)) in out
    assert out.count(("daily", time(21, 25))) == 1

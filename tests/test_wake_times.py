"""`python -m my_planner.wake_times`: 깨우기 작업 트리거 시각 (스펙 5.1, 티켓 13)."""

import os
import shutil
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
    assert out.stdout.splitlines() == ["weekday 08:55", "weekday 17:25", "weekend 09:55", "weekend 17:55"]


def test_wake_times_review_added_when_it_differs(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[schedule.review.week]\nday = "sun"\ntime = "20:00"\n', encoding="utf-8"
    )
    out = run_cli(tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == [
        "weekday 08:55", "weekday 17:25", "weekend 09:55", "weekend 17:55", "weekend 19:55",
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
        "weekday 07:25", "weekday 20:55", "weekend 10:55", "weekend 17:55", "weekend 19:05",
    ]

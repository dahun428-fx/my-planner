"""ci.yml의 paths-filter 정의가 빠지지 않게 지킨다(PyYAML 없이 글자로 확인)."""

from __future__ import annotations

from pathlib import Path

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

EXPECTED = """\
            be:
              - 'src/**'
              - 'tests/**'
              - 'scripts/**'
              - 'requirements.lock'
              - 'pyproject.toml'
              - 'config.toml'
            workflow:
              - '.github/workflows/ci.yml'
            # web/shared/global.css와 DESIGN.md가 바뀌면 두 사본 시험(sync-design.test.mjs)이 돌아야 한다
            web:
              - 'web/app/**'
              - 'web/shared/**'
              - 'DESIGN.md'
            dashboard:
              - 'web/dashboard/**'
              - 'web/shared/**'
              - 'DESIGN.md'
"""


def test_paths_filter_definitions_present() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "          filters: |\n" + EXPECTED in text


def test_job_names_and_workflow_name() -> None:
    text = CI.read_text(encoding="utf-8")
    assert text.startswith("name: ci\n")
    for name in ("be (ubuntu-latest)", "be (windows-latest)", "web-app", "web-dashboard"):
        assert f"    name: {name}\n" in text

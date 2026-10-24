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
            workflow:
              - '.github/workflows/ci.yml'
            web:
              - 'web/app/**'
"""


def test_paths_filter_definitions_present() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "          filters: |\n" + EXPECTED in text


def test_job_names_and_workflow_name() -> None:
    text = CI.read_text(encoding="utf-8")
    assert text.startswith("name: ci\n")
    for name in ("be (ubuntu-latest)", "be (windows-latest)", "web-app"):
        assert f"    name: {name}\n" in text

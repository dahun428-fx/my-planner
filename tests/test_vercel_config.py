"""두 Vercel 프로젝트는 main과 develop만 배포한다 (배포 흐름 스펙 5.1)."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("project", ["web/app", "web/dashboard"])
def test_only_main_and_develop_deploy(project):
    config = json.loads((ROOT / project / "vercel.json").read_text(encoding="utf-8"))
    assert config["git"]["deploymentEnabled"] == {"**": False, "main": True, "develop": True}
    assert "ignoreCommand" in config  # 폴더가 안 바뀐 develop·main 푸시는 건너뛴다

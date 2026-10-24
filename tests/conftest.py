import pytest

from my_planner.store.db import migrate, open_db
from my_planner.store.repos.state import StateRepo


def pytest_addoption(parser):
    parser.addoption(
        "--update-app-golden", action="store_true", default=False,
        help="tests/fixtures/app_golden/의 운영 앱 기준 응답을 지금 스트림으로 다시 쓴다(SP3-4 16장)",
    )


@pytest.fixture
def update_app_golden(request):
    return request.config.getoption("--update-app-golden")


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "state" / "planner.db")
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def state(conn):
    return StateRepo(conn)


@pytest.fixture(autouse=True)
def _reset_logging():
    """setup_logging이 붙인 핸들러를 테스트마다 떼어 낸다(임시 폴더의 파일을 닫는다)."""
    import logging

    yield
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_my_planner_handler", False):
            root.removeHandler(h)
            h.close()

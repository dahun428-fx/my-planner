"""공부 진도 `GET`·`PUT /api/v1/study/progress` (ADR 0024): 공부 앱(AI 듀오링고)이 기기 사이에 진도를 맞춘다.

- 이 경로는 `STUDY_TOKEN`만 받는다(`api/server.auth`가 경로 틀로 기대 토큰을 고른다). `STUDY_TOKEN`은 다른 경로에서
  `401`이고, `API_TOKEN`과 기기 토큰은 이 경로에서 `401`이다. 공부 앱은 비서의 다른 데이터에 닿지 못한다.
- 공부 앱의 출처는 `api.cors_origins`에 있어야 한다(브라우저가 부른다).
- `PUT`은 보낸 진도를 저장된 진도와 합쳐(`my_planner.study.merge`) 저장하고 합친 결과를 돌려준다. 같은 본문을
  여러 번 보내도 결과가 같아 `client_msg_id`가 없다. 쓰기는 즉시 갈래의 내부 동작 `study_merge`(`endpoint="study"`)로만
  한다. 활동 기록·경험치는 없다(비서의 XP와 공부 앱의 XP는 다른 것이다).
- 로그에는 `study_synced {lessons, devices}`만 남긴다. 진도 값과 토큰은 남기지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner import study
from my_planner.api.actions import BAD_BODY, read_json_object
from my_planner.api.models import error_response
from my_planner.store.repos.state import STUDY_PROGRESS_KEY, StateRepo
from my_planner.tools.actions import ActionRequest

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

log = logging.getLogger(__name__)

STUDY_PATH = "/api/v1/study/progress"
MSG_TOO_MANY = "진도가 너무 많아 합칠 수 없어요."


def get_study_progress(conn: sqlite3.Connection, deps: ApiDeps, request: web.Request) -> dict[str, Any]:
    return study.dump(study.load(StateRepo(conn, deps.clock).get(STUDY_PROGRESS_KEY)))


async def put_study_progress(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    body = await read_json_object(request)
    if body is None or study.parse(body) is None:  # 무엇이 틀렸는지(값)는 답에도 로그에도 넣지 않는다
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None, "안전 모드가 아니면 디스패처가 있다"
    res = deps.dispatcher.apply_action(
        ActionRequest("study_merge", {"progress": body}, actor="user", channel="app", endpoint="study")
    )
    if res.status != "applied":
        return error_response(422, "rejected", MSG_TOO_MANY)
    merged = res.body["result"]["progress"]
    log.info("study_synced", extra={"lessons": len(merged["done"]), "devices": len(merged["xp_by"])})
    return web.json_response(merged)

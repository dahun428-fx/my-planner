"""공부 진도 `GET`·`PUT /api/v1/study/progress` (ADR 0024): 공부 앱(AI 듀오링고)이 기기 사이에 진도를 맞춘다.

- 이 경로는 `STUDY_TOKEN`만 받는다(`api/server.auth`가 경로 틀로 기대 토큰을 고른다). `STUDY_TOKEN`은 다른 경로에서
  `401`이고, `API_TOKEN`과 기기 토큰은 이 경로에서 `401`이다. 공부 앱은 비서의 다른 데이터에 닿지 못한다.
- 공부 앱의 출처는 `api.cors_origins`에 있어야 한다(브라우저가 부른다).
- `PUT`은 보낸 진도를 저장된 진도와 합쳐(`my_planner.study.merge`) 저장하고 합친 결과를 돌려준다. 같은 본문을
  여러 번 보내도 결과가 같아 `client_msg_id`가 없다. 쓰기는 즉시 갈래의 내부 동작 `study_merge`(`endpoint="study"`)로만
  한다. 활동 기록·경험치는 없다(비서의 XP와 공부 앱의 XP는 다른 것이다).
- 로그에는 `study_synced {lessons, devices}`만 남긴다. 진도 값과 토큰은 남기지 않는다.

단어 설명 채점 `POST /api/v1/study/grade` (ADR 0025): 학생이 AI 용어를 자기 말로 설명하면 두뇌가 채점한다.
- 같은 `STUDY_TOKEN`, 같은 출처 규칙. 두뇌 큐에서 도구 없는 한 번 호출(`harness/study_grade`). 아무것도 저장하지 않는다.
- `400` 본문 틀림, `429 study_grade_limit` 오늘 몫 없음, `503 unavailable` 두뇌 실패(앱은 스스로 채점으로 넘어간다).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from aiohttp import web

from my_planner import study
from my_planner.api.actions import BAD_BODY, read_json_object
from my_planner.api.models import error_response
from my_planner.harness.study_grade import (
    StudyGradeFailed,
    StudyGradeLimit,
    parse_request,
)
from my_planner.store.repos.state import STUDY_PROGRESS_KEY, StateRepo
from my_planner.tools.actions import ActionRequest

if TYPE_CHECKING:
    from my_planner.api.server import ApiDeps

log = logging.getLogger(__name__)

STUDY_PATH = "/api/v1/study/progress"
STUDY_GRADE_PATH = "/api/v1/study/grade"
MSG_TOO_MANY = "진도가 너무 많아 합칠 수 없어요."
MSG_GRADE_LIMIT = "오늘 AI 채점은 다 썼어요. 내일 다시 해 주세요."
MSG_GRADE_FAILED = "지금은 AI가 채점할 수 없어요. 잠시 뒤에 다시 해 주세요."


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


async def post_study_grade(request: web.Request, deps: ApiDeps) -> web.StreamResponse:
    body = await read_json_object(request)
    req = parse_request(body) if body is not None else None
    if req is None:  # 무엇이 틀렸는지(값)는 답에도 로그에도 넣지 않는다
        return error_response(400, "invalid_request", BAD_BODY)
    assert deps.dispatcher is not None, "안전 모드가 아니면 디스패처가 있다"
    try:
        got = await deps.dispatcher.grade_study(req)
    except StudyGradeLimit:
        return error_response(429, "study_grade_limit", MSG_GRADE_LIMIT)
    except StudyGradeFailed:
        return error_response(503, "unavailable", MSG_GRADE_FAILED)
    return web.json_response(got.dump())

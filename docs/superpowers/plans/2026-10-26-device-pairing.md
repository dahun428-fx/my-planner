# 기기 연결 코드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 새 기기는 6자리 연결 코드만 넣고 연결하고, BE는 기기마다 따로 토큰을 주고 끊는다.

**Architecture:** BE는 메모리 `PairCodes`(코드 하나)와 `DeviceTokens`(sha256 → 기기 id 사전)를 `ApiDeps`에 두고, `devices` 표 쓰기는 즉시 갈래 내부 동작(`device_pair`, `device_revoke`, `device_touch`)으로 한다. 앱·대시보드 연결 화면은 기본이 코드 모드이고 토큰 모드는 링크로 남긴다.

**Tech Stack:** Python 3.12 aiohttp + pydantic, pytest; Next.js static export, vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-device-pairing-design.md` (v1.2)

## Global Constraints

- 코드·토큰 원문은 로그, 활동, 오류 응답, 동작 인자에 넣지 않는다(동작 인자는 `token_hash`만).
- API 토큰 경로 동작은 그대로(기존 시험 전부 통과). `/body`, 캘린더, `/internal/notify`는 기기 토큰을 받지 않는다.
- 화면에서는 토큰을 "열쇠"라고 부른다(지금 copy 그대로). 앱 첫 로드 180KB 상한(`npm run size`), `check:csp`, `lint:copy`, `typecheck` 통과.
- BE `pytest -q` 전체 통과, `ruff check`, `mypy`(저장소 설정대로).

## Review Focus

1. `POST /pair`만 Bearer 없이 통과하고, 그 밖 경로는 API 토큰 또는 끊지 않은 기기 토큰만 통과한다.
2. 끊은 기기 토큰은 바로 `401`(메모리 사전에서 빠짐), 그 기기의 푸시 구독은 꺼진다.
3. 틀린 코드가 `AuthLimiter`에 세어져 11번째에 `429`.
4. 옛 BE(`/pair` 없음, `401 unauthorized`)에서 앱·대시보드가 열쇠 모드로 간다.
5. 아이폰 Safari 탭에서 `#code=`를 읽지 않는다.

---

### Task D1: BE

**Files:**
- Create: `src/my_planner/store/migrations/019_devices.sql`, `src/my_planner/store/repos/devices.py`, `src/my_planner/api/devices.py`, `tests/test_api_devices.py`
- Modify: `src/my_planner/api/server.py`(auth, 경로, `ApiDeps.devices`, `ApiDeps.pair_codes`), `src/my_planner/api/models.py`(응답 모델, 스키마 묶음), `src/my_planner/api/push.py`(`device_id`), `src/my_planner/store/repos/push.py`(`upsert(device_id=)`, `disable_for_device`), `src/my_planner/tools/actions.py`(세 동작), `src/my_planner/app.py`(시작할 때 사전 읽기), `src/my_planner/cli.py`(`pair`), `tests/test_cli.py`, `README.md`

**Interfaces:**
- `DevicesRepo(conn).add(token_hash, label, client, at) -> int`, `.active() -> list[Device]`, `.revoke(id, at) -> bool`, `.touch(id, at) -> None`.
- `DeviceTokens.load(rows)`, `.lookup(token) -> int | None`, `.add(hash, id)`, `.remove(id)`, `.needs_touch(id, day) -> bool`.
- `PairCodes(clock).create() -> (code, expires_at)`, `.status() -> dict`, `.consume(code) -> bool`, `.mark_used(device)`.
- 경로·오류는 스펙 4.5 표 그대로. 응답 모델 `PairCreated`, `PairStatus`, `PairResult`, `DeviceList`.

- [ ] 스펙 9장 BE 시험을 `tests/test_api_devices.py`, `tests/test_cli.py`에 쓴다 → `pytest tests/test_api_devices.py -q` 실패 확인
- [ ] 구현 → `pytest -q` 전체 통과, `ruff check src tests`, `mypy src`
- [ ] `python -m my_planner schema > web/app/src/api/schema.json` 뒤 앱 `npm run gen:types`(있는 스크립트 이름대로)
- [ ] README "다른 기기 연결" 절: 코드로 연결, `pair` 명령, 기기 끊기

### Task D2: 운영 앱

**Files:** `web/app/src/screens/Connect.tsx`, `web/app/src/lib/connection.ts`, 새 `web/app/src/screens/Devices.tsx`·`web/app/src/pages/devices.tsx`, `web/app/src/screens/More.tsx`, `web/app/src/lib/copy.ts`, `web/app/src/api/client.ts`(`postPair`, `getDevices`, `deleteDevice`, `createPairCode`, `getPairStatus`), 시험 파일들.

- [ ] 스펙 9장 앱 시험 → 구현 → `npm test`, `npm run typecheck`, `npm run lint:copy`, `npm run check:csp`, `npm run size`

### Task D3: 대시보드

**Files:** `web/dashboard/src/lib/connection.ts`(`Conn.kind`, `Conn.deviceId`), 설정 화면, 시험.

- [ ] 연결 코드 모드, 해시, 기본 주소, 연결 지우기 때 `DELETE /devices/{this}` → `npm test`, `npm run typecheck`, `npm run build`

### Task D4: 노트북 반영(Dahun)

- [ ] 노트북 pull과 작업 다시 켜기 → 폰에서 코드 만들기 → 다른 컴퓨터 대시보드에서 연결 → 끊기 확인
- [ ] (선택) Vercel 환경 변수 `NEXT_PUBLIC_DEFAULT_BE_URL`, `NEXT_PUBLIC_DASHBOARD_URL`

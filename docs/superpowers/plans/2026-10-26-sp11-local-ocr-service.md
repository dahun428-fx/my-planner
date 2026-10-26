# SP11 로컬 OCR 서비스 Implementation Plan

> **보류 (2026-10-26).** 사진 기능은 SP10(사진 남기기 + Claude 읽기)이 먼저다. 이 계획은 SP10이 끝난 뒤 스펙 머리말의 바뀐 점(서비스를 부르는 쪽 = BE `PhotoReader`)에 맞춰 OCR-06·07을 다시 쓰고 연다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰하고, 지적을 반영한 뒤 다음 티켓으로 간다.

**Goal:** 메모 쓰기 화면에서 사진 한 장의 글자를 노트북 로컬 엔진(PaddleOCR)으로 읽어 커서 자리에 넣는다. 읽기는 BE와 따로 만들고 따로 배포하는 첫 부가 서비스 `services/ocr`가 맡는다. BE 코드는 바꾸지 않는다.

**Architecture:**
- `services/ocr`: aiohttp 서버(127.0.0.1:8790, 접두사 `/svc/ocr`), 작업 큐 하나·일꾼 하나, 엔진 어댑터(Paddle / 테스트용 가짜), 줄 맞추기, 자기 토큰·CORS·로그. 사진은 메모리에서만.
- 앱: BE 주소 + `/svc/ocr`로 부르고, 받은 글을 메모 쓰기 화면에 넣는다. 저장은 지금 메모 저장 그대로(`/api/v1/actions`).
- 배포: 서비스 전용 git worktree + `deploy.ps1`(되돌림 포함). medic 연동은 마지막 선택 티켓.

**Tech Stack:** 서비스 Python 3.12, aiohttp(BE와 같은 판), Pillow, `paddleocr==3.7.0`, `paddlepaddle==3.3.1`, `numpy==1.26.4`, `opencv-python-headless==4.11.0.86`(S1·S5로 확정), pytest, ruff. 앱은 SP9와 같다(Next.js 15 Pages Router 정적 내보내기, Vitest, Playwright).

**Spec:** [`docs/superpowers/specs/2026-10-26-sp11-local-ocr-service-design.md`](../specs/2026-10-26-sp11-local-ocr-service-design.md) (v1.1). 결정 [ADR 0016](../../adr/0016-add-on-services-run-beside-be.md). 상위: [SP9](../specs/2026-10-25-sp9-app-tabs-memo-schedule-design.md) 6장·9.4, [SP5](../specs/2026-10-24-sp5-ops-app-design.md), [배포 흐름](../specs/2026-10-24-release-flow-design.md).
- 스펙과 이 계획이 다르면 스펙이 맞다. 티켓은 스펙을 다시 쓰지 않고 절을 가리킨다.

## Global Constraints

- **스펙 15장 Q1~Q5에 Dahun이 답하기 전에는 OCR-01 이후를 시작하지 않는다.** OCR-00(스파이크)만 먼저 한다.
- (ADR 0016) `src/my_planner/**`, `src/my_planner_medic/**`(OCR-09 전), 마이그레이션, BE `config.toml`을 바꾸지 않는다. 모든 티켓 끝에 `git diff origin/develop --stat -- src/ config.toml requirements.lock pyproject.toml` → 출력 없음.
- (5.3·10장) 사진을 디스크에 쓰지 않는다. 로그에 글자·사진·토큰을 남기지 않는다.
- (6장) 계약은 스펙 6장 그대로. 바꾸면 스펙을 먼저 고친다.
- (8장) 새 문구는 스펙 8장 그대로, 금지어 검사에 넣는다.
- 노트북 설정(`tailscale serve`, 작업 스케줄러 등록, worktree 만들기)은 스레드가 바로 하지 않는다. 명령을 적어 Dahun 확인 뒤 한다.
- 브랜치는 `origin/develop`에서, PR 대상은 `develop`.

## 작업 방식

- TDD: 슬라이스마다 테스트 → `services/ocr/.venv/Scripts/python -m pytest <노드 id> -v` FAIL → 구현 → PASS.
- 티켓 끝 검증(서비스): `cd services/ocr; .venv\Scripts\python -m pytest -q -m "not engine"` → `0 failed`, `.venv\Scripts\python -m ruff check src tests` → `All checks passed!`. 앱: `cd web/app && npm run typecheck && npm run lint:copy && npm test && npm run build && npm run check:csp` → 모두 통과.
- 서비스 개발용 가상환경: `py -3.12 -m venv services\ocr\.venv` 뒤 `pip install -r services\ocr\requirements.lock` + `pip install -e services\ocr --no-deps`. 캐시는 `services/ocr/cache/`(스펙 3장, S5).

## Review Focus

1. **사진이 디스크에 남는가**: Pillow와 Paddle 어느 쪽도 `TEMP`에 쓰지 않는지. → OCR-02 `test_no_temp_files_written`, OCR-03 `test_engine_leaves_temp_empty`(표시 `engine`)
2. **응답을 잃고 다시 물음**: iOS가 앱을 백그라운드로 보내 `done` 응답을 잃어도, `GET`은 결과를 지우지 않으므로 다시 물으면 같은 결과가 온다. 앱은 넣은 뒤에만 `DELETE`를 한 번 보내고, 같은 결과를 두 번 넣지 않는다(스펙 5.3 5번, 7.1). → OCR-02 `test_get_twice_same_result`, OCR-07 `test_lost_response_repoll_inserts_once_then_deletes`
3. **넣을 자리**: 읽는 사이에 Dahun이 글을 고치면 앵커는 스펙 7.1의 `shiftAnchor` 규칙대로 옮긴다. → OCR-07 `test_shift_anchor_cases`(앞에서 늘림·줄임, 뒤에서 바꿈, 앵커를 덮음, 범위 밖 자르기)
4. **BE 토큰을 서비스가 받지 않음, 서비스 토큰을 BE가 받지 않음, 앱이 서비스에 BE 키를 보내지 않음** → OCR-01 `test_other_43char_token_rejected`, OCR-06 `test_ocr_requests_never_carry_be_token`, OCR-08 손 확인
5. **BE 배포가 서비스를, 서비스 배포가 BE를 건드리지 않음** → OCR-05 `deploy.ps1 -WhatIf` 출력과 OCR-08 손 확인

---

## File Structure

```
services/ocr/                         # 스펙 5.1
  pyproject.toml  requirements.lock  config.toml  .env.example  README.md
  src/my_planner_ocr/
    __main__.py      # OCR-01: serve | gen-token
    config.py        # OCR-01: config.toml + config.local.toml + 서비스 폴더 .env
    server.py        # OCR-01: 앱, 미들웨어 순서(cors → auth → 처리기), /health
    auth.py          # OCR-01: bearer_ok, AuthLimiter (BE에서 복사)
    cors.py          # OCR-01: BE api/cors.py 규칙 복사
    logs.py          # OCR-01: jsonl, 허용 키만
    imaging.py       # OCR-02: decode_and_prepare()
    jobs.py          # OCR-02: JobQueue, QueueFull
    engine.py        # OCR-02: Line, Engine 프로토콜, FakeEngine / OCR-03: PaddleEngine, check()
    layout.py        # OCR-03: lines_to_text()
    deploy_rules.py  # OCR-05
  scripts/
    register_task.ps1  check_task.ps1  task_my-planner-ocr.xml.tmpl   # OCR-04
    deploy.ps1                                                         # OCR-05
  tests/   # 스펙 12장
web/app/src/
  api/ocr.ts                      # OCR-06
  lib/shrinkImage.ts              # OCR-06
  lib/connection.ts               # OCR-06: mp.ocrToken 읽기·쓰기 (지우기는 기존 "이 기기 연결 해제"가 mp.*를 지움)
  lib/shiftAnchor.ts              # OCR-07: 스펙 7.1 넣을 자리
  screens/Settings.tsx            # OCR-06: "사진 글자 읽기" 묶음
  screens/MemoEditor.tsx          # OCR-07
  lib/copy.ts                     # OCR-06·07: 스펙 8장
.github/workflows/ci-ocr.yml      # OCR-01: 따로 된 워크플로(ci.yml은 바꾸지 않음)
.gitignore                        # OCR-01: services/ocr/cache/ 한 줄
services/ocr/requirements-ci.txt  # OCR-01
docs/spikes/2026-10-sp10.md       # OCR-00
```

## Interfaces

```python
# services/ocr/src/my_planner_ocr/engine.py
@dataclass(frozen=True)
class Line:
    text: str
    score: float
    box: tuple[float, float, float, float]   # x0, y0, x1, y1 (줄인 그림 좌표)

class Engine(Protocol):
    name: str                                 # "paddleocr 3.7.0 korean"
    def check(self) -> bool: ...              # 스펙 5.3 엔진 검사. False면 "쓸 수 없음"
    def load(self) -> None: ...
    def unload(self) -> None: ...
    def loaded(self) -> bool: ...
    def read(self, image: "PIL.Image.Image") -> list[Line]: ...   # 동기, 일꾼 스레드에서

# layout.py
def lines_to_text(lines: list[Line], *, low_score: float) -> tuple[str, int]: ...   # (text, low)

# imaging.py
class ImageError(Exception):
    code: Literal["image_too_large", "unsupported_image", "image_unreadable"]
def decode_and_prepare(data: bytes, content_type: str, *, max_mb: int, max_side_px: int) -> "PIL.Image.Image": ...

# jobs.py
JobState = Literal["queued", "running", "done", "failed"]
class QueueFull(Exception): ...                           # 429 busy
class JobQueue:
    def __init__(self, engine: Engine, clock: Callable[[], float], *, max_waiting: int,
                 timeout_s: float, ttl_s: float, idle_unload_s: float, low_score: float) -> None: ...
    def submit(self, image) -> tuple[str, int]: ...       # (job_id, ahead). 가득 차면 QueueFull
    def status(self, job_id: str) -> dict | None: ...     # 결과를 지우지 않는다
    def forget(self, job_id: str) -> bool: ...            # DELETE: 취소 또는 결과 지움
    async def run(self) -> None: ...                      # 일꾼 하나. 시간 초과 뒤에도 그 호출이 끝나야 다음 작업
```

```ts
// web/app/src/api/ocr.ts
export type OcrJob =
  | { job_id: string; state: "queued" | "running"; ahead?: number }
  | { job_id: string; state: "done"; text: string; lines: { text: string; score: number }[]; low: number; elapsed_ms: number }
  | { job_id: string; state: "failed"; error: "timeout" | "engine_error" | "no_text" };
// BE 키가 든 Conn을 받지 않는다. apiFetch/reportResult를 쓰지 않는 자체 fetch(스펙 7.3)
export type OcrResult<T> = { ok: true; data: T } | { ok: false; kind: "network" | "http"; status?: number; error?: string };
export function ocrSubmit(beUrl: string, ocrToken: string, image: Blob): Promise<OcrResult<{ job_id: string; ahead: number }>>;
export function ocrPoll(beUrl: string, ocrToken: string, jobId: string): Promise<OcrResult<OcrJob>>;
export function ocrForget(beUrl: string, ocrToken: string, jobId: string): Promise<void>;
export function ocrHealth(beUrl: string): Promise<OcrResult<{ ok: boolean; model: "loaded" | "idle" }>>;
export function ocrMessage(r: OcrResult<unknown> | OcrJob): keyof typeof copy.ocr;      // 스펙 8장 "응답 → 문구"
// web/app/src/lib/shrinkImage.ts
export function shrinkImage(file: File, opts?: { maxSide?: number; quality?: number }): Promise<Blob>;   // 스펙 7.2, 기본 2048 / 0.85
// web/app/src/lib/shiftAnchor.ts
export function shiftAnchor(prev: string, next: string, anchor: number): number;          // 스펙 7.1
```

---

## 티켓

### OCR-00 스파이크 S1~S5 (스펙 13장)

브랜치 `docs/sp10-spikes`. 코드는 `E:\ocr-local-benchmark\scripts\`(저장소 밖)에, 결과 요약만 `docs/spikes/2026-10-sp10.md`에.

- [ ] S5: 임시 venv에 잠금 후보 버전 설치, `python -c "import paddleocr, tempfile; print(paddleocr.__version__, tempfile.gettempdir())"` → `3.7.0`과 E: 경로. `(Get-ChildItem $env:LOCALAPPDATA\Temp -Recurse | Measure-Object Length -Sum).Sum`과 `%USERPROFILE%\.paddlex` 크기가 전후 같음. `pythonw`로 첫 모델 불러오기를 돌려(stdout을 파일로 돌린 상태) 종료 코드 0과 모델 내려받기 시간을 기록.
- [ ] S1: Dahun 사진 20장과 정답(Dahun이 준비. 스레드는 장수와 분류만 기록). `E:\ocr-local-benchmark\venv\Scripts\python.exe E:\ocr-local-benchmark\scripts\bench_memo_s1.py --config mobile_cpu|server_cpu|gpu` (새 스크립트, 기존 `research_metrics.py`의 CER 사용) → 설정마다 `results/memo_s1_<설정>.json`에 장별 CER, 시간, 피크 RSS. 판정: 인쇄 16장 pooled CER와 중앙 초/장으로 스펙 1장 8번 숫자, `engine.device`, 모델, `max_side_px`를 정하고, 손글씨 3장 CER > 30%면 손글씨 문구를 더해 스펙을 고친다.
- [ ] S2: Dahun 확인 뒤 `tailscale serve --bg --set-path /svc/ocr http://127.0.0.1:8790/svc/ocr`를 임시 HTTP 서버(같은 포트)로 시험. `curl -s https://<노트북>.ts.net/svc/ocr/health`, `/api/v1/health`, `/ocr-report` → 모두 200. 8MB 본문 POST와 120초 응답 → 통과. 시험 뒤 `tailscale serve --set-path /svc/ocr off`.
- [ ] S3: S2의 임시 서버가 내주는 시험 페이지 `/svc/ocr/s3`를 아이폰 Safari와 홈 화면에 추가한 상태 양쪽에서 열어, 사진 고르기(카메라/보관함), HEIC 열기, 12MP 줄이기 시간과 메모리 오류 여부, 백그라운드 뒤 이어 묻기를 확인한다. Vercel 배포는 쓰지 않는다. 판정: 페이지가 화면에 찍는 `orientation ok / heic ok / shrink <ms> / resume ok` 네 줄이 두 상태에서 모두 ok, 줄이기 3초 이하.
- [ ] S4: 모델을 올린 시험 서버를 띄운 뒤 `Get-Process python*,pythonw*,node | Select Name,Id,@{n='MB';e={[int]($_.WorkingSet64/1MB)}}`와 `(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory`를 올린 직후·한 장 처리 뒤·`idle_unload_min`(시험에서는 1분) 뒤 세 번 기록. 판정: 처리 뒤 남은 메모리 2GB 이상, 내린 뒤 서비스 RSS가 올린 직후보다 작음.
- 끝: `docs/spikes/2026-10-sp10.md`에 S1~S5 결과, 스펙 v1.1 PR.

### OCR-01 서비스 뼈대: 설정·health·인증·CORS·로그·경계·CI

- [ ] `services/ocr/pyproject.toml`, `requirements.lock`(S5 결과), `requirements-ci.txt`, `config.toml`(스펙 5.2), `.env.example`, 루트 `.gitignore`에 `services/ocr/cache/` 한 줄.
- [ ] `config.py`: `config.toml` 위에 `config.local.toml` 덮어쓰기, `.env`는 **서비스 폴더의 것만**. `OCR_TOKEN` 43자 미만이면 시작 거부(`ocr_token_missing` 로그, 종료 코드 2).
- [ ] `auth.py`·`cors.py`: BE 규칙 복사(스펙 6장). `server.py`: 미들웨어 cors → auth(`/health` 제외) → 처리기, 오류 JSON, `client_max_size = max_image_mb MiB + 64KiB`(스펙 5.2). 시작할 때 stdout·stderr를 `state/ocr/logs/stdio.log`로(스펙 5.3 6번).
- [ ] `logs.py`: 허용 키만 쓰는 jsonl(스펙 5.4).
- [ ] `__main__.py`: `serve`, `gen-token`(43자 이상 URL-safe).
- [ ] 테스트: `test_auth.py`(`test_other_43char_token_rejected` 포함), `test_cors.py`(개발용 `config.local.toml`의 스테이징 출처 포함), `test_logs.py`, `test_boundary.py`(스펙 12장, `planner.db`·`DB_PATH`·`API_TOKEN` 문자열 검사 포함), `test_config.py`(서비스 폴더 밖 `.env` 무시).
- [ ] 새 워크플로 `.github/workflows/ci-ocr.yml`(이름 `ci-ocr`, 스펙 4.5): `on.push`/`on.pull_request`의 `paths: [services/ocr/**, .github/workflows/ci-ocr.yml]`, Ubuntu, Python 3.12, `pip install -r services/ocr/requirements-ci.txt` → `pytest -q -m "not engine"`, `ruff check`. `ci.yml`은 바꾸지 않는다(medic이 `ci` 결론만 보고 BE를 배포한다). 루트 `src/` 경계 검사도 이 워크플로의 `test_boundary.py`가 저장소 루트를 읽어 한다.
- 검증: 작업 방식의 서비스 명령 → `0 failed`, `All checks passed!`. `git diff origin/develop --stat -- src/` → 없음.

### OCR-02 사진 받기와 작업 큐 (가짜 엔진)

- [ ] `engine.py`의 `Line`, `Engine` 프로토콜, `FakeEngine`(고정 줄, 지연·예외·`check()` 결과를 테스트가 정함). `PaddleEngine`은 OCR-03.
- [ ] `imaging.py`: 스펙 5.3 1번. `test_imaging.py`(EXIF 6 회전, 줄이기, 413, 415, 422, `test_no_temp_files_written`: `tempfile.tempdir`를 빈 폴더로 두고 처리 뒤 비어 있음).
- [ ] `jobs.py`: 스펙 5.3 2·3·5번, 시계 주입. `test_jobs.py`(스펙 12장 항목 전부, `test_get_twice_same_result`, `test_timeout_waits_for_call_before_next_job`, `idle_unload_s` 뒤 `unload()` 한 번).
- [ ] `server.py`에 `POST/GET/DELETE /v1/jobs`(스펙 6장). `test_server.py`: aiohttp 테스트 클라이언트로 202→done 흐름, `DELETE` 뒤 404, 429 `busy`, 8 MiB 통과·8 MiB+1 413, 503과 health `ok: false`(`FakeEngine.check()`가 False, 또는 `load()` 예외 뒤).
- 검증: 서비스 명령 → `0 failed`.

### OCR-03 Paddle 엔진과 줄 맞추기

- [ ] `engine.py`: `PaddleEngine`(스펙 5.2 `engine` 설정, S1 결정값), `check()`(스펙 5.3 엔진 검사), Paddle 로그 수준 경고 이상. 프로세스 시작 때 `PADDLE_PDX_CACHE_HOME`, `TEMP`/`TMP`를 서비스 폴더 아래로(리서치 `env.ps1`과 같은 키).
- [ ] `layout.py`: 스펙 5.3 4번. `test_layout.py`.
- [ ] `test_engine_real.py`(표시 `engine`): 합성 한국어 그림 → CER ≤ 5%, `test_engine_leaves_temp_empty`. 노트북에서 `pytest -q -m engine` → `2 passed`.
- 검증: 서비스 명령 → `0 failed`, 노트북 `-m engine` → `2 passed`.

### OCR-04 실행과 작업 스케줄러

- [ ] 단일 실행 잠금 `state/ocr/ocr.lock`(BE 방식, 코드는 복사). 두 번째 실행은 바로 끝남.
- [ ] `scripts/register_task.ps1 -Root <worktree> [-Dev]`: 작업 `my-planner-ocr`(개발용 `-dev`), 로그온·절전 복귀·5분 워치독, `pythonw -m my_planner_ocr serve`. `check_task.ps1`: 줄마다 `OK`/`FAIL`, 하나라도 `FAIL`이면 종료 코드 1. 둘 다 `.env`를 읽거나 출력하지 않는다.
- [ ] `README.md`: 설치, `gen-token`, 등록, 점검, 지우기, `tailscale serve` 명령(S2 확정판).
- 검증: 개발 PC에서 `powershell -File services\ocr\scripts\register_task.ps1 -Root <임시 폴더> -WhatIf` → 만들 작업 XML만 출력, 등록 없음.

### OCR-05 따로 배포: worktree와 deploy.ps1

- [ ] `deploy.ps1 -Name ocr -Sha <커밋> [-Dev] [-WhatIf]`(스펙 4.5 경로 표): BE 체크아웃의 사본으로 실행(`E:\my-planner\services\ocr\scripts\deploy.ps1`, 개발용은 `E:\my-planner-dev\…`). worktree가 없으면 만들 명령(`git -C E:\my-planner worktree add --detach E:\my-planner-services\ocr <sha>`)을 출력하고 멈춤(처음 한 번은 Dahun이 만든다). `git -C <worktree> checkout --detach <sha>`, `requirements.lock`이 바뀌었으면 설치, 작업 재시작, 2분 동안 `GET http://127.0.0.1:<port>/svc/ocr/health` → `ok`가 아니면 앞 커밋으로 checkout, 잠금 파일이 달랐으면 앞 잠금으로 다시 설치, 재시작, 종료 코드 1. 상태는 `E:\my-planner\state\ocr\deploy.json`(앞·지금 커밋).
- [ ] Pester가 없으므로 순수 판단 부분(바뀐 경로 → 설치 필요?, 되돌릴 때 재설치 필요?, 상태 파일 읽기)은 `deploy_rules.py`에 두고 pytest로 시험(`test_deploy_rules.py`, 잠금이 바뀐 배포를 되돌리는 경우 포함).
- 검증: `deploy.ps1 -Name ocr -Sha HEAD -WhatIf` → 할 일 목록만 출력. 서비스 명령 → `0 failed`.

### OCR-06 앱: 부르기, 사진 줄이기, 설정

- [ ] `api/ocr.ts`(자체 fetch, 스펙 7.3), `lib/shrinkImage.ts`(스펙 7.2), `connection.ts`에 `mp.ocrToken` 읽기·쓰기.
- [ ] 설정 "사진 글자 읽기" 묶음(스펙 7.4), 문구(스펙 8장), 금지어 검사.
- [ ] 테스트: 주소 만들기(`<beUrl>/svc/ocr/v1/jobs`), 401/404 키 판정, `ocrMessage`가 스펙 8장 "응답 → 문구" 표의 모든 행, `test_ocr_requests_never_carry_be_token`, 서비스 실패 뒤 BE 연결 상태 그대로, "이 기기 연결 해제" 뒤 `mp.ocrToken` 없음, `shrinkImage`가 긴 변 2,048과 8MB 재시도를 지킴(캔버스는 가짜).
- 검증: 앱 명령 → 모두 통과.

### OCR-07 앱: 메모 쓰기 화면의 사진 버튼

- [ ] `lib/shiftAnchor.ts`(스펙 7.1). `MemoEditor.tsx` 도구 줄 글 버튼 "사진", 읽는 중 띠와 취소, 넣기·앞뒤 줄바꿈·넣은 뒤 `DELETE`, 읽기 상태에서 끝날 때 넣고 저장, 135초 한도(스펙 7.3), 문구(스펙 8장).
- [ ] 테스트: 스펙 12장 앱 항목, Review Focus 2·3(`test_lost_response_repoll_inserts_once_then_deletes`, `test_shift_anchor_cases`).
- [ ] Playwright: 가짜 서비스(라우트 가로채기)로 사진 고르기 → 글 들어감 → 저장 요청 본문에 그 글.
- 검증: 앱 명령 → 모두 통과, `npm run e2e -- memos` → 통과.

### OCR-08 노트북 수용 확인 (손으로, Dahun과)

- [ ] Dahun 확인 뒤: worktree 만들기, `.env`(`gen-token`), 등록, `tailscale serve` 두 줄, 아이폰 앱 설정에 키.
- [ ] 수용 기준 1~8 확인.
  - 4번: `Stop-ScheduledTask my-planner-ocr` 뒤 앱에서 사진 → "닿지 않음" 문구, `curl.exe -s https://<노트북>.ts.net/api/v1/health -H "Authorization: Bearer <API_TOKEN>"` → `"ok": true`.
  - 5번: `curl.exe -s -o NUL -w "%{http_code}" -X POST https://<노트북>.ts.net/svc/ocr/v1/jobs -H "Authorization: Bearer <API_TOKEN>"` → `401`, 반대로 BE `/api/v1/today`에 `OCR_TOKEN` → `401`.
  - 6번: `services/ocr/` 한 줄 바꾼 커밋을 `deploy.ps1`로 배포. 전후 `Get-CimInstance Win32_Process -Filter "name='pythonw.exe'" | ? CommandLine -match 'my_planner($| )' | Select ProcessId` → 같은 pid, `state\logs\my-planner.jsonl`에 그 사이 `starting` 없음.
  - 7번: 서비스 pid의 열린 파일에 `planner.db`가 없음(`handle.exe`가 없으면 `test_boundary.py` 통과로 갈음하고 그렇게 적는다).
  - 8번: S1의 같은 20장을 앱 경로(서비스 경유)로 보내 인쇄 16장 CER와 중앙 초/장이 스펙 1장 8번 숫자 안.
- [ ] 결과를 `docs/acceptance/sp10-checklist.md`에.

### OCR-09 (선택, Dahun 결정 뒤) medic이 서비스를 배포·감시

- [ ] medic 설정에 서비스 목록(`[[services]] name, port, worktree`), `ci-<이름>` 워크플로가 성공한 `main`/`develop` 커밋 중 `services/<이름>/`가 바뀐 것에 `deploy.ps1` 호출, 서비스 health 감시와 `incident` 이슈. 이 티켓은 `src/my_planner_medic`를 바꾸므로 SP6 스펙 개정을 먼저 한다.

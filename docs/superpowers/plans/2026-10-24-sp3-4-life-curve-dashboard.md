# SP3-4 HTTP API · 인생 곡선 · 상태창 · 웹 대시보드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰한다. 지적을 반영한 뒤에 다음 티켓으로 간다.

**Goal:** 노트북의 my-planner 프로세스(BE) 안에 HTTP API `/api/v1`을 열고, 그 위에 인생 곡선과 게임형 상태창을 올리고, 폰에서도 여는 읽기 전용 웹 대시보드(Vercel)를 만든다. 텔레그램, 운영 앱, 대시보드가 같은 데이터를 보고, 쓰기는 디스패처 한 곳에서만 일어난다.

**Architecture:**
- SP1 프로세스의 asyncio 루프 하나에 aiohttp `AppRunner` + `TCPSite("127.0.0.1", 8787)`를 끼운다([ADR 0007](../../adr/0007-http-api-inside-be-single-writer.md)). 밖에서는 `tailscale serve`로만 닿는다.
- 쓰기 경로는 `Dispatcher`의 두 갈래뿐이다: 두뇌 갈래(SP1 큐, 텔레그램·앱 메시지·회차)와 즉시 갈래(신규 `Dispatcher.apply_action`, `/actions`·되돌리기·버튼·하루 한 번 작업). `GET`은 `mode=ro` 연결만 받는다.
- 대시보드는 `web/dashboard/`의 Next.js 정적 내보내기이고, 브라우저가 BE를 직접 부른다([ADR 0008](../../adr/0008-dashboard-on-vercel-browser-to-be-over-tailscale.md)).
- 계획은 **세로 티켓**(Matt Pocock `to-tickets`)으로 나눈다. 순서는 운영 앱 스레드가 기다리는 API 계약이 먼저다: 뼈대·인증·`/health` → 읽기 → `/actions`·되돌리기·활동 → `/chat` SSE → 통로 규칙 → 푸시. 그다음 곡선 데이터 계층과 `seed-life`, 두뇌 도구, 텔레그램 회고 흐름, 경험치와 상태창, 마지막으로 대시보드.
- 모든 BE 티켓의 수용 확인은 SP1 시험 이음매(`FakeBrain`, `FakeClock`, `FakeSender`, 임시 SQLite)에 이번에 더하는 `tests/be_env.py BeEnv`(실제 조립 함수 `app.build_be` + aiohttp `TestClient`)로 끝에서 끝까지 돈다.

**Tech Stack:**
- BE: Python 3.12, SP1 의존성 그대로 + `aiohttp>=3.10,<4`, `pywebpush>=2,<3`(+ `py-vapid`, `cryptography`). 개발: `hypothesis>=6`, `jsonschema>=4.23`. 정확한 판은 티켓 01·08에서 `requirements.lock`에 고정한다.
- 대시보드: Node 20 이상, **Next.js 15 Pages Router + `output: "export"`**, React, Recharts(차트), Vitest + Testing Library + MSW + jsdom, `json-schema-to-typescript`(타입 생성). 정확한 판은 티켓 16의 `package-lock.json`에 고정한다.
  - 고른 이유(한 줄): 스펙이 Next.js 정적 내보내기를 정했고(4.4, 13.1), App Router는 정적 HTML에 인라인 `<script>`(RSC 데이터)를 넣어 스펙 14장의 `script-src 'self'` CSP와 맞지 않으므로, 인라인 실행 스크립트가 없는 Pages Router로 한다.
- 화면 제작 도구: UI UX Pro Max 스킬(github `nextlevelbuilder/ui-ux-pro-max-skill`)과 taste 스킬(github `Leonxlnx/taste-skill`). 티켓 16의 디자인 단계에서 불러 쓴다(AI가 만든 티가 나는 화면을 피하려고).

**Spec:** [`docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md`](../specs/2026-10-24-sp3-4-life-curve-dashboard-design.md) (main `e610afb`, 17장 미결은 2026-10-24 Dahun이 적힌 안대로 모두 확정)
- 상위: [마스터 설계](../specs/2026-10-23-my-planner-master-design.md), [SP1 스펙](../specs/2026-10-23-sp1-secretary-core-design.md), [SP1 계획](2026-10-23-sp1-secretary-core.md)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md), 결정: [`docs/adr/`](../../adr/) 0001~0008
- 스펙과 이 계획이 다르면 스펙이 맞다. 이 계획이 스펙의 빈 곳을 정한 자리는 끝의 "스펙 빈 곳과 이 계획의 결정"에 모았다.

## Global Constraints

스펙의 문장을 그대로 옮긴다(절 번호). 모든 티켓의 요구 사항에 들어간다.

**개인 정보와 로그**
- (1장 완료 조건 3) "올바른 API 토큰이 없는 요청은 `401`이다. 허용 목록 밖 출처(Origin)에는 CORS 허용 헤더를 주지 않는다. 시스템 로그에 토큰, 메시지 본문, 할 일 제목, 도구 인자가 없다(로그 검사 테스트)."
- (14장 로그) "aiohttp 기본 접근 로그를 끈다(`access_log=None`). 대신 요청마다 `method`, **경로 틀**(`/api/v1/activity/{id}/undo`), 상태 코드, 소요 시간만 남긴다. 쿼리 문자열, 헤더, 본문, 토큰, 푸시 `endpoint`, 할 일 제목, 도구 인자는 남기지 않는다(SP1 7장 로그 규칙)."
- (14장 토큰) "토큰은 로그, 오류 응답, 활동 기록 어디에도 나오지 않는다". "빌드, Vercel 환경 변수, 저장소, 로그에는 없다."
- (14장 푸시) "`VAPID_PRIVATE_KEY`는 `.env`에만. … 구독 `endpoint`는 비밀값처럼 다룬다(로그 금지)"
- (14장 개인 데이터와 Git) "`data/`, `state/`, `.env`는 지금처럼 `.gitignore`. 이번에 `*.seed.json`, `life-seed/`, `life-curve-seed*.json`을 더한다. 시드 파일 내용, 사건, 점수는 코드, 테스트, 문서, 커밋 메시지에 넣지 않는다. 테스트 고정 자료는 꾸며 낸 내용만"
- (12장) "**시드 파일은 노트북의 `data/seed/` 아래에만 둔다**". "`--dry-run`은 … **항목 내용(제목, 메모)은 출력하지 않는다**(터미널 기록에 남지 않게)."
- (13.1) "BE URL과 API 토큰 … 둘은 그 브라우저의 `localStorage`에만 둔다(빌드나 Vercel 환경 변수에 넣지 않는다: 정적 파일은 누구나 받을 수 있다)." "서버 함수, API 라우트, 서버 렌더링 데이터 가져오기는 쓰지 않는다. … Vercel 분석, 외부 글꼴·스크립트는 넣지 않는다."

**단일 작성자 (ADR 0007, 4.3)**
- "**쓰기 경로는 `Dispatcher` 하나다.**" "**데이터**를 바꾸는 길은 위 두 갈래뿐이다." "API의 `GET` 처리기는 따로 연 **읽기 전용 연결**(`sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)`)만 받는다."
- 즉시 갈래: "동기 함수이고 안에서 `await`하지 않는다."
- "**단일 실행 잠금**(SP1 5.1 1단계, `state/my-planner.lock`)은 그대로다. API는 잠금을 잡은 프로세스 안에서만 열린다. `seed-life` CLI도 같은 잠금을 잡는다(BE가 돌고 있으면 거절, 12장)."
- 표별 작성자는 스펙 4.3 "누가 어느 표를 쓰나" 표 그대로다(티켓 15의 쓰기 경로 감시 테스트가 지킨다).

**두뇌 도구 (ADR 0005)**
- (10장) "모두 `mcp__planner__*`이고 파일·셸·웹은 여전히 없다(ADR 0005)."
- (6.4.7) 화면 도구는 "그리기만 한다: props를 카탈로그 스키마로 검증하고 `{"ok": true}`를 돌려줄 뿐, DB와 파일을 건드리지 않는다(테스트로 확인, 16장)." "**텔레그램 대화에는 `ui_*` 도구와 카드 도구(`pin_card`, `unpin_card`, `reorder_cards`, 10장)를 주지 않는다.**"
- (10장) "도구 수: 텔레그램 대화 22개(SP1 12 + 10), 앱 대화 28개(+ 화면 3, 카드 3). S12로 다시 확인한다. `max_turns=10`은 그대로 둔다."

**벌주지 않는다 (ADR 0006)**
- (9.1) "경험치가 줄어드는 길은 없다: 원장 `amount > 0` CHECK, 저장소에 UPDATE/DELETE 함수 없음, 연속 기록·기간 한정 보상 없음."
- (9장) "순수 함수 `status/xp.py`에 상수로 두고 `config.toml`로 바꾸지 않는다"
- (13.5) "연속 기록, 남은 시간, 놓친 것 수 같은 표시는 두지 않는다(ADR 0006)."
- (13.1) "화면 문구에는 SP1 금지어를 쓰지 않는다." (SP1: "놓쳤어요", "밀렸어요", "늦었지만", "실패")

**하루 상한**
- (6.4.1) "하루 두뇌 호출 상한 60회는 두 통로가 함께 쓴다."
- (6.1) "하루 두뇌 호출 상한, 사용 한도, 로그인 문제는 **오류가 아니다**. SP1처럼 고정 문구로 답한다(`/chat`의 글 조각, 6.4.1)."
- (7.3 D6) "**하루 3회 상한은 회차마다 한 번 센다.** `_run_delivered`가 `usage_state.proactive_messages`를 1 올리는 지금 자리(SP1) 그대로다. 푸시와 텔레그램을 다 보내도(D4) 하나다. 합친 회차도 SP1처럼 하나다"
- (9.2) "따로 먼저 보내는 메시지는 만들지 않는다(하루 3회 상한)." (6.4.8) "`POST /push/test` … 하루 3회 상한에 세지 않는다."

**시각과 이름**
- (6.1) "응답의 시각은 UTC ISO 8601(`2026-10-24T09:00:00Z`), 날짜는 논리적 날짜, 기간은 `priorities.period` 형식." "도구 결과 … 도 **API 경계에서 UTC로 바꾼다** … 두뇌가 받는 도구 결과는 SP1 그대로 현지 시각이다"
- 통로 값은 `telegram` | `app`, 활동 통로는 `app` | `telegram` | `scheduler`, 행위자는 `secretary` | `user`(5.2). SP1의 Global Constraints(시간대, 논리적 날짜 04:00, 영역 6개, 금지어)는 그대로다.

## 작업 방식

- SP1 계획의 TDD 주기를 그대로 쓴다. 슬라이스마다: 테스트 하나 → `python -m pytest <파일>::<테스트> -v`로 FAIL 확인(새 이름이면 `ImportError`/`AttributeError`, 새 동작이면 `AssertionError`) → 통과할 만큼 구현 → 같은 명령으로 PASS.
- 티켓 끝 검증(모든 BE 티켓 공통, 따로 적지 않는다):
  - `python -m pytest -q` → `passed`, `0 failed`(Linux에서는 Windows 전용 시험이 `skipped`). SP1의 353개 시험이 그대로 통과해야 한다(완료 조건 11). SP1 시험을 고쳐서 통과시키지 않는다.
  - `ruff check src tests` → `All checks passed!`
  - 그다음 `code-reviewer` 리뷰, 커밋.
- 생성자는 키워드 전용이고 새 인자는 기본값이 있어 SP1 호출이 그대로 돈다(`Dispatcher`, `Tools`, `Runner`, `ConversationRouter`, `TranscriptStore.append`, `ConversationsRepo.open/latest_open`).
- 사용자에게 보이는 새 문구는 스펙 부록 A와 13장 그대로다. 계획이 정한 문구는 해당 티켓에 적었다.

## Review Focus

스펙이 암시하지만 스펙의 시험 표가 다루지 않고, 사람이 쓰다가 가장 먼저 부딪힐 다섯 가지. 각 줄의 시험은 맡은 티켓의 슬라이스에 넣었다.

1. **기기 시간대가 한국이 아닌 브라우저**(PC가 UTC, 해외 여행 중 폰): 대시보드의 모든 시각은 기기 시간대와 상관없이 `Asia/Seoul`로 보인다. → 티켓 16 `time.test.ts`
2. **잘못된 쿼리 값**: `from > to`, 모르는 `zoom`, `limit=0`·`limit=1000`, 깨진 `since`, 숫자가 아닌 경로 id, `include_sensitive=yes`. 500이 아니라 `400 invalid_request`(경로 id는 `404 not_found`)이고 로그에는 경로 틀만 남는다. → 티켓 02, 03, 05
3. **BE URL 입력 모양**: 끝의 `/`, 끝에 붙인 `/api/v1`, `http://`, 앞뒤 공백, 허용 범위(`NEXT_PUBLIC_CONNECT_SRC`) 밖 주소. 앞의 셋은 정규화해 받고 `http://`와 범위 밖은 설정 화면에서 이유와 함께 거절한다. → 티켓 16 `connection.test.ts`
4. **메모장으로 고친 시드 파일**: BOM이 붙은 UTF-8, 날짜가 틀린 항목(`2019-13`), 모르는 `kind`. BOM은 읽고, 틀린 항목은 건너뛰어 이유별 개수만 출력하며, 내용은 어디에도 출력하지 않는다. JSON이 아니면 코드 6. → 티켓 10
5. **새벽(00:00~03:59) 경계**: 01:30에 끝낸 할 일은 전날 논리적 날짜의 일이라 전날의 쉬는 날(X9)을 주지 않고, 01:30에 누른 사다리 버튼은 버튼에 든 달에 기록된다. → 티켓 14, 15

---

## File Structure

```
pyproject.toml, requirements.lock, config.toml([api], [notify]), .env.example(API_TOKEN, VAPID_*), README.md(19)
docs/spikes/2026-11-sp3-4.md (00), docs/acceptance/sp3-4-checklist.md (20)
src/my_planner/
  cli.py                         # argparse: (없음)→app.main, gen-token, gen-vapid, schema, seed-life
  __main__.py                    # raise SystemExit(cli.main())
  app.py                         # build_be()로 조립을 뽑고 API 수명을 시작·종료 순서에 넣는다
  config.py                      # ApiConfig, NotifyConfig, VapidConfig, api_token
  domain.py                      # Channel, ActivityChannel, Actor, RunContext 새 필드
  api/{server,auth,cors,models,read,chat,actions,push,health}.py
  harness/{stream,delivery,checkins,review_steps}.py, harness/prompts/{review_month,review_quarter,review_year,channel_app}.md
  curve/{model,seed}.py
  status/{xp,snapshot}.py
  store/db.py(open_ro), store/views.py, store/migrations/006~010_*.sql
  store/repos/{curve,status,activity,push,cards,channels}.py
  tools/{actions,activity,ui}.py, tools/core.py(곡선·상태창·카드 메서드), tools/mcp_adapter.py(call_tool, tool_names_for)
tests/
  be_env.py(BeEnv), fakes.py(+ ListSink, FakePushSender, FakeTurn.deltas), ui_stream.py(SSE 파서)
  test_api_*.py, test_dispatcher_channels.py, test_delivery.py, test_curve_*.py, test_status_*.py,
  test_seed_life.py, test_review_steps.py, test_telegram_*.py, test_write_paths.py, test_dashboard_fixtures.py
  fixtures/life_seed_example.json (꾸며 낸 내용)
web/dashboard/                   # Vercel 루트 디렉터리
  package.json, next.config.mjs, vercel.json, tsconfig.json, scripts/check-csp.mjs
  src/pages/{_app,_document,index,tasks,curve,status,settings}.tsx
  src/{lib,components,screens,styles,api,test}/
```

## 티켓 지도

| # | 티켓 | 막는 티켓 | 라벨 |
|---|---|---|---|
| 00 | 착수 전 검증 (S7~S12) | 없음 | `ready-for-agent`(클라우드 원형) + `needs-laptop`(S7·S8·S9·S10 기기 부분) |
| 01 | API 뼈대: 마이그레이션, 인증·CORS·로그, `/health` | 00(클라우드 부분) | `ready-for-agent` |
| 02 | 읽기 API: 할 일·컨디션·답할 회차·대화·카탈로그·스키마 | 01 | `ready-for-agent` |
| 03 | 읽기 API: `/curve`, `/status` 읽기 모델 | 02 | `ready-for-agent` |
| 04 | 즉시 갈래와 활동 기록, `POST /actions` | 02 | `ready-for-agent` |
| 05 | 되돌리기와 `GET /activity` | 04 | `ready-for-agent` |
| 06 | 앱 채팅 `POST /chat` (UI message stream) | 05, 00(S11) | `ready-for-agent` |
| 07 | 통로별 대화 규칙, 가르기, 답한 회차 | 06 | `ready-for-agent` |
| 08 | 웹 푸시와 회차 전달 (D1~D8) | 07 | `ready-for-agent` |
| 09 | 인생 곡선 데이터 계층 | 03, 05 | `ready-for-agent` |
| 10 | `seed-life` 시드 가져오기 | 09 | `ready-for-agent` |
| 11 | 곡선·상태 두뇌 도구와 사건 초안 버튼 | 09, 06 | `ready-for-agent` |
| 12 | 앱 전용 두뇌 도구: 화면 조각과 고정 카드 | 06, 05 | `ready-for-agent` |
| 13 | 회차 차례의 확인 (10.1) | 12 | `ready-for-agent` |
| 14 | 회고 단계: 월말 사다리, 분기 영역 점수, 연말 | 11, 07 | `ready-for-agent` |
| 15 | 경험치, 레벨, 텔레그램 `/status`, 쓰기 경로 감시 | 14, 08, 13 | `ready-for-agent` |
| 16 | 대시보드 뼈대와 (a) 비서 상태 화면 | 03 | `ready-for-agent` |
| 17 | 대시보드 (b) 할 일 + 컨디션, (d) 상태창 | 16 | `ready-for-agent` |
| 18 | 대시보드 (c) 인생곡선 | 16 | `ready-for-agent` |
| 19 | Vercel 배포, Tailscale serve, 운영 안내 | 15, 17, 18 | `needs-laptop` |
| 20 | 노트북 수용 테스트 | 19 | `needs-laptop` |

00→01→02→(03, 04→05→06→07→08)이 운영 앱 계약 줄이고, 운영 앱 스레드는 02 뒤부터 `GET /schema`로 타입을 만들 수 있다. 09~15가 곡선·상태창 줄, 16~18은 03 뒤 어느 때나 옆길로 돈다.

---

### 티켓 00: 착수 전 검증 (S7~S12)

**목표:** 스펙 3장의 가정을 확인하고 뒤 티켓이 쓸 값을 정한다. 시험 코드는 `spikes/`(커밋하지 않음, `.gitignore`에 있음)에 두고, 결과는 `docs/spikes/2026-11-sp3-4.md`에 SP1 기록(`docs/spikes/2026-10-sp1.md`)과 같은 모양으로 남긴다. 실패한 항목은 스펙의 해당 절을 먼저 고친다.
**막는 티켓:** 없음
**라벨:** 클라우드 원형과 기록은 `ready-for-agent`, 아래 `needs-laptop` 표시 항목은 노트북(Remote Control)과 폰이 필요하다.

**Files:** Create `docs/spikes/2026-11-sp3-4.md`, `spikes/s7_loop.py`, `spikes/s8_sse.py`, `spikes/s9_pna.py`, `spikes/s10_push.py`, `spikes/s11_stream.py`, `spikes/s12_tools.py`

- [ ] **S7 같은 루프에서 HTTP + 폴링 + tick**
  - 클라우드: `s7_loop.py`가 한 루프에 aiohttp `AppRunner` + `TCPSite("127.0.0.1", 8787)`, 가짜 롱폴링 코루틴, 1분 tick(10초로 줄임), 5초 걸리는 가짜 두뇌 작업을 띄운다. `curl -s -o /dev/null -w "%{time_total}\n" http://127.0.0.1:8787/ping` 10회 → 모두 0.1초 미만(두뇌 작업 중에도).
  - `needs-laptop`: 같은 스크립트를 작업 스케줄러에서 `E:\my-planner\.venv\Scripts\pythonw.exe spikes\s7_loop.py`로 띄운다(Proactor 루프 기본). 이 루프에서 Agent SDK `query("안녕이라고만 답해")`(자식 프로세스)를 부르는 동안 `curl.exe http://127.0.0.1:8787/ping`이 답하고, 콘솔 창이 뜨지 않는다(`hide_console()` 포함).
  - 실패 시: 스펙 3장 S7 대안(API 전용 스레드 루프 + `run_coroutine_threadsafe`)으로 스펙 4.3과 티켓 01의 `start_api`를 고친다.
- [ ] **S8 SSE 버퍼링**
  - 클라우드: `s8_sse.py`가 200ms 간격 `text-delta` 20개를 `X-Accel-Buffering: no`로 보낸다. `curl -N -s http://127.0.0.1:8787/sse | ts -s '%.s'`로 조각마다 도착 시각을 적는다. 기대: 조각 간격 ≈ 0.2초.
  - `needs-laptop`: 사전 조건(tailnet 관리 화면에서 MagicDNS, HTTPS 인증서 켜기) → `tailscale serve --bg --https=443 http://127.0.0.1:8787` → 폰(셀룰러 + Tailscale)과 노트북 브라우저에서 같은 측정. 첫 `text-delta`까지 지연과 묶임 여부를 기록한다. 묶이면 15초 `: ping` 주석으로 다시 재고, 그래도 묶이면 운영 앱 스레드에 알린다.
- [ ] **S9 사설 네트워크 접근**
  - 클라우드: `s9_pna.py`가 사전 요청에 `Access-Control-Allow-Private-Network: true`로 답한다. `curl -si -X OPTIONS -H "Origin: https://example.vercel.app" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Private-Network: true" http://127.0.0.1:8787/api/v1/health` → `204`, 그 헤더 있음.
  - `needs-laptop`: Vercel 미리보기 주소의 시험 페이지에서 `fetch("https://<노트북>.<tailnet>.ts.net/api/v1/health")`를 데스크톱 Chrome, Android Chrome, iOS Safari에서 부른다. 권한 창 문구와 결과를 기록한다(티켓 19 사용자 안내에 쓴다).
- [ ] **S10 웹 푸시**
  - 클라우드: Linux에 `pip install pywebpush`, VAPID 키 생성, 로컬 가짜 푸시 서버(201·404·410 응답)로 `webpush(...)` 호출. `http_ece`로 페이로드를 풀어 원문과 같은지 확인. `TTL`, `Topic` 헤더가 실리는지 확인.
  - `needs-laptop`: Windows venv에 설치되는지, Android Chrome과 iPhone(홈 화면에 추가한 PWA, iOS 16.4 이상)에서 실제 알림을 받는지. iOS 구독이 안 되면 스펙 3장 대안대로 둔다.
- [ ] **S11 글 조각과 세션 가르기** (로그인된 Claude가 필요하다. 클라우드에 구독 로그인이 없으면 노트북에서 돌린다)
  - `include_partial_messages=True`로 `StreamEvent`가 오고, 그 안 `content_block_delta`의 `text_delta`를 이어 붙이면 최종 `ResultMessage.result`와 같다.
  - 첫 호출의 `session_id`로 `resume=<id>`, `fork_session=True` 호출: 새 `session_id`가 다르고, 첫 호출에서 알려 준 단어("암호는 바나나")를 기억한다. 원래 세션을 다시 resume하면 갈라진 쪽 대화를 모른다.
  - 실패 시: 스펙 3장 S11 대안(`text-delta` 하나, 또는 SP1 resume 실패 대체 경로)을 티켓 06·07의 기본으로 둔다.
- [ ] **S12 도구 잠금 재확인**: 더미 도구 28개(이름은 티켓 11·12·15의 실제 이름)를 등록한 in-process 서버로 SP1 S2의 두 질문을 다시 한다. 기대: 목록에 `mcp__planner__*`만, `Read`로 파일을 읽지 못한다. 22개로도 한 번.
- [ ] **기록**: 항목마다 성공 여부, 명령, 출력 요약, 정한 값. 정할 값: `aiohttp`·`pywebpush` 판, SSE 첫 조각 지연, PNA 권한 창 안내 문구, SDK의 `StreamEvent` 필드 경로, `fork_session` 사용 형식.
- [ ] **수용 확인**: 기록 문서에 S7~S12 행이 모두 있고, `needs-laptop` 행은 "노트북 대기"로라도 적혀 있다. 클라우드 행이 하나라도 실패면 스펙을 먼저 고친 커밋이 있다.
- [ ] **Commit** `docs: record SP3-4 spike results`

---

### 티켓 01: API 뼈대 — 마이그레이션, 인증·CORS·로그, `/health`

**목표:** BE가 폴링을 시작한 뒤 `127.0.0.1:8787`에 API를 연다. 토큰이 맞으면 `GET /api/v1/health`가 스펙 6.3.1 그대로 답하고, 틀리면 401, 허용 밖 출처에는 CORS 헤더가 없다. 로그에는 경로 틀만 남는다. 스펙 5장의 마이그레이션 006~010을 모두 넣는다(뒤 티켓은 표를 만들지 않고 쓰기만 한다).
**막는 티켓:** 00(클라우드 부분). S7 노트북 결과가 실패면 이 티켓의 `start_api`를 스펙 대안대로 고친다.
**라벨:** `ready-for-agent`

**Files:**
- Create: `store/migrations/006_channels.sql`, `007_activity.sql`, `008_push_cards.sql`, `009_curve.sql`, `010_status.sql`(스펙 5.1~5.5의 SQL 그대로), `cli.py`, `api/__init__.py`, `api/server.py`, `api/auth.py`, `api/cors.py`, `api/models.py`, `api/health.py`, `harness/checkins.py`, `store/repos/channels.py`, `store/repos/push.py`, `tests/be_env.py`
- Modify: `__main__.py`, `app.py`, `config.py`, `store/db.py`, `store/repos/state.py`, `store/repos/runs.py`, `store/repos/conversations.py`, `harness/dispatcher.py`(`_call_brain`), `loop/runner.py`, `config.toml`, `.env.example`, `pyproject.toml`, `requirements.lock`
- Test: `tests/test_migrations.py`, `tests/test_api_auth.py`, `tests/test_api_cors.py`, `tests/test_api_health.py`, `tests/test_api_logging.py`, `tests/test_api_readonly.py`, `tests/test_app_start.py`, `tests/test_cli.py`

**Interfaces**
- Consumes: `open_db`, `migrate`, `StateRepo`, `RunsRepo`, `Runner`, `Dispatcher`, `app._serve`, `SingleInstanceLock`, `setup_logging` (SP1)
- Produces:

`config.py`
- `ApiConfig(enabled: bool = True, host: str = "127.0.0.1", port: int = 8787, cors_origins: list[str] = [], cors_origin_regex: str = "", max_body_kb: int = 64)`
- `NotifyConfig(default_primary: Literal["telegram", "app"] = "app")`
- `Settings.api: ApiConfig`, `Settings.notify: NotifyConfig`, `Settings.api_token: SecretStr | None = None`(`_Secrets`가 `.env`의 `API_TOKEN`을 읽는다). `API_TOKEN_MIN_CHARS = 43`(`token_urlsafe(32)`의 길이).

`store/db.py`
- `open_ro(path: Path) -> sqlite3.Connection`: `sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)`, `Row` 팩토리.

`store/repos/*` (읽기 부분. 쓰기는 뒤 티켓)
- `Run`에 `answered_at: datetime | None = None`, `answered_via: str | None = None`. `RunsRepo.on_logical_date(d: date, tz, boundary) -> list[Run]`(`scheduled_for`의 논리적 날짜 기준).
- `Conversation`에 `channel: str = "telegram"`, `forked_from: int | None = None`.
- `DeliveriesRepo(conn, clock).sent_channels(run_id: int) -> list[str]`(`status='sent'`).
- `PushRepo(conn, clock).count_active() -> int`, `.last_success_at() -> datetime | None`.
- `state.py` 키: `BRAIN_AUTH_STATE_KEY = "brain_auth_state"`, `BRAIN_AUTH_CHECKED_KEY = "brain_auth_checked_at"`, `NOTIFY_PRIMARY_KEY = "notify_primary"`.
- `Dispatcher._call_brain`: 결과마다 `brain_auth_state`를 `auth_error`면 `result.error`(`login`/`billing`), 아니면 `ok`로, `brain_auth_checked_at`을 지금으로 쓴다.
- `Runner.polling_down -> bool` (지금 `_polling_down`의 공개 속성).

`harness/checkins.py`
- `CheckinState = Literal["pending", "answered", "missed"]`
- `checkin_state(run: Run, *, runs: RunsRepo, now: datetime, settings: Settings) -> CheckinState | None`: `done`이 아니면 None. 답장 창은 SP1 `reply_window_end`, 합친 회차는 묶음의 가장 늦은 끝.
- `runs_today(*, runs: RunsRepo, deliveries: DeliveriesRepo, now, settings) -> list[dict]`: 6.3.1 `runs_today` 항목.

`api/models.py`
- `ErrorResponse`, `HealthResponse`(6.3.1 필드 그대로) 등 pydantic 모델. `MODELS: dict[str, type[BaseModel]]`(티켓마다 늘어난다), `schema_bundle() -> dict`(`{"api": "v1", "models": {이름: JSON Schema}}`).
- `to_api_times(value: Any) -> Any`: dict·list를 따라가며 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?[+-]\d{2}:\d{2}$` 문자열만 UTC `…Z`로 바꾼다(날짜만 있는 문자열은 그대로).
- `error_response(status: int, code: str, message: str) -> web.Response`: `{"error": {"code", "message"}}`.

`api/auth.py`
- `bearer_ok(header: str | None, token: str) -> bool`: `Bearer <t>` 모양만, `hmac.compare_digest`.
- `AuthLimiter(clock: Clock, *, max_failures: int = 10, window: timedelta = timedelta(minutes=1))`: `.failed() -> None`, `.blocked() -> bool`(10회째부터 1분 동안 True).

`api/cors.py`
- `CorsPolicy(origins: list[str], origin_regex: str = "")`: `.allows(origin: str | None) -> bool`(정확한 문자열 또는 `re.fullmatch`).
- `cors_middleware(policy: CorsPolicy)`: `OPTIONS` 사전 요청은 토큰 없이 `204` + `Access-Control-Allow-Origin: <origin>`, `-Methods: GET, POST, PUT, DELETE`, `-Headers: Authorization, Content-Type`, `-Max-Age: 600`, `Vary: Origin`, 요청에 `Access-Control-Request-Private-Network`가 있으면 `Access-Control-Allow-Private-Network: true`. 일반 응답에는 `-Allow-Origin`, `Access-Control-Expose-Headers: x-conversation-id`, `Vary: Origin`. 허용 밖 출처는 CORS 헤더 없이 그대로 처리(토큰 검사는 그대로). 자격 증명 헤더는 주지 않는다.

`api/health.py`
- `ErrorCounter(clock: Clock, *, window: timedelta = timedelta(hours=24))`(`logging.Handler`): WARNING 이상을 `record.msg`(이벤트 이름)로만 센다. `.snapshot() -> dict`(`window_hours`, `since`, `total`, `by_event`).
- `health_view(conn: sqlite3.Connection, deps: ApiDeps) -> dict`: 6.3.1 필드 출처 표 그대로. `notify.effective`는 티켓 08 전까지 `telegram`(구독이 없으므로 D1a), 08이 `effective_channel()`로 바꾼다.

`api/server.py`
- `@dataclass ApiDeps(settings: Settings, clock: Clock, token: str, read_conn: Callable[[], sqlite3.Connection], dispatcher: Dispatcher | None, errors: ErrorCounter, polling_state: Callable[[], Literal["running", "down", "stopped"]], started_at: datetime, transcripts: TranscriptStore | None = None, safe_mode: bool = False)`. 뒤 티켓이 필드를 더한다(`delivery`, `push`).
- `build_app(deps: ApiDeps) -> web.Application`: 미들웨어 순서 `access_log` → `cors` → `body_limit(max_body_kb)` → `auth` → `safe_mode`(안전 모드면 `/health` 말고 `503 safe_mode`). 라우트는 `/api/v1` 아래, 모르는 경로는 `404 not_found` JSON.
- `async start_api(app: web.Application, host: str, port: int) -> web.AppRunner | None`: `AppRunner(app, access_log=None)`. 포트가 쓰이고 있으면(`OSError`) `api_bind_error` 경고를 남기고 None.
- `async stop_api(runner: web.AppRunner | None) -> None`
- 접근 로그 미들웨어: `log.info("api_request", extra={"method", "route", "status", "duration_ms"})`. `route`는 `request.match_info.route.resource.canonical`(없으면 `"-"`).

`app.py`
- `@dataclass BeParts(state, convs, runs, tasks, conditions, transcripts, tools, router, dispatcher, runner, sender)`와 `build_be(settings: Settings, conn: sqlite3.Connection, clock: Clock, *, brain: Brain, sender: Sender, sleep=asyncio.sleep, keep_awake=nullcontext) -> BeParts`: 지금 `_serve`의 조립을 그대로 옮긴 함수. `_serve`와 `BeEnv`가 같이 쓴다.
- 시작 순서(스펙 15장): 6단계에서 폴링을 시작한 뒤 `start_api`. `api.enabled = false`면 열지 않는다. `api_token`이 없거나 43자 미만이면 `api_token_missing` 경고를 남기고 열지 않는다(텔레그램과 루프는 계속). 안전 모드에서는 `ApiDeps(safe_mode=True, dispatcher=None)`로 `/health`만 답하는 API를 연다.
- 종료 순서: tick 멈춤 → `stop_api` → updater → app → dispatcher.
- `ErrorCounter`를 루트 로거에 붙인다(`setup_logging` 뒤).

`cli.py`
- `main(argv: list[str] | None = None) -> int`: 인자가 없으면 `app.main()`. `gen-token`은 `secrets.token_urlsafe(32)` 한 줄을 출력하고 0. 뒤 티켓이 `gen-vapid`(08), `schema`(02), `seed-life`(10)를 더한다.

`tests/be_env.py`
- `BeEnv.start(tmp_path, *, script: list[FakeTurn] = [], start: datetime, overrides: dict | None = None) -> BeEnv` (async 컨텍스트 관리자): 임시 루트에 마이그레이션한 DB, `build_be(... brain=FakeBrain(script, tools, clock=clock), sender=FakeSender(), sleep=fake_sleep(clock))`, `build_app(ApiDeps(token=TEST_TOKEN, read_conn=lambda: open_ro(db), ...))`, `aiohttp.test_utils.TestClient`, 디스패처 시작.
- 속성 `client`, `clock`, `brain`, `telegram`(FakeSender), `parts`. 메서드 `get(path, *, token=TEST_TOKEN, headers=None)`, `post(path, json, *, token=TEST_TOKEN)`, `put`, `delete`, `async tick()`(`runner.tick()` 뒤 디스패처 큐가 빌 때까지 기다림), `async drain()`.

**Slices**

마이그레이션
- [ ] `test_migrate_fresh_then_again`(SP1)이 그대로 통과하고 `user_version == 10`
- [ ] `test_migrate_5_to_10_keeps_sp1_rows`: 005 상태 DB에 대화·`inbound_pending` 행을 넣고 올리면 행이 남고 `channel == "telegram"`, `runs.answered_at IS NULL`
- [ ] `test_curve_and_status_checks`: 아래가 모두 `IntegrityError`
  - `curve_ladder_scores` `now=11`, `now`·`future` 둘 다 NULL, `period='2026-Q4'`
  - `curve_area_scores` `score=0`, `period='2026-Q5'`, `area='sports'`
  - `status_xp_ledger` `amount=0`, 같은 `(source_kind, source_ref)` 두 번
  - `curve_milestones` `status='confirmed'`인데 `confirmed_at` NULL

인증 (`tests/test_api_auth.py`, `BeEnv`)
- [ ] `test_no_token_401` / `test_wrong_token_401_body_has_no_reason`: 본문이 정확히 `{"error": {"code": "unauthorized", "message": …}}`이고 `message`에 "토큰"·"형식" 같은 이유가 없다
- [ ] `test_right_token_200`
- [ ] `test_token_in_query_or_cookie_not_accepted`: `?token=`·`Cookie: token=` → 401
- [ ] `test_ten_failures_then_429_for_a_minute`: 실패 10회 뒤 맞는 토큰도 `429 too_many_auth_failures`, `clock.advance(seconds=61)` 뒤 200
- [ ] `test_options_preflight_without_token`: 204

CORS (`tests/test_api_cors.py`, `cors_origins=["https://dash.example.vercel.app"]`, `cors_origin_regex="^https://dash-[a-z0-9-]+-team\\.vercel\\.app$"`)
- [ ] `test_allowed_origin_preflight_headers`: 위 헤더 값이 정확히 그 문자열
- [ ] `test_private_network_preflight`: 요청 헤더가 있을 때만 `Access-Control-Allow-Private-Network: true`
- [ ] `test_regex_origin_allowed`, `test_other_vercel_app_not_allowed`: `https://evil.vercel.app` → `Access-Control-Allow-Origin` 없음, 토큰이 맞으면 200 본문은 그대로
- [ ] `test_expose_header_on_get`

`/health` (`tests/test_api_health.py`)
- [ ] `test_health_fields_from_sources`: `version.schema == 10`, `version.api == "v1"`, `last_tick_at == app_state.last_seen_at`, `brain.calls_cap == 60`, `proactive.cap == 3`, 지난 `pause_until`은 `null`, 시각은 모두 `Z`로 끝난다
- [ ] `test_degraded_conditions` (매개변수 4개): 폴링 `down`, `brain_auth_state=login`, `billing`, `limited_until` 미래 → `status == "degraded"`
- [ ] `test_brain_auth_unknown_until_first_call_then_written_by_dispatcher`
- [ ] `test_error_counter_counts_event_names_in_24h_window`: `log.warning("send_error")` 2회, `log.info("x")` 1회 → `by_event == {"send_error": 2}`. `clock.advance(hours=25)` 뒤 `total == 0`
- [ ] `test_runs_today_delivered_via_and_checkin_state`: done(답장 창 안) → `pending`, 창 밖 → `missed`, `answered_at` 있음 → `answered`
- [ ] `test_safe_mode_health_only`: `/health` → `{"status": "safe_mode", "version", "now"}`만, `/today` → `503 safe_mode`

읽기 전용과 로그
- [ ] `test_get_handlers_receive_mode_ro_connection` (`tests/test_api_readonly.py`): `deps.read_conn()`으로 받은 연결에 `INSERT INTO app_state …` → `sqlite3.OperationalError`
- [ ] `test_access_log_route_template_only` (`tests/test_api_logging.py`): `GET /api/v1/health?q=SECRET-QUERY`를 `Authorization: Bearer TEST-TOKEN-…`로 부른 뒤 로그 파일에 `"route": "/api/v1/health"`, `"status": 200`이 있고 `SECRET-QUERY`, 토큰 문자열, `Authorization`이 없다
- [ ] `test_failed_auth_log_has_no_token`: 틀린 토큰 문자열이 로그에 없다
- [ ] `test_body_over_64kb_413`: `too_large`

앱 시작 (`tests/test_app_start.py`의 가짜 Updater·Application 이음매)
- [ ] `test_api_starts_after_polling_and_stops_before_updater`: 호출 순서 `start_polling` → `start_api` … `stop_api` → `updater.stop` → `app.stop` → `dispatcher.stop`
- [ ] `test_api_disabled_runs_like_sp1`, `test_missing_or_short_token_logs_and_skips_api`
- [ ] `test_port_in_use_logs_api_bind_error_and_keeps_polling`: 포트를 먼저 잡아 두고 시작 → 로그에 `api_bind_error`, 폴링은 시작됨
- [ ] `test_safe_mode_opens_health_only_api`
- [ ] `test_gen_token` (`tests/test_cli.py`): 출력 한 줄, 43자 이상, `[A-Za-z0-9_-]`만. `test_no_args_calls_app_main`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_health_after_morning_brief`: `BeEnv.start(start=kst(2026, 10, 24, 10, 0, 30), script=[FakeTurn([], "좋은 아침이에요")])` → `await env.tick()` → `GET /health`의 `runs_today[0]`이 `{"loop": "morning_brief", "status": "done", "delivered_via": ["telegram"], "checkin_state": "pending"}`, `proactive.sent_today == 1`, `brain.calls_today == 1`, `brain.auth == "ok"`, `notify == {"primary": "app", "effective": "telegram"}`. 실행: `python -m pytest tests/test_api_e2e.py -v` → `1 passed`.

**마무리**
- [ ] `.env.example`에 `API_TOKEN=`(자리 표시), `config.toml`에 스펙 15장의 `[api]`, `[notify]` 블록 그대로.
- [ ] **Review + Commit** `feat(api): API skeleton with auth, CORS, health and SP3-4 migrations`

---

### 티켓 02: 읽기 API — 할 일·컨디션·답할 회차·대화·카탈로그·스키마

**목표:** `GET /today`, `/week`, `/conditions`, `/checkins`, `/checkins/{id}`, `/conversations`, `/conversations/{id}/messages`, `/ui/catalog`, `/schema`가 스펙 6.3.2~6.3.4, 6.4.5~6.4.7 그대로 답한다. `/today`·`/week`와 텔레그램 `/today`·`/week`가 같은 함수에서 나온다(16장 계약 테스트). 운영 앱 스레드는 이 티켓 뒤 `GET /schema`로 타입을 만든다.
**막는 티켓:** 01
**라벨:** `ready-for-agent`

**Files:**
- Create: `store/views.py`, `api/read.py`, `tools/ui.py`(카탈로그만)
- Modify: `bot/commands.py`(`today_text`, `week_text`가 뷰를 글로만 바꾼다), `store/transcripts.py`, `store/repos/conditions.py`, `store/repos/conversations.py`, `harness/checkins.py`, `harness/context.py`, `harness/dispatcher.py`(`_ask_condition_for` 위임), `api/models.py`, `api/server.py`, `cli.py`
- Test: `tests/test_api_read.py`, `tests/test_api_schema.py`, `tests/test_transcript_channels.py`

**Interfaces**
- Consumes: `TasksRepo.list/priorities`, `ConditionsRepo`, `RunsRepo`, `TranscriptStore`, `ApiDeps`, `checkin_state` (01)
- Produces:

`store/views.py`
- `TodoGroup = Literal["priority", "scheduled", "open"]`
- `@dataclass TodayView(date: date, weekday: str, groups: list[tuple[TodoGroup, Task]], condition: Condition | None)`
- `today_view(tasks: TasksRepo, conditions: ConditionsRepo | None, now: datetime, tz, boundary) -> TodayView`: 지금 `today_text`의 묶음 규칙 그대로(우선순위 → 일정 → 열린 할 일, 이미 나온 것 빼기, 전에 잡은 일 포함).
- `@dataclass DayView(date, weekday, is_today: bool, todos: list[Task])`, `@dataclass WeekView(week: str, start: date, end: date, priorities: list[Task], days: list[DayView])`
- `week_view(tasks, now, tz, boundary) -> WeekView`: 7일 모두(빈 날 포함).
- `todo_dict(t: Task, tasks: TasksRepo, today: date) -> dict`: 6.3 `Todo` 모양. `priority`는 지금 기간(일·주·월·분기·년) 우선순위 가운데 가장 큰 주기 하나, 아니면 None. 시각은 UTC `Z`.
- `conditions_view(conditions: ConditionsRepo, from_: date, to: date) -> dict`: 기록 있는 날만, `average`는 소수 한 자리, 기록이 없으면 `average: null`.
- `today_text`는 `today_view`를, `week_text`는 `week_view`를 글로 바꾸기만 한다(글에서 빈 날은 지금처럼 뺀다). SP1 시험이 그대로 통과한다.

`harness/context.py`
- `ask_condition_for(run: Run, merged: list[Run], *, conditions: ConditionsRepo | None, runs: RunsRepo, settings: Settings) -> date | None`: `Dispatcher._ask_condition_for`의 규칙을 옮긴 순수 함수. 디스패처는 이것을 부른다.

`harness/checkins.py` (추가)
- `checkin_summaries(*, runs, convs, deliveries, d: date, now, settings) -> list[dict]`: 6.4.5 요약 목록(`text`, `cards` 없음). 보낸 회차만, 다른 회차에 합쳐진 회차는 빼고 primary 하나로.
- `checkin_detail(run_id: int, *, runs, convs, deliveries, tasks, conditions, now, settings) -> dict | None`
- `checkin_cards(run: Run, merged: list[Run], *, tasks: TasksRepo, conditions: ConditionsRepo, runs: RunsRepo, settings) -> list[dict]`: 그 회차의 `tool_events_log`(`run_id`)에서 `tasks_proposed`로 낸 할 일 가운데 아직 `draft`인 것 → `{"toolCallId": "h_draft_<run_id>", "component": "ui_todo_draft", "props": {"task_ids": […]}}`, `ask_condition_for(...)`의 날짜에 컨디션 기록이 없으면 → `{"toolCallId": "h_cond_<run_id>", "component": "ui_condition_picker", "props": {"date": …}}`. 티켓 13·14가 확인 카드와 사다리·영역 카드를 더한다.

`store/transcripts.py`
- `TranscriptStore.append(at, speaker, conversation_id, run_key, text, tools=None, *, channel: Channel = "telegram")`: `channel == "app"`일 때만 머리글 끝에 ` @app`을 붙인다(텔레그램 머리글은 SP1 그대로. 아래 "스펙 빈 곳" 1).
- `_HEADER`가 끝의 ` @(telegram|app)`을 선택으로 받는다. 표시가 없으면 `telegram`.
- `@dataclass TranscriptMessage(at: datetime, speaker: Literal["user", "secretary"], text: str, tools: list[str], channel: Channel)`, `messages(conversation_id: int) -> list[TranscriptMessage]`: 날짜 파일과 `HH:MM`에서 시각을 만든다(경계 04:00 전이면 파일 날짜 다음 날).

저장소
- `ConditionsRepo.between(from_: date, to: date) -> list[Condition]`
- `ConversationsRepo.recent(*, channel: str | None, limit: int) -> list[Conversation]`, `.for_run(run_id: int) -> list[Conversation]`

`tools/ui.py`
- `UI_CATALOG_VERSION = "2026-10-24.1"`, `UI_COMPONENTS: dict[str, dict]`(6.4.7 표의 8개, 각 `{"origin": "brain" | "harness", "schema": JSON Schema}`. 제한: `ui_todo_list.task_ids` ≤30, `ui_choice.options` 2~4, `ui_summary_card.lines` ≤8·줄마다 120자)
- `validate_props(component: str, props: dict) -> str | None`(오류 문구 또는 None, `jsonschema` 사용)

`api/read.py`: `get_today`, `get_week`, `get_conditions`, `get_checkins`, `get_checkin`, `get_conversations`, `get_conversation_messages`, `get_ui_catalog`, `get_schema`. 모두 `deps.read_conn()`만 쓰고, 응답 dict를 `to_api_times` 뒤 해당 pydantic 모델로 검증해 낸다.
- `/today`: `brief`는 오늘 논리적 날짜의 `done` `morning_brief` 또는 `return` 회차의 `outbound_text`, `cards`는 티켓 12 전까지 `[]`.
- 쿼리 검증: `from`·`to`는 `YYYY-MM-DD`, `from <= to`, 366일 이하. `limit`은 1~200. 경로 id는 정수. 어기면 `400 invalid_request`, 없는 id는 `404 not_found`.

`api/models.py`: `Todo`, `TodayResponse`, `WeekResponse`, `ConditionsResponse`, `CheckinSummary`, `CheckinDetail`, `ConversationsResponse`, `MessagesResponse`, `UiCatalogResponse`, `SchemaResponse`를 `MODELS`에 더한다.

`cli.py schema`: `schema_bundle()`을 JSON으로 출력(대시보드 타입 생성용, 티켓 16).

**Slices**

계약 (`tests/test_api_read.py`, `BeEnv`, 같은 고정 자료: 우선순위 2·일정 1·전에 잡은 할 일 1·초안 1·소프트 삭제 1)
- [ ] `test_today_matches_today_text_same_order`: `/today`의 `todos[].todo.title` 순서 == `today_text` 글에서 읽은 제목 순서, 묶음 이름은 `priority`, `priority`, `scheduled`, `open`
- [ ] `test_week_has_all_7_days_and_matches_week_text`: `days` 7개, 빈 날 `todos: []`, 할 일 있는 날의 제목 순서 == `week_text`
- [ ] `test_drafts_and_soft_deleted_never_in_get`: 초안·삭제 제목이 어떤 응답 본문에도 없다
- [ ] `test_todo_priority_is_biggest_current_period`: 같은 할 일이 이번 주·이번 분기 우선순위 → `{"cadence": "quarter", …}`
- [ ] `test_brief_from_done_morning_or_return`
- [ ] `test_times_are_utc_z`: `scheduled_at`이 `"2026-10-25T05:00:00Z"`(KST 14:00)
- [ ] `test_conditions_default_30_days_skips_empty`: 기록 21일 → `days_logged == 21`, `items` 21개, 빈 날 없음
- [ ] `test_bad_query_values_400` (Review Focus 2): `from=2026-10-24&to=2026-10-01`, `from=2026-13-01`, 367일, `limit=0`, `limit=1000`, `/checkins/abc` → 400 / 404, 로그의 `route`는 틀
- [ ] `test_checkin_states_and_detail_cards`: 보낸 저녁 체크인(초안 2개 제안, 컨디션 없음) → 상세 `cards`가 `h_draft_<id>`(`task_ids` 2개)와 `h_cond_<id>`
- [ ] `test_merged_run_listed_once_with_latest_window`: 일요일 저녁 + 회고 → 목록 1개, `reply_until`은 회고의 24시간 끝
- [ ] `test_skipped_runs_are_not_checkins`
- [ ] `test_conversations_list_and_messages`: `channel=app` 거르기, 최근 것부터, `messages`의 `speaker`·`tools == ["add_task"]`, 가린 글(`[가림]`)

원문 기록 (`tests/test_transcript_channels.py`)
- [ ] `test_app_header_has_marker`: `### 21:05 사용자 [44] (evening_checkin) @app`
- [ ] `test_telegram_header_unchanged_and_legacy_reads_as_telegram`
- [ ] `test_messages_time_after_midnight_belongs_to_next_calendar_day`: 10/24 파일의 `01:30` → `2026-10-24T16:30:00Z`

스키마 (`tests/test_api_schema.py`)
- [ ] `test_schema_lists_all_models`: `/schema`의 `models` 키가 `MODELS`와 같고 `api == "v1"`
- [ ] `test_every_read_response_validates_against_schema`: 위 응답 본문 각각을 `jsonschema.validate`
- [ ] `test_ui_catalog_version_and_components`: `version == "2026-10-24.1"`, 8개, `origin` 값이 표대로
- [ ] `test_cli_schema_prints_bundle`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_today_after_chat_and_checkin`: 텔레그램 메시지 → FakeBrain이 `add_task`(내일 14:00 치과)·`propose_tasks` 2개 → 17:30 tick의 저녁 체크인(FakeBrain) → `GET /today`(다음 날)에 치과가 `scheduled`, `GET /checkins?date=…`에 그 체크인 `pending`, 상세 `cards` 2개. `python -m pytest tests/test_api_e2e.py -v` → `2 passed`.

**마무리**
- [ ] **Review + Commit** `feat(api): read endpoints for today, week, conditions, check-ins and conversations`

---

### 티켓 03: 읽기 API — `/curve`, `/status` 읽기 모델

**목표:** `GET /curve`와 `GET /status`가 스펙 6.3.5, 6.3.6, 8장, 9.2~9.4의 계산대로 답한다. 표는 01이 만들었고 이 티켓은 읽기와 계산만 한다(쓰기는 09 이후). 시험은 고정 자료를 저장소 밖 SQL로 넣는다.
**막는 티켓:** 02
**라벨:** `ready-for-agent`

**Files:**
- Create: `curve/__init__.py`, `curve/model.py`, `status/__init__.py`, `status/xp.py`, `status/snapshot.py`, `store/repos/curve.py`(읽기), `store/repos/status.py`(읽기)
- Modify: `api/read.py`, `api/models.py`, `api/server.py`
- Test: `tests/test_curve_model.py`, `tests/test_status_snapshot.py`, `tests/test_api_curve_status.py`

**Interfaces**
- Consumes: `ConditionsRepo.between`, `TasksRepo.priorities/list`, `period_of`, `ApiDeps` (01, 02)
- Produces:

`store/repos/curve.py` `CurveRepo(conn, clock)` 읽기
- `@dataclass Chapter(id, seed_key, title, theme, start_month, end_month, sketch, certainty, status, origin, draft_since)`, `@dataclass Milestone(id, chapter_id, date_text, precision, sort_date: date, kind, kind_certainty, title, note, sensitive: bool, certainty, status, origin, title_label, conversation_id, draft_since, confirmed_at)`, `@dataclass Ladder(period, now, future, note)`, `@dataclass AreaScore(period, area: Area, score: int, note, recovery_quest)`
- `chapters_overlapping(from_month: str, to_month: str) -> list[Chapter]`(확정만), `milestones_between(from_: date, to: date, *, include_sensitive: bool) -> list[Milestone]`(확정만), `ladder_between(from_month, to_month) -> list[Ladder]`, `area_scores_between(from_q, to_q) -> list[AreaScore]`, `latest_area_periods(n: int = 2) -> list[str]`, `area_scores(period) -> dict[Area, AreaScore]`, `area_default(area: Area) -> str | None`, `earliest_chapter_start() -> str | None`, `get_milestone(id)`, `get_chapter(id)`

`store/repos/status.py` `StatusRepo(conn, clock)` 읽기
- `total() -> int`, `recent(n: int = 5) -> list[XpEntry(at, label, amount)]`, `titles(*, include_sensitive: bool) -> list[TitleRow(milestone_id, title, title_label, kind, date_text, granted_at, sensitive)]`

`curve/model.py` (순수 함수)
- `Zoom = Literal["day", "week", "month", "quarter", "year"]`, `MAX_BUCKETS = 400`
- `@dataclass(frozen=True) Bucket(name: str, start: date, end: date)`; `class TooManyBuckets(ValueError)`
- `default_range(zoom: Zoom, today: date, earliest_chapter: str | None) -> tuple[date, date]`: day 지난 30일, week 26주, month 24개월, quarter 20분기, year 가장 이른 챕터(없으면 올해)~올해. 기간 끝은 그 묶음의 끝 날짜.
- `buckets(zoom: Zoom, from_: date, to: date) -> list[Bucket]`: 이름은 `period_of(cadence, d)`, `day`는 날짜. 400 초과면 `TooManyBuckets`.
- `bucket_conditions(conditions: list[Condition], bs: list[Bucket]) -> list[dict]`: 기록 있는 묶음만, 평균 소수 한 자리.
- `reassurance(ladder: list[Ladder], conditions: list[Condition]) -> list[dict]`: `now`가 있는 달마다. `condition_scaled = (average − 1) × 2.5`, `gap = round(condition_scaled − now, 1)`, 그 달 기록 7일 미만이면 `condition_average`·`condition_scaled`·`gap`이 None.
- `curve_view(curve: CurveRepo, conditions: ConditionsRepo, *, zoom: Zoom, from_: date | None, to: date | None, include_sensitive: bool, today: date) -> dict`: 6.3.5 모양.

`status/xp.py` (순수 함수, 상수. 숫자는 스펙 9장 그대로)
- `XP_TASK = 10`, `XP_PRIORITY = {day: 15, week: 25, month: 50, quarter: 100, year: 200}`, `XP_CHECKIN_REPLY = 5`, `XP_CONDITION = 5`, `XP_REVIEW_WEEK = 30`, `XP_LADDER = 10`, `XP_WHEEL = 20`, `XP_YEAR_REVIEW = 50`, `XP_REST_DAY = 5`, `XP_SECRETARY_AMOUNTS = (5, 10)`, `SECRETARY_DAILY_MAX = 3`
- `xp_threshold(level: int) -> int`(`T(L) = 25 × (L − 1) × (L + 4)`), `level_for(xp_total: int) -> int`, `progress(xp_total: int) -> tuple[int, int, int]`(level, into, for_next)
- `AREA_LABELS: dict[Area, str]`(커리어, 경제, 건강, 관계, 배움, 삶의 질), `DEFAULT_RECOVERY_QUESTS: dict[Area, str]`(부록 A 그대로)
- `title_name(kind: str, title: str, title_label: str | None) -> str`: 고점 `「{제목}」의 순간`, 전환점 `「{제목}」을 지나온 사람`, `title_label`이 있으면 그것.

`status/snapshot.py`
- `status_snapshot(*, now: datetime, tz, boundary, status: StatusRepo, curve: CurveRepo, tasks: TasksRepo, conditions: ConditionsRepo, include_sensitive: bool = False) -> dict`: 6.3.6 모양. 스탯·디버프·회복 퀘스트 순서(`recovery_quest` → `curve_area_defaults` → `DEFAULT_RECOVERY_QUESTS`)·HP·메인 퀘스트(이번 분기 `quarter` 우선순위와 첫 걸음 열림/완료 수)·일일 퀘스트(오늘 `planned_for`인 열린 첫 걸음, 없으면 메인 퀘스트마다 날짜 없는 다음 첫 걸음 하나)는 9.3 그대로.

API: `get_curve`(쿼리 `zoom` 기본 `month`, `from`·`to` `YYYY-MM-DD`, `include_sensitive` `true`|`false`만), `get_status`(`include_sensitive`). `TooManyBuckets` → `400 invalid_request` "범위를 줄이거나 확대 단위를 키워 주세요". 모델 `CurveResponse`, `StatusResponse`.

**Slices**

곡선 계산 (`tests/test_curve_model.py`)
- [ ] `test_buckets_iso_week_and_quarter_boundaries`: 2026-12-28(월)~2027-01-03은 `2026-W53`, 2026-03-31/04-01은 `2026-Q1`/`2026-Q2`
- [ ] `test_default_ranges_per_zoom`: today 2026-10-24 → day 2026-09-25~10-24, month 2024-11-01~2026-10-31(6.3.5 예시), quarter 20개, week 26개
- [ ] `test_year_zoom_from_earliest_chapter`
- [ ] `test_over_400_buckets_raises`: day 401일
- [ ] `test_bucket_conditions_average_logged_days_only`
- [ ] `test_reassurance_scaling_and_7_day_threshold`: 21일 평균 3.4·사다리 6 → `condition_scaled == 6.0`, `gap == 0.0`. 6일 기록 → `gap is None`. `future`만 있는 달 → 항목 없음

상태창 (`tests/test_status_snapshot.py`)
- [ ] `test_level_table`: `xp_threshold` 2→150, 5→900, 10→3150, 20→11400, 30→24650. `progress(1380) == (6, 130, 400)`
- [ ] `test_stats_latest_quarter_falls_back_to_previous_with_period`
- [ ] `test_debuff_only_when_both_quarters_and_lower`: 같으면 False
- [ ] `test_recovery_quest_priority`: 점수 행의 퀘스트 → 기본값 표 → 부록 A 문구
- [ ] `test_no_area_scores_stats_null_no_debuff`
- [ ] `test_hp_today_condition_or_null`
- [ ] `test_main_and_daily_quests`: 첫 걸음 열림 2·완료 3 → `{"open": 2, "done": 3}`, 오늘 것 없으면 메인 퀘스트마다 다음 첫 걸음 하나
- [ ] `test_titles_template_label_override_and_sensitive_excluded`: 저점은 칭호 행이 있어도 나오지 않는다

API (`tests/test_api_curve_status.py`)
- [ ] `test_curve_excludes_drafts_and_sensitive_by_default`, `test_include_sensitive_true_marks_flag`
- [ ] `test_curve_bad_query_400` (Review Focus 2): `zoom=hour`, `include_sensitive=yes`, `from > to`, 401개 묶음
- [ ] `test_curve_and_status_validate_against_schema`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_curve_and_status_read_model`: `BeEnv`에서 텔레그램으로 할 일을 만들고 우선순위(분기)로 올린 뒤(FakeBrain), 곡선 고정 자료는 SQL로 넣고 → `GET /curve?zoom=quarter`의 `areas`·`reassurance`, `GET /status`의 `main_quests[0].title`이 그 할 일, `level == 1`, `xp_total == 0`(원장 쓰기는 15). → `passed`

**마무리**
- [ ] **Review + Commit** `feat(api): curve and status read model`

---

### 티켓 04: 즉시 갈래와 활동 기록, `POST /actions`

**목표:** `POST /actions`가 두뇌 없이 도구 함수 하나를 부르고 스펙 6.4.2대로 답한다(적용·확인 필요·거절, 같은 `client_msg_id`는 처음 응답 그대로). 모든 변경 도구는 데이터, `tool_events_log`, `activity`를 한 트랜잭션에 쓴다. 텔레그램 버튼(`bot/callbacks.py handle_callback`)과 하루 한 번 작업의 초안 만료가 `apply_action`을 거친다.
**막는 티켓:** 02
**라벨:** `ready-for-agent`

**Files:**
- Create: `tools/actions.py`, `tools/activity.py`, `store/repos/activity.py`, `api/actions.py`
- Modify: `domain.py`, `tools/core.py`, `tools/confirmations.py`, `harness/dispatcher.py`, `bot/callbacks.py`, `loop/runner.py`(`expire_drafts` 작업), `app.py`, `api/models.py`, `api/server.py`
- Test: `tests/test_api_actions.py`, `tests/test_activity.py`, `tests/test_telegram_drafts.py`·`test_telegram_conditions.py`(SP1, 그대로 통과)

**Interfaces**
- Consumes: `Tools` 변경 메서드, `TasksRepo.transaction`, `render_confirmations`, `ApiDeps.dispatcher` (SP1, 01)
- Produces:

`domain.py`
- `Channel = Literal["telegram", "app"]`, `ActivityChannel = Literal["telegram", "app", "scheduler"]`, `Actor = Literal["secretary", "user"]`
- `RunContext`에 `actor: Actor = "secretary"`, `activity_channel: ActivityChannel | None = None`, `channel: Channel = "telegram"`, `activity_ids: list[int] = field(default_factory=list)`, `undo_ids: list[int] = field(default_factory=list)`

`store/repos/activity.py`
- `@dataclass Activity(id, at, actor, channel, kind, target, summary, risk, undo_json: dict | None, undone_at, undone_by, conversation_id, run_id, inbound_id)`
- `ActivityRepo(conn, clock)`: `add(*, actor, channel, kind, target, summary, risk, undo: dict | None, conversation_id, run_id, inbound_id) -> int`, `get(id) -> Activity | None`, `changed_after(target: str, after: datetime) -> bool`
- `IdempotencyRepo(conn, clock)`: `get(client_msg_id) -> IdemRecord(endpoint, status_code, response: dict | None, conversation_id) | None`, `put(client_msg_id, endpoint, status_code, response, conversation_id=None) -> None`, `prune(older_than: datetime) -> int`
- `ConfirmsRepo(conn, clock)`: `create(*, action, args, summary, origin: Literal["actions", "run_turn"], expires_at, run_id=None, conversation_id=None) -> PendingConfirm`(토큰 `"ct_" + secrets.token_urlsafe(16)`), `get(token)`, `resolve(token, resolution: Literal["applied", "declined", "expired", "stale"]) -> None`, `expire(now) -> int`, `prune(older_than) -> int`

`tools/activity.py`
- `activity_origin(ctx: RunContext) -> tuple[Actor, ActivityChannel]`: `ctx.activity_channel`이 있으면 그것. 없으면 `run_id`가 있고 `inbound_id`가 없으면 `scheduler`, 아니면 `ctx.channel`.
- `record_activity(repo: ActivityRepo, ctx: RunContext, *, kind: str, target: str | None, summary: str, risk: Literal["low", "confirm"], undo: dict | None) -> int`: 행을 쓰고 `ctx.activity_ids`에 더한다(`undo`가 있고 `risk == "low"`면 `ctx.undo_ids`에도).
- 대상 문자열은 5.2 주석 그대로: `task:<id>`, `condition:<날짜>`, `priorities:<cadence>:<period>`.

`tools/core.py`
- `Tools(..., activity: ActivityRepo | None = None)`. 변경 메서드(`add_task`, `propose_tasks`, `confirm_tasks`, `update_task`, `move_task`, `complete_task`, `reopen_task`, `drop_task`, `set_priorities`, `record_condition`)가 `_finish` 안(같은 트랜잭션)에서 `record_activity`를 부른다. `summary`는 그 이벤트의 확인 문구 한 줄, `undo`는 바꾸기 전 값(티켓 05가 쓴다). `activity`가 None이면 SP1과 같다.
- `Tools.expire_drafts(ctx, older_than: datetime) -> dict`: `TasksRepo.expire_drafts`를 부르고 활동 `drafts_expired`.

`tools/confirmations.py`
- `confirmation_line(e: ToolEvent, today: date) -> str | None`(지금 `_line`의 공개 이름)

`tools/actions.py`
- `@dataclass ActionRequest(action: str, args: dict, *, actor: Actor, channel: ActivityChannel, client_msg_id: str | None = None, confirm_token: str | None = None, endpoint: Literal["actions", "undo", "chat"] = "actions")`
- `@dataclass ActionResult(status: Literal["applied", "needs_confirm", "rejected", "conflict", "undone", "already_undone"], http_status: int, body: dict)`: `body`는 6.4.2 응답 본문 그대로(`activity_id`, `undo_id`, `result`, `confirmation`, `xp`, 또는 `confirm_token`, `summary`, `expires_at`, 또는 `error`).
- `@dataclass(frozen=True) ActionSpec(tool: str, needs_confirm: Callable[[Tools, dict], str | None] | None = None, public: bool = True)`
- `ACTIONS: dict[str, ActionSpec]`: 이 티켓은 `add_task`, `update_task`, `move_task`, `complete_task`, `reopen_task`, `drop_task`, `confirm_tasks`, `set_priorities`, `record_condition`, `decline_confirm`과 내부용(`public=False`) `expire_drafts`, `prune_api_state`. 뒤 티켓이 같은 표에 더한다.
- `needs_confirm`: `drop_task`는 그 할 일이 지금 기간 우선순위이거나 열린 첫 걸음이 있으면 문구, `set_priorities`는 `quarter`·`year`이면서 지금 목록이 비어 있지 않고 다른 목록으로 바꿀 때 문구(예: "이번 분기 우선순위 3개를 바꿔요").
- `xp`는 티켓 15 전까지 `{"gained": 0, "level_up": null}`.

`harness/dispatcher.py`
- `Dispatcher(..., activity: ActivityRepo | None = None, idempotency: IdempotencyRepo | None = None, confirms: ConfirmsRepo | None = None)`
- `Dispatcher.apply_action(req: ActionRequest) -> ActionResult`: 동기, `await` 없음. 순서: (1) `client_msg_id`가 `api_idempotency`에 있으면 저장한 응답 그대로 (2) 모르는 `action`, HTTP 요청인데 `public=False` → `400 invalid_request` (3) `confirm_token`이 있으면 `ConfirmsRepo`에서 확인: 없음·쓰임·만료 → `409 conflict`, 그 대상의 활동이 토큰 생성 뒤에 있으면 `stale`로 닫고 `409 conflict`, 맞으면 `risk="confirm"`으로 적용(`undo_id` 없음) (4) `needs_confirm` 문구가 있으면 토큰 만들고(`origin="actions"`, +10분) `needs_confirm` (5) `RunContext(conversation_id=None, run_id=None, actor=req.actor, activity_channel=req.channel)`로 도구 호출, `{"error"}`면 `422 rejected` (6) 응답과 `api_idempotency`를 같은 트랜잭션에 쓴다.

`bot/callbacks.py`: `handle_callback(query, owner_id, tools, *, transcripts, clock, router=None, apply: Callable[[ActionRequest], ActionResult] | None = None)`. `apply`가 있으면 `d:c`→`confirm_tasks`, `d:x`→`drop_task`, `d:all`→`confirm_tasks`, `c:`→`record_condition`을 `ActionRequest(actor="user", channel="telegram")`로 부른다. 답 문구와 원문 기록은 SP1 그대로. `app.py`는 `apply=dispatcher.apply_action`을 넘긴다.

`loop/runner.py`: 하루 한 번 `expire_drafts`, `ConfirmsRepo.expire`(만료된 토큰 `expired`) + 7일 지난 토큰 삭제, `api_idempotency` 2일 지난 행 삭제를 `apply_action(ActionRequest(actor="secretary", channel="scheduler", …))`로 한다.

`api/actions.py`: `post_actions(request)`: `ActionRequestBody(action, args, client_msg_id: str, confirm_token: str | None)` 검증(`client_msg_id` 필수) → `apply_action(ActionRequest(actor="user", channel="app", …))` → `to_api_times(result.body)`를 `result.http_status`로. 모델 `ActionRequestBody`, `ActionApplied`, `ActionNeedsConfirm`, `ActionRejected`.

**Slices**

`/actions` (`tests/test_api_actions.py`, `BeEnv`)
- [ ] `test_complete_task_applied_shape`: `{"status": "applied", "activity_id": n, "undo_id": n, "result": {…"completed_at": "…Z"}, "confirmation": "✓ 완료: 운동", "xp": {"gained": 0, "level_up": null}}`
- [ ] `test_every_public_action_applies` (매개변수: 표의 할 일·컨디션 동작)
- [ ] `test_rejected_422_uses_tool_message`: 우선순위 4개 → `{"status": "rejected", "activity_id": null, "error": {"code": "rejected", "message": "<도구 문구>"}}`
- [ ] `test_needs_confirm_drop_priority_task_then_apply_with_token`: 첫 요청은 데이터 그대로·`pending_confirms` 행, 같은 요청 + `confirm_token` → 적용, `undo_id` 없음
- [ ] `test_set_priorities_quarter_replacing_nonempty_needs_confirm`, `test_set_priorities_quarter_first_time_applies`
- [ ] `test_confirm_token_used_or_expired_409`: 두 번째 사용 → 409, `clock.advance(minutes=11)` → 409
- [ ] `test_confirm_token_stale_409`: 토큰 뒤 같은 할 일을 `move_task` → 409, `resolution == "stale"`
- [ ] `test_duplicate_client_msg_id_returns_first_response`: 두 번째 요청에 도구가 다시 불리지 않는다(활동 1행)
- [ ] `test_missing_client_msg_id_400`, `test_unknown_or_internal_action_400`(`expire_drafts`)
- [ ] `test_decline_confirm_closes_token_changes_nothing`

활동 (`tests/test_activity.py`)
- [ ] `test_activity_same_transaction_as_change`: 도구가 `log_tool_event` 뒤 예외를 내도록 이음매를 걸면 할 일·`tool_events_log`·`activity` 모두 없다
- [ ] `test_actor_channel_mapping`: 사용자 메시지에 답한 두뇌 → `secretary`/`telegram`, 회차 첫 호출 → `secretary`/`scheduler`, 버튼 → `user`/`telegram`, `/actions` → `user`/`app`, 초안 만료 → `secretary`/`scheduler`
- [ ] `test_activity_summary_has_no_message_body`: 사용자 메시지 본문 문자열이 `activity` 어느 열에도 없다
- [ ] `test_buttons_go_through_apply_action`: `d:c` 누름 → 활동 `tasks_confirmed`(`user`/`telegram`), SP1 답 문구 그대로
- [ ] `test_daily_jobs_expire_tokens_and_prune_idempotency`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_actions_end_to_end`: 텔레그램 메시지로 FakeBrain이 `add_task` → `POST /actions complete_task` → 텔레그램 `/today`(가짜 업데이트)에서 그 할 일이 빠지고, `GET /today`에도 없다. 같은 `client_msg_id`로 다시 보내면 같은 본문. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(api): immediate lane apply_action, activity log and POST /actions`

---

### 티켓 05: 되돌리기와 `GET /activity`

**목표:** `POST /activity/{id}/undo`가 U1~U6과 종류별 되돌리기 표(6.4.3)대로 정확히 한 번 되돌린다. `GET /activity`가 6.4.4 모양으로, 지금 되돌릴 수 있는 것에만 `undo_id`를 준다.
**막는 티켓:** 04
**라벨:** `ready-for-agent`

**Files:**
- Modify: `tools/activity.py`, `tools/actions.py`, `tools/core.py`, `store/repos/activity.py`, `store/repos/tasks.py`(`expire_drafts` 기준 시각), `api/actions.py`, `api/models.py`, `api/server.py`
- Test: `tests/test_api_undo.py`, `tests/test_tools_drafts.py`(SP1, 그대로)

**Interfaces**
- Consumes: `ActivityRepo`, `IdempotencyRepo`, `apply_action`, `undo_json` (04)
- Produces:
- `UndoHandler = Callable[[Tools, dict, RunContext], str | None]`(되돌리기 전 확인. 칸이 차 있으면 `"superseded"` 반환), `UNDO_HANDLERS: dict[str, UndoHandler]`, `register_undo(kind: str, handler: UndoHandler) -> None`. 이 티켓의 종류: `task_added`, `task_updated`, `task_moved`, `task_completed`, `task_reopened`, `task_dropped`, `tasks_confirmed`, `priorities_set`, `condition_recorded`. 09·12가 등록을 더한다.
- `undoable_now(a: Activity, repo: ActivityRepo, now: datetime) -> bool`: U1(`risk == "low"`, `undo_json` 있음, 종류가 등록됨), U2(`now − at ≤ 24시간`), U3(같은 `target`에 되돌리지 않은 더 나중 활동 없음, 되돌리기 활동 포함).
- `ACTIONS["undo"] = ActionSpec(tool="undo", public=False)`, `apply_action(ActionRequest(action="undo", args={"activity_id": id}, endpoint="undo", …))`: 이미 되돌렸으면 `200 {"status": "already_undone", "activity_id": <되돌리기 활동 id>}`, U1 → `422 not_undoable`, U2 → `409 undo_expired`, U3 → `409 superseded`. 되돌리면 새 활동(`kind="undo"`, `undo_json=None`, `target`은 원래 대상)과 원래 행의 `undone_at`·`undone_by`를 한 트랜잭션에, 응답 `{"status": "undone", "activity_id", "undone", "confirmation": "↩ 되돌림: {요지}"}`. 경험치 원장은 건드리지 않는다(U6).
- `TasksRepo.expire_drafts(older_than)`: 초안의 기준 시각은 가장 최근 `task_events.kind='proposed'` 시각(없으면 `created_at`). `tasks_confirmed` 되돌리기가 `proposed` 이벤트를 새로 쓴다.
- `ActivityRepo.since(after: datetime | None, limit: int) -> list[Activity]`(오래된 것부터)
- `api/actions.py`: `post_undo(request)`(본문 `{"client_msg_id"}` 필수), `get_activity(request)`(`since` ISO, `limit` 1~200 기본 50, 응답 `{"items": [...], "next_since": <마지막 at 또는 since>}`, 항목에 `undo_id`는 `undoable_now`일 때만). 모델 `UndoRequestBody`, `UndoResponse`, `ActivityResponse`.

**Slices** (`tests/test_api_undo.py`, `BeEnv`, `/actions`로 변경을 만든다)
- [ ] `test_undo_each_kind` (매개변수 9종): 되돌린 뒤 대상이 이전 값과 같다. `task_added` → `deleted_at` 있음, `task_reopened` → 이전 `done`과 `completed_at`, `condition_recorded` → 없던 날은 행 삭제
- [ ] `test_undo_task_dropped_restores_priority_only_if_slot_empty`: 칸이 차 있으면 `409 superseded`
- [ ] `test_undo_tasks_confirmed_restarts_draft_clock`: 확정 2일 뒤 되돌림 → 그날로부터 2일 23시간 뒤에도 `draft`, 3일 뒤 `dropped`
- [ ] `test_u1_not_undoable`: `risk=confirm` 활동, `decline_confirm` → `422 not_undoable`
- [ ] `test_u2_24h_boundary`: 정확히 24시간 → 되돌림, 24시간 1초 → `409 undo_expired`
- [ ] `test_u3_superseded_chain`: 완료 → 날짜 이동 → 완료 되돌리기 = 409. 되돌린 뒤 대상을 다시 바꾸면 그 되돌리기 이전 활동도 막힌다
- [ ] `test_u4_double_undo_already_undone_same_with_same_client_msg_id`
- [ ] `test_u5_undo_of_undo_not_undoable`
- [ ] `test_activity_list_shape_order_and_undo_id_now` (6.4.4): `since` 뒤만, 오래된 것부터, 24시간 지나면 같은 행의 `undo_id`가 사라진다
- [ ] `test_activity_bad_query_400_and_bad_path_404` (Review Focus 2): `since=어제`, `limit=0`, `/activity/abc/undo`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_undo_end_to_end`: 텔레그램 대화에서 FakeBrain이 `complete_task` → `GET /activity`의 그 행에 `undo_id`(행위자 `secretary`/`telegram`) → `POST /activity/{id}/undo` → `GET /today`에 다시 나오고, 텔레그램 `/today` 글에도 나온다. 같은 요청을 다시 보내면 `already_undone`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(api): undo rules U1-U6 and GET /activity`

---

### 티켓 06: 앱 채팅 `POST /chat` (UI message stream)

**목표:** 운영 앱이 `POST /api/v1/chat`으로 보낸 메시지가 두뇌 갈래를 지나 AI SDK UI message stream(SSE)으로 답한다. 스펙 6.4.1의 조각 순서, 7.5의 M1~M8(통로별 묶음, 통로별 보낼 곳, 처리 완료 기록, 다시 넣기, 끊김, 중복)을 지킨다. 명령은 같은 함수로 처리한다. 대화 이어가기는 이 티켓에서 앱 통로 안의 `chat`·`plan` 규칙만이고, 회차 대화와 가르기는 07이다.
**막는 티켓:** 05, 00(S11 결과: 글 조각과 대체 경로)
**라벨:** `ready-for-agent`

**Files:**
- Create: `harness/stream.py`, `api/chat.py`, `tests/ui_stream.py`
- Modify: `domain.py`, `harness/brain.py`, `harness/dispatcher.py`, `harness/conversations.py`, `store/repos/state.py`, `store/repos/conversations.py`, `tools/mcp_adapter.py`, `bot/commands.py`, `bot/telegram_io.py`(`_answer_command`가 공통 함수를 부른다), `app.py`, `api/models.py`, `api/server.py`, `tests/fakes.py`
- Test: `tests/test_api_chat.py`, `tests/test_dispatcher_app_channel.py`, `tests/test_stream.py`, `tests/test_brain_options.py`

**Interfaces**
- Consumes: `Dispatcher._handle_messages`·`_drain_messages`·`_call_brain`, `StateRepo` 대기 메시지, `IdempotencyRepo`, `apply_action`, `command_of`, `today_text`, `build_planner_server` (SP1, 04)
- Produces:

`harness/stream.py`
- `class StreamSink(Protocol)`: `emit(chunk: dict[str, Any]) -> None`, `ping() -> None`, `@property disconnected -> bool`
- `QueueSink()`: 연결마다 `attach() -> asyncio.Queue[bytes | None]`, `detach(q)`, `close()`(모든 큐에 None). 연결이 하나도 없으면 `disconnected`. M8을 위해 여럿을 붙일 수 있고, 붙는 순간 지금까지의 조각을 다시 넣어 준다.
- `encode_sse(chunk: dict) -> bytes`(`data: <JSON>\n\n`, `ensure_ascii=False`), `SSE_DONE = b"data: [DONE]\n\n"`, `SSE_PING = b": ping\n\n"`, `PING_INTERVAL_S = 15`
- `UiMessageWriter(sink: StreamSink, message_id: str)`: `start(metadata: dict)`, `status(state: Literal["queued", "thinking"])`(`transient: true`), `start_step()`, `text_start(id)`, `text_delta(id, delta)`, `text_end(id)`, `text(id, whole: str)`, `tool_input(call_id, name, input)`, `tool_output(call_id, output)`, `tool_error(call_id, text)`, `finish_step()`, `data_activity(activity_ids, undo_ids)`, `finish(metadata)`, `@property streamed_text -> bool`
- `AppReplySender`: `async send(out: Outbound) -> None`: `out.writer`에 (두뇌 글이 조각으로 나가지 않았으면 `out.text`를 글 블록 하나로) → 확인 문구 블록(`id="h-confirm"`) → 하네스 화면 조각(티켓 12) → `data_activity` → `finish`. 싱크가 끊겼으면 조용히 그만둔다(M7). `async typing()`은 아무것도 하지 않는다.

`domain.py` / `dispatcher.py`
- `RunContext.stream: UiMessageWriter | None = None`
- `Inbound`에 `channel: Channel = "telegram"`, `client_msg_id: str | None = None`, `checkin_id: int | None = None`, `sink: QueueSink | None = None`, `conversation_id: int | None = None`(앱 메시지는 받을 때 정한다)
- `Outbound`에 `channel: Channel = "telegram"`, `confirmation: str = ""`, `writer: UiMessageWriter | None = None`, `activity_ids: list[int]`, `undo_ids: list[int]`
- `Dispatcher(..., app_sender: AppReplySender | None = None)`. 텔레그램은 지금 `sender` 그대로(SP1 호출과 시험이 바뀌지 않게). 통로별 보낼 곳 `self._senders = {"telegram": sender, "app": app_sender}`.
- `_drain_messages(lead: Inbound) -> list[Inbound]`: `lead`가 앱이거나 `recovered`면 `[]`. 텔레그램이면 텔레그램 메시지만 꺼내고 나머지는 제자리(M2).
- `Dispatcher.route_app_message(at: datetime, *, conversation_id: int | None, checkin_id: int | None) -> Conversation`: 동기. 앱 통로의 대화 규칙(이 티켓: 열린 앱 `plan` → 요청한 `conversation_id`가 앱의 열린 `chat`이고 30분 안이면 그것 → 30분 안의 앱 `chat` → 새 앱 `chat`)으로 고르고 `touch`한다. 07이 회차 규칙을 앞에 넣는다.
- `Dispatcher.attach_stream(client_msg_id: str, sink: QueueSink) -> bool`: 처리 중(큐 대기 포함, 다시 넣은 `sink=None` 행 포함)이면 그 처리의 싱크에 붙이고 True(M8).
- 앱 메시지 처리: 하루 상한·사용 한도·로그인·글 아님은 SP1 고정 문구를 글 블록으로 보내고 정상 `finish`. 처리 완료는 `StateRepo.finish_app_inbound(update_id: int, *, client_msg_id: str, conversation_id: int, reply_text: str) -> None`(`api_idempotency(endpoint='chat')` 쓰기 + `inbound_pending` 삭제, 한 트랜잭션, `telegram_updates`에는 쓰지 않음, M5) → 원문 기록 `channel="app"`.
- 다시 넣기(M6): `resubmit_inbound`가 `channel='app'` 행을 `sink=None`으로 넣는다. 답은 어디에도 보내지 않고 M5로 끝낸다.

`store/repos/state.py`
- `PendingInbound`에 `channel: str = "telegram"`, `client_msg_id: str | None = None`, `checkin_id: int | None = None`
- `add_pending_inbound(update_id, text_redacted, sent_at, received_at, *, channel="telegram", client_msg_id=None, checkin_id=None)`
- `next_app_inbound_id() -> int`: `app_state.app_inbound_seq`에서 −1, −2, …
- `pending_by_client_msg_id(client_msg_id) -> PendingInbound | None`

`harness/brain.py`
- `build_options(..., include_partial_messages: bool = False, fork_session: bool = False)`(fork는 07이 쓴다)
- `ClaudeBrain.run`: `run_ctx.stream`이 있으면 `include_partial_messages=True`로 부르고, `StreamEvent`의 글 조각(S11에서 정한 필드 경로)을 `text_start/delta/end`로 보낸다. S11이 실패였으면 끝난 뒤 `text()` 하나로 보낸다.
- 시스템 프롬프트: `run_ctx.channel == "app"`이면 `system.md` + `channel_app.md`(티켓 12가 내용을 채운다. 이 티켓은 빈 파일 자리만).

`tools/mcp_adapter.py`
- `call_tool(tools: Any, ctx: RunContext, name: str, args: dict) -> dict`: 메서드 호출. `ctx.stream`이 있으면 호출 전 `tool_input`(이름은 앞머리 없음), 뒤 `tool_output(to_api_times(result))` 또는 `{"error"}`면 `tool_error`. `_handler`는 이것을 감싼다.
- `tool_names_for(channel: Channel) -> list[str]`: 이 티켓은 둘 다 `TOOL_NAMES`. 12가 앱 전용을 더한다. `build_planner_tools`는 `tool_names_for(ctx.channel)`을 쓴다.

`bot/commands.py`
- `@dataclass CommandDeps(tasks, conditions, state, router, clock, settings, apply: Callable[[ActionRequest], ActionResult])`
- `run_command(cmd: str, text: str, deps: CommandDeps, *, channel: Channel) -> str`: `/today`, `/week`, `/help`, `/pause`, `/unpause`, `/done`의 답 글(텔레그램 `_answer_command`와 앱이 같이 쓴다). 상태를 바꾸는 셋은 `apply`로 내부 동작 `cmd_pause`, `cmd_unpause`, `cmd_done`(`ACTIONS`, `public=False`)을 부른다.

`api/chat.py`
- `post_chat(request) -> web.StreamResponse`: 본문 `ChatRequestBody(client_msg_id: str, conversation_id: int | None, checkin_id: int | None, message: {id, role: "user", parts: [...]})`.
  1. `api_idempotency`에 있으면 저장한 `reply_text`를 글 블록 하나로 재생(두뇌 없음).
  2. 처리 중이면 `attach_stream`(M8), `data-status: queued`부터.
  3. `parts`의 `text`를 이어 붙인다. `command_of`가 `/plan` 말고 명령이면 `run_command` → 글 블록 하나, `api_idempotency(endpoint='chat', response_json={"conversation_id": null, "reply_text"})`.
  4. 아니면 `/plan`이면 앱 계획 대화를 열고(`router.start_plan(channel="app")`), `route_app_message` → 가린 글을 `add_pending_inbound(next_app_inbound_id(), …, channel="app")` → `submit_message(Inbound(channel="app", sink=…, conversation_id=…))`.
  - 응답 헤더: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `x-vercel-ai-ui-message-stream: v1`, `x-conversation-id: <id>`. 기다리는 동안 15초마다 `: ping`(주입한 `sleep`). 끝에 `data: [DONE]`.
  - `messageId`는 `m-<conversation_id>-<|inbound_id|>`, `messageMetadata`는 `{"conversation_id", "channel": "app", "kind": "chat" | "plan" | "run", "checkin_id"}`.
- 모델 `ChatRequestBody`.

`tests/fakes.py`
- `FakeTurn.deltas: list[str] | None = None`: 있으면 `run_ctx.stream`에 그 조각들로 글 블록을 보낸다(없으면 `text` 하나).
- `FakeBrain`: `run_ctx.stream`이 있으면 도구를 `call_tool`로 부른다(SP1 시험의 경로는 그대로). 받은 `fork_session` 인자를 `calls`에 기록한다.
- `ListSink`: 조각을 목록에 모으는 `StreamSink`.

`tests/ui_stream.py`
- `parse_sse(body: bytes) -> list[dict]`: `data:` 줄을 JSON으로, `[DONE]` 확인, 주석 줄 무시. AI SDK `UIMessageChunk`의 형식 규칙(첫 조각 `start`, `text-*`의 `id` 짝, `tool-input-available` 뒤 같은 `toolCallId`의 출력, 마지막 `finish`)을 확인한다. 운영 앱 스레드가 기준 응답을 주면 `tests/fixtures/app_golden/*.sse`를 이 파서로 같이 읽는다.

**Slices**

스트림 (`tests/test_api_chat.py`, `BeEnv`, `FakeTurn([("add_task", {...})], "내일 치과를 추가할게요.", deltas=["내일 치과를 ", "추가할게요."])`)
- [ ] `test_chat_stream_order_and_headers`: 조각 `type` 순서가 정확히 `start, data-status, start-step, text-start, text-delta, text-delta, text-end, tool-input-available, tool-output-available, finish-step, text-start, text-delta, text-end, data-activity, finish`, 그 뒤 `[DONE]`. 확인 블록 `id == "h-confirm"`, 글이 `✓ 추가: 치과 → 내일`. 헤더 다섯 개 값이 위와 같다
- [ ] `test_tool_chunk_name_has_no_prefix_and_output_is_utc`: `toolName == "add_task"`, `output.scheduled_at`이 `Z`
- [ ] `test_data_activity_ids_are_undoable`: `data-activity.undo_ids`의 id로 `/activity/{id}/undo` → 200
- [ ] `test_daily_cap_rate_limit_login_are_text_chunks` (매개변수 3): `error` 조각 없음, 글이 SP1 고정 문구, 정상 `finish`
- [ ] `test_non_text_parts_get_non_text_reply`
- [ ] `test_same_client_msg_id_replays_without_brain`: 두 번째 요청 뒤 `len(env.brain.calls) == 1`, 글 블록 하나가 첫 답 + 확인 문구
- [ ] `test_disconnect_mid_stream_completes` (M7): 첫 `text-delta` 뒤 끊으면 할 일 1개, 원문 기록 `@app` 두 줄, `api_idempotency` 행, `inbound_pending` 없음
- [ ] `test_inflight_duplicate_attaches_single_brain_call` (M8)
- [ ] `test_ping_every_15s_while_queued`: 텔레그램 회차가 두뇌를 잡고 있는 동안 `: ping` 줄
- [ ] `test_commands_in_app` : `/today` 글이 텔레그램 `today_text`와 같고 두뇌·`inbound_pending` 없음. `/pause 3`은 `pause_until`을 쓰고 같은 `client_msg_id` 재요청은 다시 실행하지 않는다. `/plan 이사 준비`는 두뇌 스트림, `messageMetadata.kind == "plan"`
- [ ] `test_parser_reads_spec_example`: 스펙 6.4.1의 예시 본문을 `parse_sse`가 오류 없이 읽는다

섞인 큐 (`tests/test_dispatcher_app_channel.py`, SP1 `Env` + `app_sender`)
- [ ] `test_mixed_queue_batches_telegram_only`: 처리 중 텔레그램 2·앱 2가 쌓이면 두뇌 호출 3회(텔레그램 묶음 1 + 앱 2), 텔레그램 답은 FakeSender 1개, 앱 싱크 두 개가 각자 답, 대화 id가 섞이지 않는다
- [ ] `test_app_done_writes_no_telegram_updates`: `telegram_updates`에 음수 id 없음
- [ ] `test_recovered_app_row_replies_nowhere` (M6): FakeSender 0개, `reply_text`·원문 기록·`api_idempotency`만
- [ ] `test_daily_cap_shared_by_channels`: 텔레그램 30 + 앱 30 뒤 61번째(어느 통로든) 고정 문구
- [ ] `test_app_tool_set_is_channel_specific`: `build_planner_tools(tools, RunContext(..., channel="app"))`의 이름 == `tool_names_for("app")`

두뇌 (`tests/test_brain_options.py`)
- [ ] `test_stream_events_become_text_deltas`: 가짜 SDK 메시지(`StreamEvent` 셋 + `ResultMessage`)로 `ListSink`에 `text-start, text-delta×3, text-end`
- [ ] `test_partial_messages_only_when_streaming`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_chat_end_to_end`: `POST /chat`("내일 치과 추가해 줘") → `parse_sse` 통과 → `GET /conversations?channel=app`에 그 대화, `GET /conversations/{id}/messages`에 사용자·비서 두 줄(`tools == ["add_task"]`) → 텔레그램 `/today`(다음 날 시계)에 치과. → `passed`

**마무리**
- [ ] 운영 앱 스레드에 `parse_sse`가 확인하는 규칙과 기준 응답 자리를 알린다(이 저장소 이슈 한 줄).
- [ ] **Review + Commit** `feat(api): POST /chat with AI SDK UI message stream and per-channel brain lane`

---

### 티켓 07: 통로별 대화 규칙, 가르기, 답한 회차

**목표:** 스펙 7.1~7.2: 텔레그램과 앱의 `chat`·`plan` 대화가 서로 잇지 않고, 회차에 다른 통로에서 답하면 그 통로에 회차 대화를 갈라 만든다(`fork_session`). 한쪽에서 답하면 `runs.answered_at`·`answered_via`가 한 번 적히고 텔레그램 버튼이 거둬진다. 두뇌는 다른 통로에서 바뀐 것을 알림으로 받는다.
**막는 티켓:** 06
**라벨:** `ready-for-agent`

**Files:**
- Modify: `harness/conversations.py`, `harness/dispatcher.py`, `harness/context.py`(`build_notices`), `harness/checkins.py`, `store/repos/conversations.py`, `store/repos/runs.py`, `store/repos/channels.py`, `store/repos/activity.py`, `bot/telegram_io.py`, `bot/callbacks.py`, `tools/actions.py`, `tests/fakes.py`
- Test: `tests/test_dispatcher_channels.py`, `tests/test_api_checkins.py`

**Interfaces**
- Consumes: `ConversationRouter`, `route_app_message`, `RunsRepo`, `DeliveriesRepo`, `apply_action`, `build_options(fork_session=…)` (SP1, 06)
- Produces:
- `ConversationsRepo.open(kind, logical_date, run_id=None, *, channel: Channel = "telegram", forked_from: int | None = None)`, `latest_open(kind, channel: Channel = "telegram")`, `run_conversation(run_id: int, channel: Channel) -> Conversation | None`, `set_channel(id, channel)`. `latest_open_run_opened_by(at)`는 통로와 상관없이 그대로(규칙 3).
- `ConversationRouter.for_user_message(at, *, sent_at=None, channel: Channel = "telegram", checkin_id: int | None = None) -> Conversation`: 스펙 7.2 규칙 1~5 순서. 규칙 1·3에서 이 통로 쪽 회차 대화가 없으면 `open(run, …, channel, forked_from=<원래 대화>)`. `start_plan(channel="telegram")`, `end_plan(channel="telegram")`, `plan_open()`은 어느 통로든 열린 계획 대화가 있으면 True(회차 대기 규칙).
- `Dispatcher.route_app_message`는 `for_user_message(channel="app", checkin_id=…)`를 쓴다.
- 가르기: 대화가 `forked_from`이 있고 `session_id`가 없으면 첫 두뇌 호출을 `session_id=<원래 대화 session_id>`, `fork_session=True`로. `resume_failed`면 SP1 대체 경로 + 원래 회차의 `runs.outbound_text`를 `## 회차 메시지`로 앞에 붙인다.
- `Brain.run(prompt, *, session_id, run_ctx, fork_session: bool = False) -> BrainResult`(프로토콜과 `ClaudeBrain`, `FakeBrain`)
- `RunsRepo.mark_answered(id: int, channel: Channel, at: datetime) -> bool`(`answered_at IS NULL`일 때만 True)
- `Dispatcher.mark_answered(run_id: int, channel: Channel) -> bool`: 합쳐 보낸 묶음이면 primary에 적는다. 처음이면 텔레그램 버튼 거두기를 예약한다(`telegram_message_id`가 있으면 `TelegramSender.clear_buttons(message_id)`, 안 되면 `buttons_clear_error` 로그만). 티켓 15가 X3/X5/X8을 같은 트랜잭션에 더한다.
- 답으로 치는 것: 그 회차 대화(어느 통로든)의 사용자 메시지(디스패처, 답장 창 안, 보낸 시각 기준), 그 회차의 버튼, 같은 일을 하는 `/actions`. `harness/checkins.py run_answered_by(req: ActionRequest, *, runs, tasks, settings, now) -> int | None`: `record_condition(date=d)` → `d`가 논리적 날짜인 보낸 저녁 체크인(답장 창 안), `confirm_tasks`·`drop_task` → 그 초안을 낸 회차(`tool_events_log.run_id`). 14가 사다리를 더한다. `apply_action`이 적용 뒤 부른다. 텔레그램 버튼은 `query.message.message_id` → `DeliveriesRepo.run_for_message(message_id) -> int | None`으로 회차를 찾는다.
- 회차 전달 기록(텔레그램, SP1 경로): `TelegramSender.send(out) -> int | None`(버튼이 붙은 마지막 조각의 `message_id`)과 `DeliveriesRepo.record(run_id, channel, mode: Literal["full", "fallback"], status: Literal["sent", "not_sent"], *, telegram_message_id=None, push_ok=0, push_failed=0) -> None`, `.telegram_message_id(run_id) -> int | None`, `.run_for_message(message_id) -> int | None`. `_run_delivered`가 기록한다. 08이 앱·대체를 더한다.
- 다른 통로 알림: `build_notices(..., elsewhere: list[str] | None = None)` → `## 다른 곳에서 바뀐 것` + 최대 5줄. 줄은 `ActivityRepo.other_channel_since(after: datetime, channel: Channel, limit: int = 5) -> list[Activity]`의 `summary`. 기준은 이 대화의 `last_message_at`.
- `FakeSender.cleared: list[int]`, `async clear_buttons(message_id)`

**Slices** (`tests/test_dispatcher_channels.py`)
- [ ] `test_telegram_chat_and_app_chat_do_not_continue`: 텔레그램 chat 10분 뒤 앱 메시지 → 새 앱 대화, 그 뒤 텔레그램 메시지 → 원래 텔레그램 대화
- [ ] `test_plan_is_per_channel_but_runs_wait_for_any`: 앱 `/plan` 동안 텔레그램 메시지는 텔레그램 chat, 17:30 회차는 대기
- [ ] `test_run_reply_from_other_channel_forks`: 텔레그램으로 보낸 저녁 체크인에 앱 답(창 안) → 앱 쪽 `kind=run`, 같은 `run_id`, `forked_from` = 텔레그램 대화, FakeBrain 호출이 `session_id="s-run"`, `fork_session=True`. 두 번째 앱 답은 앱 쪽 세션을 resume(`fork_session=False`)
- [ ] `test_fork_failure_falls_back_with_outbound_text`: `resume_failed=True` → 새 세션 프롬프트에 회차 본문
- [ ] `test_checkin_id_within_window_targets_run`, `test_checkin_id_outside_window_falls_through_to_rule_2`
- [ ] `test_other_channel_notice_max_5_lines`: 앱 `/actions` 7회 뒤 텔레그램 메시지 → 프롬프트에 `## 다른 곳에서 바뀐 것`과 최근 5줄, 같은 통로 변경은 없음
- [ ] `test_answered_once_first_channel_wins`: 앱 답 뒤 텔레그램 답 → `answered_via == "app"` 그대로
- [ ] `test_answer_clears_telegram_buttons`: `FakeSender.cleared == [<그 회차 message_id>]`
- [ ] `test_condition_action_answers_evening_checkin`: `/actions record_condition(date=그날)` → `answered`, 다른 날짜 → 그대로
- [ ] `test_draft_button_answers_its_run`
- [ ] `test_late_reply_by_sent_at`: 노트북이 잠든 동안 03:50에 보낸 텔레그램 답을 05:00에 받아도 그 저녁 체크인의 답

답할 회차 API (`tests/test_api_checkins.py`)
- [ ] `test_checkin_detail_conversation_ids_per_channel`: `{"app": 44, "telegram": 41}`
- [ ] `test_states_pending_answered_missed_by_sent_time`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_answer_from_app_closes_telegram`: 17:30 tick → 텔레그램 체크인(FakeSender) → 18:00 `POST /chat {checkin_id}` → `GET /checkins/{id}`가 `answered`/`app`, `FakeSender.cleared`에 그 메시지, FakeBrain의 두 번째 호출이 `fork_session=True`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: per-channel conversations, run forking and answered check-ins`

---

### 티켓 08: 웹 푸시와 회차 전달 (D1~D8)

**목표:** 주 통로(`app` 기본)와 유효한 푸시 구독에 따라 회차를 웹 푸시 또는 텔레그램으로 보낸다(스펙 7.3 D1~D8). 푸시가 하나도 안 되면 텔레그램으로 대체하고, 404/410 구독은 끈다. 하루 3회 상한은 회차마다 1. `/push/*`, `/settings/notify`, `gen-vapid`를 연다.
**막는 티켓:** 07
**라벨:** `ready-for-agent`

**Files:**
- Create: `harness/delivery.py`, `api/push.py`
- Modify: `config.py`(VAPID), `cli.py`, `harness/dispatcher.py`(`_send_run`, `_resend_run`, `_send_notice`), `store/repos/push.py`, `store/repos/channels.py`, `api/health.py`, `api/server.py`, `api/models.py`, `tools/actions.py`, `app.py`, `pyproject.toml`, `requirements.lock`, `.env.example`, `tests/fakes.py`
- Test: `tests/test_delivery.py`, `tests/test_api_push.py`

**Interfaces**
- Consumes: `_run_delivered`, `send_with_retry`, `DeliveriesRepo.record`, `ConversationsRepo.set_channel`, `apply_action` (SP1, 04, 07)
- Produces:

`config.py`: `VapidConfig(public_key: str, private_key: SecretStr, subject: str)`, `Settings.vapid: VapidConfig | None`(`.env`의 `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`가 모두 있을 때만). `cli.py gen-vapid`: `VAPID_PUBLIC_KEY=<base64url>`와 `VAPID_PRIVATE_KEY=<…>` 두 줄을 출력.

`store/repos/push.py` `PushRepo` 쓰기
- `@dataclass PushSubscription(id, endpoint, p256dh, auth, label, last_success_at, failure_count, disabled_at)`
- `upsert(endpoint, p256dh, auth, label) -> int`(같은 endpoint면 키를 바꾸고 같은 id, 꺼진 구독이면 다시 켠다), `delete(id) -> bool`, `active() -> list[PushSubscription]`, `record_ok(id, at)`, `record_failure(id, *, gone: bool, at) -> None`(gone이면 `disabled_at`, 아니면 `failure_count + 1`, 5가 되면 `disabled_at`)

`harness/delivery.py`
- `class PushSender(Protocol)`: `send(sub: PushSubscription, payload: dict, *, ttl: int, topic: str) -> int`(HTTP 상태. 네트워크 오류는 예외. 동기)
- `WebPushSender(private_key: str, subject: str)`: `pywebpush.webpush(..., ttl=ttl, headers={"Topic": topic})`
- `effective_channel(primary: Channel, active_subscriptions: int, push_enabled: bool) -> Channel`(D1a)
- `push_payload(run: Run, text: str, *, reply_until: datetime) -> tuple[dict, int, str]`: 6.4.8 `{"type": "checkin", "checkin_id", "title", "body", "url": "/checkins/<id>"}`, `title`은 부록 A(아침 브리핑 / 저녁 체크인 / 주간 회고 / 다시 이어서), `body`는 본문 첫 줄 120자, TTL = 답장 창 끝까지 초, `topic = "run-<id>"`. `notice_payload(text) -> dict`(`type: "notice"`, `title: "알림"`).
- `@dataclass DeliveryOutcome(channel: Channel, mode: Literal["full", "fallback"], sent: bool, telegram_message_id: int | None, push_ok: int, push_failed: int)`
- `Delivery(*, telegram: Sender, push: PushSender | None, pushes: PushRepo, state: StateRepo, clock, settings, sleep, to_thread=asyncio.to_thread)`
  - `effective() -> Channel`(`app_state.notify_primary` 또는 `notify.default_primary`)
  - `async deliver_run(run: Run, out: Outbound, *, reply_until: datetime) -> DeliveryOutcome`: D2 텔레그램 전체(SP1 3회) / D3 구독마다 3회(1초·2초 간격), 하나라도 201이면 끝 / D4 모두 안 되면 텔레그램 전체(`fallback`). 보내기는 `to_thread`, 결과 기록(`record_ok`, `record_failure`)은 루프 스레드.
  - `async deliver_notice(text: str) -> bool`(D8)
  - `async push_test() -> tuple[int, int]`(ok, failed. 상한에 세지 않는다)
- 디스패처: `Dispatcher(..., delivery: Delivery | None = None)`. 있으면 `_send_run`이 `deliver_run`을 쓰고, `DeliveriesRepo.record`로 결과를 남기며, 회차 대화의 통로를 전체 본문을 받은 통로로 `set_channel`(D5). `proactive_messages`는 `_run_delivered`에서 회차마다 1(D6). 5분 뒤 재전송은 전달이 하나도 안 된 회차에만 같은 순서로(D7). 고정 안내는 `deliver_notice`, DB 안전 모드 안내는 SP1 그대로 텔레그램만.
- `api/health.py`: `notify.effective`는 `effective_channel(...)`, `push` 필드는 `PushRepo`.
- `ACTIONS`(내부, 활동 남김, 되돌릴 수 없음): `push_subscribe`(`push_subscribed`), `push_unsubscribe`(`push_unsubscribed`), `notify_set`(`notify_changed`), `push_test_result`. 활동 `summary`와 로그에 `endpoint`는 없다(예: "푸시 구독: 폰").
- `api/push.py`: `get_vapid_key` → `{"public_key"}`, `post_subscription`(`PushSubscriptionBody`) → `201 {"id"}`, `delete_subscription` → `204`/`404`, `post_push_test` → `{"ok", "failed"}`, `get_notify`·`put_notify` → `{"primary", "effective", "push_subscriptions"}`. VAPID가 없으면 `/push/*`는 `404 not_found`이고 실제 통로는 늘 `telegram`.
- `tests/fakes.py FakePushSender(results: dict[str, list[int | Exception]])`: 구독 endpoint마다 응답을 차례로 준다. `sent: list[tuple[str, dict, int, str]]`.

**Slices** (`tests/test_delivery.py`, SP1 `Env` + `Delivery`)
- [ ] `test_default_app_without_subscription_goes_telegram` (D1a): `effective() == "telegram"`, 텔레그램 1, 푸시 0
- [ ] `test_primary_telegram_full_telegram_no_push` (D2)
- [ ] `test_primary_app_push_ok_no_telegram` (D3): 페이로드 `type == "checkin"`, `title == "아침 브리핑"`, `topic == "run-<id>"`, TTL = 12:00까지 초, `run_deliveries`(`app`, `full`, `sent`, `push_ok=1`)
- [ ] `test_all_push_fail_falls_back_to_telegram` (D4): 구독 둘 다 500 → 각 3회, 텔레그램 1, `mode == "fallback"`
- [ ] `test_404_410_disable_without_retry`: 410 구독은 1회만, `disabled_at` 있음
- [ ] `test_five_consecutive_failures_disable_then_next_run_starts_telegram`
- [ ] `test_proactive_counter_once_per_run` (D6): D2·D3·D4 각각 `proactive_messages == 1`
- [ ] `test_resend_after_5_minutes_only_if_nothing_delivered` (D7)
- [ ] `test_run_conversation_channel_follows_full_body` (D5)
- [ ] `test_notice_goes_to_effective_channel_and_safe_mode_telegram_only` (D8)
- [ ] `test_paused_runs_silent_on_both_channels`

API (`tests/test_api_push.py`)
- [ ] `test_vapid_public_key`, `test_subscribe_same_endpoint_same_id`, `test_delete_subscription_204_then_404`
- [ ] `test_push_test_not_counted_in_daily_cap`
- [ ] `test_settings_notify_get_put_effective`: 구독 없이 `PUT {"primary": "app"}` → `effective == "telegram"`, 구독 등록 뒤 `app`
- [ ] `test_push_routes_404_without_vapid`
- [ ] `test_push_endpoint_never_logged_or_in_activity`: 시험 endpoint 문자열이 로그 파일과 `activity` 어디에도 없다

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_push_delivery_and_fallback`: `POST /push/subscriptions` → 10:00 tick → `FakePushSender.sent` 1, `FakeSender.sent` 0, `GET /health`의 `proactive.sent_today == 1`, `runs_today[0].delivered_via == ["app"]`. 그 구독을 410으로 바꾸고 17:30 tick → 텔레그램으로 오고 구독 꺼짐 → 다음 날 10:00 tick은 처음부터 텔레그램(`effective == "telegram"`). → `passed`

**마무리**
- [ ] `.env.example`에 `VAPID_*` 자리 표시.
- [ ] **Review + Commit** `feat: web push delivery with Telegram fallback and notify settings`

---

### 티켓 09: 인생 곡선 데이터 계층

**목표:** 곡선 표의 쓰기 함수와 곡선 도구 함수(사다리, 영역 점수, 사건·챕터 초안 확정과 빼기)를 만들고 `/actions`와 되돌리기에 잇는다. 사건·챕터 초안은 빼거나 3일 지나면 **행을 지운다**. 고점·전환점을 확정하면 칭호가 생기고, 확정을 되돌리면 칭호가 지워진다. 바뀔 때마다 `data/curve/chapters.md`를 다시 만든다.
**막는 티켓:** 03, 05
**라벨:** `ready-for-agent`

**Files:**
- Modify: `store/repos/curve.py`(쓰기), `store/repos/status.py`(칭호), `store/exports.py`, `tools/core.py`, `tools/confirmations.py`, `tools/actions.py`, `tools/activity.py`, `loop/runner.py`, `app.py`
- Test: `tests/test_curve_actions.py`, `tests/test_curve_drafts.py`

**Interfaces**
- Consumes: `CurveRepo` 읽기(03), `ActivityRepo`, `register_undo`, `apply_action`(04, 05)
- Produces:

`CurveRepo` 쓰기
- `add_chapter(*, title, start_month, status: Literal["draft", "confirmed"], origin: Literal["seed", "chat", "review"], end_month=None, theme=None, sketch=None, certainty="fact", seed_key=None, source_ref=None) -> Chapter`(초안이면 `draft_since = 지금`)
- `add_milestone(*, date_text, kind, title, status, origin, note=None, chapter_id=None, sensitive=False, certainty="fact", kind_certainty="fact", conversation_id=None, source_ref=None) -> Milestone`(`precision`과 `sort_date`는 `date_text` 모양에서: `2019` → `year`/`2019-01-01`)
- `confirm_milestones(ids) -> list[Milestone]`, `confirm_chapters(ids) -> list[Chapter]`(초안만, `draft_since = NULL`, `confirmed_at`)
- `unconfirm_milestone(id, at)`, `unconfirm_chapter(id, at)`(되돌리기: `draft`, `draft_since = at`)
- `delete_milestone_draft(id) -> bool`, `delete_chapter_draft(id) -> bool`(확정 행은 False)
- `expire_drafts(older_than: datetime) -> tuple[list[int], list[int]]`(`draft_since` 기준 삭제)
- `set_ladder(period, *, now: int | None, future: int | None, note) -> Ladder`(없는 쪽은 그 달 기존 값을 둔다), `restore_ladder(period, before: Ladder | None)`
- `set_area_scores(period, scores: dict[Area, int], *, notes: dict | None, quests: dict | None) -> None`, `restore_area_scores(period, before: dict[Area, AreaScore])`
- `set_area_default(area, quest)`, `add_question(text) -> int`, `next_open_question() -> tuple[int, str] | None`, `mark_question(id, status)`

`StatusRepo`: `add_title(milestone_id, at) -> None`(`high`·`turning_point`만 부른다), `remove_title(milestone_id) -> None`. (원장에는 쓰기 함수가 아직 없다. 15가 `grant`만 더한다.)

`tools/core.py` `Tools(..., curve: CurveRepo | None = None, status: StatusRepo | None = None, review_date_for: Callable[[RunContext], date | None] | None = None)`
- `record_ladder_score(ctx, period=None, now=None, future=None, note=None) -> dict`: 둘 다 없으면 오류, 0~10 밖 오류, 미래 달 거절. 기간 기본값은 10장: `review_date_for(ctx)`(그 대화가 회고 회차 대화면 회차 `scheduled_for`의 논리적 날짜)가 든 달, 아니면 오늘. ToolEvent `ladder_recorded`.
- `record_area_scores(ctx, scores, period=None, notes=None, recovery_quests=None) -> dict`: 1~10, 영역 이름 검사, `recovery_quests`는 지난 분기보다 내려간 영역에만·80자 이하. ToolEvent `area_scores_recorded`.
- `confirm_milestones(ctx, ids)`, `confirm_chapters(ctx, ids)`: 결과 `{"confirmed": [...], "skipped_ids": [...]}`, 칭호가 생기면 이벤트 데이터에 `title_name`.
- `drop_curve_drafts(ctx, milestone_ids=None, chapter_ids=None)`: 확정한 것은 오류(`"확정한 사건은 뺄 수 없어요."`). ToolEvent `milestone_dropped`·`chapter_dropped`.
- 바뀐 뒤 `export_curve(curve, data_dir / "curve" / "chapters.md")`.

`store/exports.py`: `export_curve(repo: CurveRepo, path: Path) -> None`: 챕터와 확정 사건, 민감 사건은 제목 대신 "(민감)".

확인 문구 (`confirmation_line`): 사건 확정 `✓ 저장: {제목} ({날짜}, {고점|저점|전환점})` + 칭호가 생기면 다음 줄 `칭호: {칭호}`, 빼기 `✗ 뺐어요: {제목}`(부록 A). 이 계획이 정한 것: 사다리 `✓ 사다리({YYYY-MM}): 지금 {n} · 5년 뒤 {m}`(없는 쪽은 뺀다), 영역 `✓ 영역 점수({YYYY-Qn}): 커리어 7 · 경제 5 …`(넣은 영역만), 챕터 확정 `✓ 저장: {제목} (챕터, {시작}~{끝|지금})`.

`ACTIONS` 추가: `record_ladder_score`, `record_area_scores`, `confirm_milestones`, `confirm_chapters`, `drop_milestone`(→ `drop_curve_drafts(milestone_ids=[id])`), `drop_chapter`, 내부 `expire_curve_drafts`(활동 `milestone_drafts_expired`, `chapter_drafts_expired`). `register_undo`: `ladder_recorded`, `area_scores_recorded`(이전 행, 없었으면 삭제), `milestones_confirmed`, `chapters_confirmed`(초안으로, `draft_since` = 되돌린 시각, 칭호 삭제). 빼기는 되돌릴 수 없다(행 삭제). 대상 문자열: `ladder:<YYYY-MM>`, `areas:<YYYY-Qn>`, `milestone:<id>`, `chapter:<id>`.

`loop/runner.py`: 하루 한 번 `expire_curve_drafts`(`limits.draft_ttl_days`).

**Slices**

도구와 동작 (`tests/test_curve_actions.py`, `BeEnv`)
- [ ] `test_ladder_future_only_first_then_now_keeps_future`
- [ ] `test_ladder_range_and_future_month_rejected`: `now=11` → 422, 다음 달 → 422
- [ ] `test_area_scores_range_names_and_quests_only_for_down`: 올라간 영역의 퀘스트 → 422, 81자 → 422
- [ ] `test_confirm_high_and_turning_grant_titles_low_does_not`
- [ ] `test_drop_milestone_deletes_row_and_confirmed_is_rejected`
- [ ] `test_dropping_chapter_draft_nulls_milestone_chapter_id`: FK 오류 없음
- [ ] `test_undo_ladder_and_areas_restore_or_delete`
- [ ] `test_undo_confirm_resets_draft_since_and_removes_title`: 1년 전에 만든 사건의 확정을 되돌려도 다음 날 tick 뒤 행이 남고, 3일 뒤 사라진다
- [ ] `test_period_default_from_review_conversation`: 11/29 회고 회차 대화에서 12/1에 `record_ladder_score(now=7)` → `period == "2026-11"`. 일반 대화면 `2026-12`
- [ ] `test_export_chapters_md_masks_sensitive`
- [ ] `test_confirmation_lines`: 위 문구 그대로, 금지어 없음

초안 (`tests/test_curve_drafts.py`, 러너)
- [ ] `test_curve_drafts_deleted_after_3_days_by_draft_since`: 2일 23시간 → 남음, 3일 → 없음, 활동 `milestone_drafts_expired`(`secretary`/`scheduler`)
- [ ] `test_drafts_not_in_get_curve_until_confirmed`: 완료 조건 6

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_curve_write_path`: `CurveRepo.add_milestone(status="draft", kind="high")`로 초안을 놓고 → `GET /curve`에 없음 → `POST /actions confirm_milestones` → `GET /curve`에 있음, `GET /status`의 `titles`에 `「…」의 순간` → 되돌리기 → 둘 다 없음 → `clock.advance(days=3)` + tick → 행 삭제. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(curve): curve data layer, draft deletion, titles and curve actions`

---

### 티켓 10: `seed-life` 시드 가져오기

**목표:** `python -m my_planner seed-life <파일> [--dry-run]`이 검토한 시드 파일(스펙 12장 형식)에서 챕터, 사건, 영역 기본 퀘스트, 질문을 한 트랜잭션으로 가져온다. 단일 실행 잠금을 잡고, 한 번만 가져오며, 내용은 출력하지 않는다.
**막는 티켓:** 09
**라벨:** `ready-for-agent`

**Files:**
- Create: `curve/seed.py`, `tests/fixtures/life_seed_example.json`(꾸며 낸 내용: 챕터 3, 사건 8 — 민감 미확인 1, `storage` 미확인 1, 날짜 오류 1 포함, 영역 6, 질문 2)
- Modify: `cli.py`, `.gitignore`(이미 세 패턴이 있는지 확인만)
- Test: `tests/test_seed_life.py`

**Interfaces**
- Consumes: `CurveRepo` 쓰기, `StatusRepo.add_title`, `export_curve`, `SingleInstanceLock`, `open_db`, `migrate` (09, SP1)
- Produces:
- `EXIT_OK = 0`, `EXIT_RUNNING = 3`, `EXIT_ALREADY = 4`, `EXIT_NOT_REVIEWED = 5`, `EXIT_BAD_FILE = 6`(이 계획이 정함: 읽을 수 없거나 JSON이 아니거나 최상위 모양이 틀림)
- `SkipReason = Literal["sensitive_unconfirmed", "storage_unconfirmed", "invalid"]`
- `load_seed(path: Path) -> dict`: `encoding="utf-8-sig"`(BOM 허용), `json.loads`
- `@dataclass SeedPlan(chapters: list[dict], events: list[dict], quests: dict[Area, str], sketches: dict[str, str], questions: list[str], skipped: Counter[SkipReason])`
- `plan_import(seed: dict) -> SeedPlan`(순수 함수): 확인 규칙(민감이거나 `storage` 키가 있으면 `confirmed: true`일 때만), `certainty` '사실'→`fact`·'추정'→`estimate`, `kind` 'turning'→`turning_point`, 날짜·`kind` 오류는 `invalid`, 건너뛴 챕터를 가리키는 사건의 `chapter_id`는 None, `areas[].score`·`evidence`·`sensitive_parts`와 `ladder`는 읽지 않는다.
- `apply_seed(conn, plan: SeedPlan, clock) -> dict[str, int]`: 한 트랜잭션. 모두 `status=confirmed`, `origin=seed`, 고점·전환점은 칭호(경험치 없음), 끝에 `app_state.life_seed_imported_at`.
- `run_seed_life(root: Path, file: Path, *, dry_run: bool, out: TextIO, lock_factory=SingleInstanceLock) -> int`: 잠금 실패 → 부록 A 문구 출력, 3. 이미 가져왔으면 4. `meta.reviewed is not True` → 5. 출력은 개수만:
  - `가져올 것: 챕터 {n}, 사건 {n}, 영역 퀘스트 {n}, 질문 {n}`
  - `건너뛸 것: {합} (sensitive_unconfirmed {n}, storage_unconfirmed {n}, invalid {n})`
  - 가져오면 마지막 줄 `가져왔어요.`, `--dry-run`이면 `--dry-run: 아무것도 쓰지 않았어요.`
- `cli.py seed-life <file> [--dry-run]`

**Slices** (`tests/test_seed_life.py`, 임시 루트, 꾸며 낸 고정 자료)
- [ ] `test_not_reviewed_imports_nothing_code_5`
- [ ] `test_sensitive_and_storage_only_when_confirmed`
- [ ] `test_scores_and_ladder_not_imported`: `curve_ladder_scores`, `curve_area_scores` 비어 있음, `curve_area_defaults` 6행 중 확인 규칙을 통과한 것만
- [ ] `test_turning_maps_to_turning_point_and_certainty_mapping`
- [ ] `test_skipped_chapter_nulls_event_chapter_id`
- [ ] `test_titles_for_high_and_turning_no_xp`: `status_xp_ledger` 0행
- [ ] `test_questions_are_open`, `test_sketch_goes_to_chapter`
- [ ] `test_second_run_code_4`
- [ ] `test_running_be_code_3_with_message`: `lock_factory`가 `AlreadyRunning`을 내면 정확히 "my-planner가 실행 중이에요. 작업 스케줄러에서 멈춘 뒤 다시 실행해 주세요."
- [ ] `test_second_instance_real_lock` (Windows 전용, 그 밖에서는 skip)
- [ ] `test_dry_run_counts_only_no_content`: `capsys` 출력에 고정 자료의 모든 `title`·`note` 문자열이 없고, DB가 그대로
- [ ] `test_bom_file_reads` (Review Focus 4): BOM을 붙여 쓴 사본으로 같은 개수
- [ ] `test_invalid_items_counted_not_printed` (Review Focus 4): `2019-13`, `kind: "peak"` → `invalid 2`, 내용 없음
- [ ] `test_not_json_code_6`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_seed_then_curve`: `run_seed_life(root, fixture, dry_run=False)` → 같은 루트로 `BeEnv` 시작 → `GET /curve?zoom=year`에 확정 챕터 3·사건(민감 제외), `GET /curve?zoom=year&include_sensitive=true`에 확인된 민감 사건, `GET /status`의 `titles` 개수 = 고점+전환점, `ladder == []`. FakeBrain이 `get_curve`를 부르는 텔레그램 대화(티켓 11 뒤에 돌리는 시험이면 `pytest.mark.skipif`로 두지 않고 이 수용 시험은 API만 본다). → `passed`

**마무리**
- [ ] README에 순서(노트북 `data/seed/`로 옮김 → `--dry-run` → 가져오기 → 노트북 밖 사본 지우기)는 티켓 19에서 쓴다. 여기서는 `python -m my_planner seed-life --help` 출력만 확인한다.
- [ ] **Review + Commit** `feat(curve): seed-life import CLI`

---

### 티켓 11: 곡선·상태 두뇌 도구와 사건 초안 버튼

**목표:** 두뇌가 마스터 5.3과 스펙 10장의 곡선·상태 도구를 쓴다(`grant_xp`는 15). 대화에서 꺼낸 사건과 챕터는 초안이고, 텔레그램 답 아래에 `✓ 저장` `✗ 빼기` `전부 저장` 버튼이 붙는다. 자연어 확정과 빼기도 된다. `system.md`에 원칙 9~11을 더한다.
**막는 티켓:** 09, 06
**라벨:** `ready-for-agent`

**Files:**
- Modify: `tools/core.py`, `tools/mcp_adapter.py`, `harness/dispatcher.py`(`_outbound`), `bot/telegram_io.py`, `bot/callbacks.py`, `harness/prompts/system.md`, `app.py`
- Test: `tests/test_curve_tools.py`, `tests/test_telegram_curve.py`, `tests/test_prompts.py`(SP1 금지어 시험 그대로)

**Interfaces**
- Consumes: 09의 `Tools` 곡선 메서드, `curve_view`, `status_snapshot`, `apply_action`, `message_keyboard` (03, 04, 09)
- Produces:
- `Tools.add_milestone(ctx, date, kind, title, note=None, chapter_id=None, sensitive=False) -> dict`: 초안(`origin=chat`, `conversation_id=ctx.conversation_id`), ToolEvent `milestone_proposed`(확인 문구 없음, 버튼이 대신)
- `Tools.propose_chapter(ctx, title, start, theme=None, end=None) -> dict`: 초안, ToolEvent `chapter_proposed`
- `Tools.get_curve(ctx, from_=None, to=None, zoom="month") -> dict`: `curve_view`를 줄인 것. 민감 사건은 `title: "(민감)"`, `note` 없음. JSON 스키마 키는 `from`·`to`
- `Tools.get_status(ctx) -> dict`: `status_snapshot(...)` 그대로
- `TOOL_NAMES`에 `record_ladder_score`, `record_area_scores`, `add_milestone`, `confirm_milestones`, `propose_chapter`, `confirm_chapters`, `drop_curve_drafts`, `get_curve`, `get_status` 9개(설명은 스펙 10장 표의 "하는 일").
- `Outbound`에 `draft_milestone_ids: list[int]`, `draft_chapter_ids: list[int]`(`milestone_proposed`, `chapter_proposed` 이벤트에서 채운다)
- `bot/telegram_io.py`: `milestone_keyboard(ids: list[int], conversation_id: int | None, titles: dict[int, str]) -> list[list[InlineKeyboardButton]]`(초안마다 `✓ 저장: {제목 16자}` `✗ 빼기` 콜백 `m:c:<id>`, `m:x:<id>`, 맨 아래 `전부 저장` `m:all:<대화 id>`), `chapter_keyboard(ids, titles)`(`h:c:<id>`, `h:x:<id>`). `message_keyboard` 줄 순서: 할 일 초안 → 사건 초안 → 챕터 초안 → 컨디션.
- `bot/callbacks.py`: `m:`·`h:`를 `apply_action`(`confirm_milestones`, `drop_milestone`, `confirm_chapters`, `drop_chapter`)으로. 이미 정리된 초안 → "이미 정리된 사건이에요.". 원문 기록 `[버튼] 저장: {제목}`, `[버튼] 빼기: {제목}`.
- `system.md` 원칙 9(사건과 챕터는 초안으로만, 추측해서 만들지 않고 "곡선에 남길까요?"와 함께), 10(점수는 사용자가 말한 숫자만), 11(점수가 내려가도 걱정하는 말 대신 회복 퀘스트 하나). 스펙 10장 문장 그대로.

**Slices**

도구 (`tests/test_curve_tools.py`, MCP 핸들러를 두뇌처럼 직접 await)
- [ ] `test_add_milestone_is_draft_not_in_curve`
- [ ] `test_milestone_date_precision_and_sort_date`: `2019` → `year`/`2019-01-01`, `2023-05` → `month`, `2023-05-07` → `day`, `2023-5` → 오류
- [ ] `test_sensitive_default_false`
- [ ] `test_confirm_milestones_by_natural_language`: FakeBrain이 `confirm_milestones` → 확인 문구와 칭호 줄
- [ ] `test_drop_curve_drafts_rejects_confirmed`
- [ ] `test_get_curve_masks_sensitive_title`, `test_get_status_equals_snapshot`
- [ ] `test_telegram_tool_count_21_before_grant_xp`: `len(tool_names_for("telegram")) == 21`

텔레그램 (`tests/test_telegram_curve.py`, `Update.de_json` 가짜 콜백)
- [ ] `test_milestone_buttons_layout_and_64_bytes`
- [ ] `test_m_all_confirms_only_this_conversation_drafts`
- [ ] `test_stale_milestone_button_reply`
- [ ] `test_button_reply_copy`: "✓ 저장: 제주 여행 (2019, 고점)"과 "칭호: 「제주 여행」의 순간", 빼기 "✗ 뺐어요: 제주 여행"
- [ ] `test_chapter_buttons`
- [ ] `test_system_prompt_has_principles_9_to_11`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_story_to_curve`: 텔레그램 "예전에 처음 혼자 제주 여행 갔을 때 정말 좋았어"(꾸며 낸 문장) → FakeBrain `add_milestone(date="2019", kind="high", title="제주 여행")` → FakeSender 메시지에 `m:c:<id>` 버튼 → 그 콜백 → `GET /curve?zoom=year`에 사건, `GET /status` 칭호. 3일 뒤 남은 다른 초안은 사라진다. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(curve): curve and status brain tools with milestone draft buttons`

---

### 티켓 12: 앱 전용 두뇌 도구 — 화면 조각과 고정 카드

**목표:** 앱 대화의 두뇌만 `ui_todo_list`, `ui_choice`, `ui_summary_card`(그리기만)와 `pin_card`, `unpin_card`, `reorder_cards`를 쓴다(스펙 6.4.7, 10장). 하네스는 초안 카드와 컨디션 고르기를 화면 조각(`h_`)으로 붙인다. `GET /today`의 `cards`가 고정 카드를 지금 값으로 채운다.
**막는 티켓:** 06, 05
**라벨:** `ready-for-agent`

**Files:**
- Create: `store/repos/cards.py`, `harness/prompts/channel_app.md`(내용)
- Modify: `tools/ui.py`, `tools/core.py`, `tools/mcp_adapter.py`, `tools/actions.py`, `tools/activity.py`, `harness/stream.py`(`AppReplySender`의 하네스 조각), `api/read.py`(`/today` cards), `app.py`
- Test: `tests/test_ui_tools.py`, `tests/test_cards.py`

**Interfaces**
- Consumes: `UI_COMPONENTS`, `validate_props`, `call_tool`, `tool_names_for`, `UiMessageWriter`, `todo_dict` (02, 06)
- Produces:
- `Tools.ui_todo_list(ctx, title, task_ids)`, `Tools.ui_choice(ctx, question, options)`, `Tools.ui_summary_card(ctx, title, lines)`: `validate_props`가 통과하면 `{"ok": true}`, 아니면 `{"error": …}`. DB·파일·`ctx.events`를 건드리지 않는다. 조각은 `call_tool`이 보낸다(오류면 `tool-output-error`, 그 컴포넌트 조각은 그려지지 않는다).
- `CardsRepo(conn, clock)`: `@dataclass Card(id, component, props: dict, sort_order, pinned_at, unpinned_at, conversation_id)`, `pin(component, props, conversation_id) -> Card`(맨 뒤), `unpin(id) -> Card | None`, `reorder(ids) -> None`(고정된 카드 전부가 아니면 `ValueError`), `active() -> list[Card]`, `restore(card: Card)`, `restore_order(order: list[int])`
- `Tools.pin_card(ctx, component, props)`(그 컴포넌트 스키마로 검증), `Tools.unpin_card(ctx, id)`, `Tools.reorder_cards(ctx, ids)`: 활동 `card_pinned`, `card_unpinned`, `cards_reordered`(`actor=secretary`, low, 대상 `card:<id>`, 순서는 `cards:order`). `/actions`의 `pin_card`, `unpin_card`, `reorder_cards`(`actor=user`)도 같은 메서드. `register_undo` 셋.
- `APP_ONLY_TOOLS = ["ui_todo_list", "ui_choice", "ui_summary_card", "pin_card", "unpin_card", "reorder_cards"]`, `tool_names_for("app") == TOOL_NAMES + APP_ONLY_TOOLS`, `tool_names_for("telegram") == TOOL_NAMES`.
- 하네스 조각(`AppReplySender`): `out.draft_task_ids` → `tool-input-available {toolCallId: "h_draft_<n>", toolName: "ui_todo_draft", input: {"task_ids"}}` + `tool-output-available {output: {"ok": true}}`, `out.ask_condition_for` → `h_cond_<n>`의 `ui_condition_picker`. `n`은 그 답의 순번.
- `/today`의 `cards`: `CardsRepo.active()`를 `sort_order` 순으로, `props.task_ids`가 있으면 `data.todos`에 지금 `todo_dict`(초안·삭제된 것은 빼고).
- `channel_app.md`: 화면 도구는 보기 좋을 때만 쓰고 글로도 같은 뜻을 말한다, 카드 고정은 사용자가 원할 때만(한 단락).

**Slices**
- [ ] `test_ui_tools_do_not_touch_db_or_files` (`tests/test_ui_tools.py`): 호출 전후 DB 파일 해시와 `data/` 아래 파일 목록·해시가 같다
- [ ] `test_ui_schema_error_is_tool_error_and_no_component_chunk`: `ui_choice` 선택지 5개 → `tool-output-error`
- [ ] `test_ui_and_card_tools_absent_from_telegram`: `ClaudeBrain`이 텔레그램 대화에서 만든 서버의 도구 이름에 여섯 개가 없다
- [ ] `test_app_prompt_includes_channel_app_only_for_app`
- [ ] `test_harness_chunks_have_h_prefix`: FakeBrain이 앱 대화에서 `propose_tasks` → `h_draft_1` 조각
- [ ] `test_pin_card_validates_against_its_own_component` (`tests/test_cards.py`): `ui_choice`에 맞는 props로 `ui_todo_list`를 고정 → 오류
- [ ] `test_card_activity_actor_secretary_and_undo_each`
- [ ] `test_reorder_requires_all_pinned_ids`
- [ ] `test_today_cards_filled_with_current_task_data`: 고정 뒤 할 일을 완료하면 다음 `/today`의 `data.todos[0].status == "done"`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_pin_card_from_app_chat`: `POST /chat` → FakeBrain(앱) `ui_todo_list` + `pin_card` → 스트림에 `toolName == "ui_todo_list"` 조각, `GET /today` `cards[0].component == "ui_todo_list"`와 `data` → `GET /activity`의 `card_pinned` 되돌리기 → `cards == []`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: app-only UI component tools and pinned cards`

---

### 티켓 13: 회차 차례의 확인 (10.1)

**목표:** 회차를 실행하는 두뇌 호출(A1)에서 비서가 스스로 꺼낸 `drop_task`, `set_priorities`, 일정 시각을 바꾸는 `update_task`, 시각이 있는 할 일의 `move_task`는 아무것도 바꾸지 않고 확인 토큰을 만든다(A2). 사용자에게는 앱 `ui_confirm` 조각과 텔레그램 `k:` 버튼이 간다(A5). 사용자 메시지에 답하는 차례는 SP1 그대로 바로 적용한다(A3).
**막는 티켓:** 12
**라벨:** `ready-for-agent`

**Files:**
- Modify: `domain.py`, `tools/core.py`, `tools/actions.py`, `harness/dispatcher.py`, `harness/stream.py`, `harness/checkins.py`, `bot/telegram_io.py`, `bot/callbacks.py`, `harness/prompts/system.md`
- Test: `tests/test_run_turn_confirm.py`

**Interfaces**
- Consumes: `ConfirmsRepo`, `apply_action`의 토큰 경로, `UiMessageWriter`, `reply_window_end`, `checkin_cards` (04, 06, 12)
- Produces:
- `RunContext.run_turn -> bool`(속성): `run_id is not None and inbound_id is None`(A1)
- `Tools(..., confirms: ConfirmsRepo | None = None, reply_until: Callable[[int], datetime] | None = None)`. 위 네 경우에 `ctx.run_turn`이면 `_request_confirm(ctx, action: str, args: dict, summary: str) -> dict`: `ConfirmsRepo.create(origin="run_turn", run_id=ctx.run_id, conversation_id=ctx.conversation_id, expires_at=reply_until(run_id))`, ToolEvent `confirm_requested`(data: `token`, `summary`, `action`, `args`), 활동 `confirm_requested`(바뀐 것 없음), 결과 `{"status": "needs_confirm", "confirm_token", "summary"}`. `add_task`는 언제나 바로(A4).
- `Outbound.confirms: list[tuple[str, str]]`(token, summary)
- `bot/telegram_io.py confirm_keyboard(confirms) -> rows`: 줄마다 `✓ 확인: {summary 16자}`(`k:a:<token>`), `✗ 그대로 두기`(`k:x:<token>`). `message_keyboard` 줄 순서: 초안 줄들 → 확인 줄 → 컨디션 줄.
- `bot/callbacks.py`: `k:a` → `apply_action(ActionRequest(action=<토큰의 action>, args=<토큰의 args>, confirm_token=token, actor="user", channel="telegram"))`, `k:x` → `decline_confirm`. 쓰임·만료·`stale` → "이미 정리된 제안이에요."
- 앱: `AppReplySender`가 `confirm_requested`마다 `h_confirm_<n>`의 `ui_confirm {summary, confirm_token, action, args}`. `checkin_cards`도 그 회차의 열린 토큰마다 같은 카드를 더한다.
- `system.md` 원칙 12: "확인이 필요한 변경은 제안으로 말하고, 적용했다고 말하지 않는다"(A7).

**Slices** (`tests/test_run_turn_confirm.py`, 스펙 16장 표의 행)
- [ ] `test_run_turn_detection_both_channels`: 회차 첫 호출 = 확인, 회차 대화에 사용자가 답한 차례 = 바로(A3)
- [ ] `test_run_turn_tools_need_confirm` (매개변수: `drop_task`, `set_priorities` 주기 다섯, `scheduled_at` 바꾸는 `update_task`, 시각 있는 할 일 `move_task`): 데이터 그대로, `pending_confirms` 행, 두뇌가 받은 결과가 `needs_confirm`
- [ ] `test_move_task_without_schedule_applies_in_run_turn`, `test_add_task_applies_in_run_turn`
- [ ] `test_sp1_user_turn_behavior_unchanged`: SP1의 해당 시험 파일이 그대로 통과(`python -m pytest tests/test_tools_tasks.py tests/test_dispatcher_tools.py -q` → `0 failed`)
- [ ] `test_confirm_card_and_telegram_buttons`: 텔레그램 키보드에 `k:a:ct_…`·`k:x:ct_…`(64바이트 이하), 앱 스트림에 `h_confirm_1`
- [ ] `test_confirm_applies_with_activity_and_decline_changes_nothing`
- [ ] `test_double_press_expired_or_stale_not_applied`: 답장 창 끝 뒤 → "이미 정리된 제안이에요."
- [ ] `test_token_survives_restart`: 새 `BeEnv`(같은 루트)에서 같은 토큰으로 적용

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_morning_brief_proposal_needs_confirm`: 10:00 tick, FakeBrain(회차)이 `set_priorities(day, …)` → 우선순위 그대로, `GET /checkins/{id}`의 `cards`에 `ui_confirm` → 그 `action`, `args`, `confirm_token`으로 `POST /actions` → 우선순위 바뀜, 활동 `actor == "user"`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: confirmation for secretary-initiated changes in run turns`

---

### 티켓 14: 회고 단계 — 월말 사다리, 분기 영역 점수, 연말

**목표:** `review(week)` 회차가 그 달 마지막 일요일이면 사다리 점수, 분기 마지막 달이면 영역 점수, 12월이면 올해 돌아보기를 차례로 묻는다(스펙 11.1~11.2). 새 회차 종류는 만들지 않는다. 한 메시지에 질문 하나, 한 메시지에 키보드 한 종류.
**막는 티켓:** 11, 07
**라벨:** `ready-for-agent`

**Files:**
- Create: `harness/review_steps.py`, `harness/prompts/review_month.md`, `review_quarter.md`, `review_year.md`
- Modify: `harness/dispatcher.py`(프롬프트 선택, 사다리 1단계 키보드), `bot/telegram_io.py`, `bot/callbacks.py`, `store/reviews.py`, `harness/checkins.py`(사다리·영역 카드, `run_answered_by`), `tools/core.py`(`review_date_for` 조립), `app.py`
- Test: `tests/test_review_steps.py`, `tests/test_telegram_ladder.py`

**Interfaces**
- Consumes: `record_ladder_score`, `record_area_scores`, `get_curve`, `CurveRepo.next_open_question`, `save_weekly_review`, `mark_answered`, `apply_action` (09, 11, 07)
- Produces:
- `@dataclass(frozen=True) ReviewSteps(month: bool, quarter: bool, year: bool)`, `review_steps(d: date) -> ReviewSteps`: `d`가 그 달 마지막 일요일이면 `month`, 그리고 3·6·9·12월이면 `quarter`, 12월이면 `year`. 판정 날짜는 회고 회차 `scheduled_for`의 논리적 날짜(넘겨 받은 회고도 원래 날짜).
- 프롬프트 선택: `review_week.md` 뒤에 해당하는 `review_month.md` → `review_quarter.md` → `review_year.md`를 잇고, 월말이면서 분기·연말이 아니면 열린 시드 질문 하나(`curve_questions` → `asked`)를 `## 이번에 물을 질문`으로 붙인다(분기·연말이면 마지막 단계 뒤).
- 사다리 키보드 `ladder_keyboard(period: str, field: Literal["n", "f"]) -> list[list[InlineKeyboardButton]]`: `0`~`5`, `6`~`10` 두 줄, `f`면 셋째 줄 `건너뛰기`. 콜백 `l:<YYYY-MM>:n:<0-10>`, `l:<YYYY-MM>:f:<0-10>`, `l:<YYYY-MM>:f:skip`. 달은 회고 회차 날짜가 든 달.
- 1단계 자리(스펙 11.1-1): (a) 그 회고 묶음의 컨디션 버튼을 누르면 콜백이 토스트 대신 **새 메시지**로 "컨디션 {N} 기록했어요.\n\n{사다리 1단계 문구}" + `n` 키보드를 보낸다 (b) 컨디션 버튼 없이 회고 대화에 처음 들어온 사용자 글의 답에는 디스패처가 `Outbound.ladder: tuple[str, Literal["n", "f"]] | None`으로 같은 문구와 키보드를 붙인다 (c) 그 날짜 컨디션이 이미 있어 컨디션 줄이 없으면 회고 메시지에 바로 붙인다. 1단계는 회차마다 한 번(`app_state.ladder_prompted_run_id`). 그 달 사다리가 이미 있으면 묻지 않는다.
- 2·3단계: `l:…:n:<v>` → `apply_action(record_ladder_score(period, now=v))` → 새 메시지 "5년 뒤에는 몇 칸일 것 같아요?" + `f` 키보드. `f:<v>`·`f:skip` → "기록했어요: 지금 {n}, 5년 뒤 {m}"(건너뛰면 "기록했어요: 지금 {n}"), 분기면 이어서 부록 A 영역 점수 문구(지난 분기 점수 줄 포함, 없으면 "지난 분기: 기록 없음"). 이 메시지들은 원문 기록에 회차 대화로 남고 하루 3회에 세지 않는다. 답장 창 뒤의 누름은 기록만 하고 다음 단계를 묻지 않는다.
- `run_answered_by`: `record_ladder_score(period)` → 그 달 월말 회고 회차.
- `save_weekly_review(data_dir, period, text, *, included: list[str] | None = None) -> Path`: 머리글 아래 `포함: 월간(2026-10), 분기(2026-Q4)` 한 줄(있을 때만).
- 앱(실제 통로 `app`): `checkin_cards`가 월말 회고에 `ui_ladder_picker {period, field: "now"}`(그 달 `now`가 있으면 `future`), 분기 회고에 `ui_area_scores {period, previous}`를 더한다.

**Slices**

판정 (`tests/test_review_steps.py`)
- [ ] `test_last_sunday_in_five_sunday_month`: 2026-11-29 → month, 2026-11-22 → 아무것도 아님
- [ ] `test_1227_month_quarter_year_overlap`: 2026-12-27 → 셋 다
- [ ] `test_carried_review_uses_original_date`: 11/29 회고를 R1로 12/1에 넘겨 받아도 `month`, 사다리 달은 `2026-11`
- [ ] `test_prompts_appended_in_order`: 12/27 회고 프롬프트에 세 지시문이 그 순서로, 시드 질문은 하나만
- [ ] `test_review_file_includes_line`

텔레그램 (`tests/test_telegram_ladder.py`)
- [ ] `test_review_message_has_condition_row_not_ladder`
- [ ] `test_condition_press_on_review_sends_ladder_step1_message`
- [ ] `test_first_text_reply_gets_step1_when_no_condition_button`
- [ ] `test_condition_already_recorded_step1_on_review_message`
- [ ] `test_one_keyboard_kind_per_message`: 어떤 메시지에도 컨디션 줄과 사다리 줄이 같이 없다
- [ ] `test_now_then_future_then_recorded_copy`, `test_skip_future_copy`
- [ ] `test_quarter_area_prompt_with_previous_scores`
- [ ] `test_late_button_after_window_records_without_next_step`
- [ ] `test_late_skipped_review_next_review_does_not_ask_twice`: 10월 월말 회고가 `skipped(late)` → 10월 사다리는 비어 있고, 11/29 회고는 11월만 묻는다
- [ ] `test_ladder_button_at_0130_records_button_month` (Review Focus 5): 12/1 01:30(논리적 11/30)에 `l:2026-11:n:6` → `2026-11`
- [ ] `test_ladder_press_marks_review_answered`
- [ ] `test_app_checkin_cards_ladder_and_area`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_month_end_review_ladder`: 시계 2026-11-29 18:00 tick → 회고+저녁 체크인 한 메시지(FakeBrain, 컨디션 줄만) → 컨디션 4 누름 → 1단계 메시지 → `l:2026-11:n:6` → 2단계 → `l:2026-11:f:8` → "기록했어요: 지금 6, 5년 뒤 8" → `GET /curve`의 `ladder`에 `{"period": "2026-11", "now": 6, "future": 8}`, `GET /checkins/{id}`가 `answered`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: monthly ladder, quarterly area scores and year-end review steps`

---

### 티켓 15: 경험치, 레벨, 텔레그램 `/status`, 쓰기 경로 감시

**목표:** 스펙 9.1의 X1~X10이 같은 트랜잭션에서 원장에 쌓이고(오르기만), 레벨이 오르면 확인 문구 끝에 "레벨 {N}이 됐어요."가 붙는다. 텔레그램 `/status`(11.4)와 `GET /status`가 같은 숫자를 보인다. 쓰기 경로 감시와 전체 로그 검사로 BE 쪽을 마무리한다.
**막는 티켓:** 14, 08, 13
**라벨:** `ready-for-agent`

**Files:**
- Modify: `store/repos/status.py`(`grant`), `tools/core.py`, `tools/confirmations.py`, `tools/actions.py`, `tools/mcp_adapter.py`, `harness/dispatcher.py`(`mark_answered`, 레벨 문구), `loop/runner.py`, `bot/commands.py`, `bot/telegram_io.py`, `store/db.py`(감시 이음매)
- Test: `tests/test_status_xp.py`, `tests/test_status_property.py`, `tests/test_status_command.py`, `tests/test_write_paths.py`, `tests/test_api_logging.py`, `tests/test_brain_options.py`

**Interfaces**
- Consumes: `status/xp.py` 상수(03), 모든 변경 도구, `mark_answered`(07), `review_steps`(14), `status_snapshot`(03)
- Produces:
- `StatusRepo.grant(*, at, logical_date: date, source_kind, source_ref, amount, label, area=None) -> bool`: `INSERT … ON CONFLICT DO NOTHING`, 새로 쌓였으면 True. 원장의 UPDATE·DELETE 함수는 만들지 않는다. `count_secretary_on(d: date) -> int`.
- 쌓는 자리(모두 그 변경과 같은 트랜잭션):
  - X1/X2 `Tools.complete_task`: 완료 순간 그 할 일이 든 지금 기간 우선순위 가운데 가장 큰 주기 → `XP_PRIORITY`, 없으면 `XP_TASK`. `source_ref = task:<id>`, 라벨 "할 일 완료"
  - X4 `record_condition`(`date:<날짜>`, "컨디션"), X6 `record_ladder_score`(그 달 처음, `ladder:<YYYY-MM>`, "사다리 점수"), X7 `record_area_scores`(그 분기 처음, `areas:<YYYY-Qn>`, "영역 점수")
  - X3/X5/X8 `Dispatcher.mark_answered`: 주간 회고가 든 묶음이면 X5 하나(`run:<회고 id>`, "주간 회고"), 아니면 X3(`run:<id>`, "체크인 답"). 12월 마지막 일요일 회고 대화의 답이면 X8(`year:<YYYY>`, "연말 회고")도.
  - X9 하루 한 번 `apply_action(grant_rest_days)`: `app_state.last_rest_day_checked` 다음 날부터 어제까지, 최대 14일, `installed_at`의 논리적 날짜 이후, 그날 완료한 할 일(논리적 날짜 기준)이 없으면 `date:<날짜>` 5, 라벨 "쉬는 날". 활동 `rest_days_granted`(`secretary`/`scheduler`, 쌓인 날이 있을 때만)
  - X10 `Tools.grant_xp(ctx, amount, reason) -> dict`: `amount ∈ {5, 10}`, `reason` 1~60자, 하루 3회(`secretary:<날짜>:<n>`), 넘으면 오류. 라벨 "비서가 준 경험치", 활동 `xp_granted_by_secretary`. `TOOL_NAMES`에 더해 텔레그램 22, 앱 28.
- 레벨 문구: `level_up_line(before: int, after: int) -> str`("레벨 {after}이 됐어요." 또는 `""`). 텔레그램 답의 확인 문구 끝, `/chat`의 `h-confirm` 블록 끝, `/actions`의 `xp: {"gained": n, "level_up": N | null}`와 `confirmation` 끝.
- `bot/commands.py`: `status_text(snapshot: dict) -> str`(11.4 형식 그대로, 영역 점수가 없으면 "영역 점수는 분기 마지막 주 회고에서 함께 정해요.", 칭호는 첫 하나 + "외 {n}개"), `COMMANDS`에 `/status`, `HELP_TEXT`에 `/status  레벨, 스탯, 퀘스트` 줄. `run_command`가 처리하므로 앱 `/status`도 같다.
- `store/db.py open_db(path, *, on_write: Callable[[str], None] | None = None)`: `set_trace_callback`으로 `INSERT`·`UPDATE`·`DELETE` 문만 넘긴다(시험 이음매. 앱은 넘기지 않는다).

**Slices**

경험치 (`tests/test_status_xp.py`)
- [ ] `test_xp_table_x1_to_x10` (매개변수 10행): 금액과 `source_kind`/`source_ref`가 9.1 표 그대로
- [ ] `test_x2_biggest_cadence_at_completion`: 이번 주·이번 분기 우선순위 → 100
- [ ] `test_recomplete_after_undo_does_not_double`(U6)
- [ ] `test_x5_once_for_bundle_and_x8_on_1227`
- [ ] `test_rest_days_rules`: 멈춤 기간과 노트북이 꺼진 날도 쉬는 날, 30일 꺼짐 → 14일치만, `installed_at` 전은 없음
- [ ] `test_task_done_at_0130_counts_previous_day_so_no_rest_day` (Review Focus 5)
- [ ] `test_grant_xp_amounts_reason_and_daily_cap`
- [ ] `test_level_up_line_once`: 140 → 150을 넘는 완료 → "레벨 2가 됐어요."가 한 번만(텔레그램 답, `/actions`의 `xp.level_up == 2`)
- [ ] `test_ledger_has_no_update_delete_functions`: `StatusRepo`에 `grant` 말고 원장을 바꾸는 공개 메서드가 없다(`inspect`로 이름 확인)

속성 (`tests/test_status_property.py`, `hypothesis`)
- [ ] `test_xp_and_level_never_decrease`: 무작위 순서의 `complete_task`, `reopen_task`, 되돌리기, 회차 답(`mark_answered`), `record_condition`, 하루 넘기기(`grant_rest_days`) 뒤 매 단계 `total()`과 `level_for(total())`가 줄지 않는다(완료 조건 8). `max_examples=200`

`/status` (`tests/test_status_command.py`)
- [ ] `test_status_text_format`: 스펙 11.4 예시 고정 자료로 글이 그 블록과 같다
- [ ] `test_status_command_and_api_same_numbers`: 같은 시각 텔레그램 `/status` 글의 레벨·경험치·스탯 숫자 == `GET /status`
- [ ] `test_status_empty_stats_copy`, `test_help_lists_status`

마무리 감시
- [ ] `test_tool_counts_22_and_28` (`tests/test_brain_options.py`, S12): `len(tool_names_for("telegram")) == 22`, `len(tool_names_for("app")) == 28`, 모두 `build_options`의 허용 패턴 `mcp__planner__*` 안
- [ ] `test_each_table_written_only_by_its_path` (`tests/test_write_paths.py`): `on_write`로 받은 문마다 표 이름과 호출한 모듈(`inspect.stack()`의 첫 `my_planner` 프레임)을 모은 뒤, 스펙 4.3 표의 허용 모듈 집합(`tools.*`·`tools/activity.py` / `harness.dispatcher`(`mark_answered`, `apply_action`) / `harness.delivery` / `api.chat`(`inbound_pending` 저장, `route_app_message`는 디스패처) / `loop.*`·`harness.dispatcher`(운영 상태))에 드는지 본다. 시나리오: 01~14의 수용 시험 흐름 하나씩. `api.read`에서 나온 쓰기는 0
- [ ] `test_full_scenario_logs_have_no_secrets` (`tests/test_api_logging.py`): 시험 토큰, 시험 문장("비밀 문장 7f3a"), 할 일 제목, 도구 인자 값, 푸시 endpoint를 쓰는 전체 흐름(텔레그램, `/chat`, `/actions`, 푸시) 뒤 로그 파일에 그 문자열이 하나도 없다

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_week_of_xp`: FakeClock으로 7일을 돌린다(하루 할 일 3 완료 FakeBrain, 저녁 체크인 답, 컨디션 버튼, 일요일 회고). `GET /status`의 `xp_total`이 원장 합과 같고 9.1의 한 주 예상(≈350)과 같은 계산, 쉬는 날이 하루 있으면 그날 `+5 쉬는 날`이 `recent_xp`에, 텔레그램 `/status`와 숫자가 같다. → `passed`
- [ ] BE 전체: `python -m pytest -q` → `0 failed`, 스펙 16장 묶음 명령이 모두 `0 failed`:
  - `python -m pytest tests/test_api_*.py`
  - `python -m pytest tests/test_dispatcher_channels.py tests/test_delivery.py`
  - `python -m pytest tests/test_curve_*.py tests/test_status_*.py tests/test_seed_life.py`

**마무리**
- [ ] **Review + Commit** `feat(status): XP ledger rules, level-ups, /status and write-path audit`

---

### 티켓 16: 대시보드 뼈대와 (a) 비서 상태 화면

**목표:** `web/dashboard/`에 정적 내보내기 대시보드를 만든다. 처음 열면 설정 화면에서 BE URL과 토큰을 넣고, 모든 화면 위의 연결 띠가 켜짐·꺼짐(10초)·마지막 응답을 보인다. 첫 화면은 비서 상태(13.2). 디자인 토큰은 두 스킬로 정한다.
**막는 티켓:** 03
**라벨:** `ready-for-agent`

**Files:**
- Create: `web/dashboard/package.json`, `package-lock.json`, `next.config.mjs`, `tsconfig.json`, `vercel.json`, `vitest.config.ts`, `scripts/check-csp.mjs`, `scripts/gen-types.mjs`, `src/pages/_app.tsx`, `_document.tsx`, `index.tsx`, `settings.tsx`, `src/lib/{connection,api,time,polling,labels}.ts`, `src/components/{ConnectionBand,StateNotice,Nav}.tsx`, `src/screens/HealthScreen.tsx`, `src/styles/{tokens,globals}.css`, `src/api/{schema.json,types.gen.ts}`, `src/test/{server,handlers}.ts`, `src/test/fixtures/health*.json`
- Create (BE): `tests/test_dashboard_fixtures.py`
- Test: `src/lib/*.test.ts`, `src/components/*.test.tsx`, `src/screens/HealthScreen.test.tsx`, `src/banned-words.test.ts`

**Interfaces**
- Consumes: `GET /health` 계약, `python -m my_planner schema`(02), `BeEnv`(01)
- Produces (TypeScript):
- `next.config.mjs`: `output: "export"`, `trailingSlash: true`, `images: { unoptimized: true }`, `reactStrictMode: true`. Pages Router만(`src/app/` 없음). API 라우트·`getServerSideProps` 없음.
- `src/lib/connection.ts`
  - `type Connection = { beUrl: string; token: string }`
  - `normalizeBeUrl(input: string, allowedPattern: string): { ok: true; url: string } | { ok: false; reason: "not_https" | "out_of_range" | "invalid" }`: 공백 제거, 끝 `/`와 `/api/v1` 제거, `https://`만, 호스트가 `NEXT_PUBLIC_CONNECT_SRC`(예: `https://*.tail1234.ts.net`)에 맞아야 한다
  - `loadConnection(): Connection | null`, `saveConnection(c: Connection): void`(`localStorage["mp.connection"]`), `loadLastHealthOk(): { receivedAt: string; lastTickAt: string | null } | null`, `saveLastHealthOk(v)`(`localStorage["mp.lastHealthOk"]`). 읽기·쓰기는 모두 `try/catch`, 막혀 있으면 null/무시
- `src/lib/api.ts`
  - `type ApiResult<T> = { kind: "ok"; data: T } | { kind: "offline" } | { kind: "unauthorized" } | { kind: "rate_limited" } | { kind: "safe_mode" } | { kind: "broken"; code: string }`
  - `fetchApi<T>(conn: Connection, path: string, isT: (x: unknown) => x is T, opts?: { timeoutMs?: number }): Promise<ApiResult<T>>`: `Authorization: Bearer`, 10초 `AbortController`, 네트워크 오류·시간 초과 → offline, 401 → unauthorized, 429 → rate_limited, 503 `safe_mode` → safe_mode, 그 밖 `5xx` → broken(`error.code`), 모양이 틀리면 broken(`"shape"`)
  - `isHealth`, … 응답 모양 검사기(`types.gen.ts`의 타입을 좁히는 손 검사기, 필수 필드만)
- `src/lib/polling.ts`: `usePolling<T>(load: () => Promise<ApiResult<T>>, intervalMs = 60_000): { result: ApiResult<T> | null; refresh: () => void }`: 열 때 한 번, 보이는 탭일 때만 60초마다, `visibilitychange`로 다시 보이면 바로 한 번, `unauthorized`면 멈추고 설정이 바뀔 때까지 다시 부르지 않는다
- `src/lib/time.ts`: `formatKst(iso: string, style: "M/D HH:mm" | "HH:mm" | "HH:mm:ss" | "M/D") : string`(`Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hourCycle: "h23" })`)
- `src/lib/labels.ts`: 회차 이름(아침 브리핑, 저녁 체크인, 주간 회고, 다시 이어서), 상태(`done` 보냄, `pending`/`queued` 예정, `running` 보내는 중, `failed` 전송 안 됨, `skipped` `건너뜀({사유})`), 사유 표시(이 계획이 정함: `late` 시간 지남, `merged_into_return` 복귀 인사에 합침, `paused` 멈춤, `auth` 로그인 필요, `rate_limit` 사용 한도, `daily_cap` 하루 상한), 답할 회차(답함, 답 기다림, 지나감)
- `src/components/ConnectionBand.tsx`: `/health`를 공유 폴링한다. 성공하면 `saveLastHealthOk`, 문구 `● BE 켜짐 · {HH:mm:ss} 응답`과 `[연결 확인]` 버튼, offline이면 `BE 꺼짐 · 마지막 응답 {M/D HH:mm}` 또는 `BE 꺼짐 · 마지막 응답 기록 없음`
- `src/components/StateNotice.tsx`: 스펙 13.1 공통 상태 표의 문구 그대로(설정 없음 → `/settings`로 이동)
- `src/screens/HealthScreen.tsx`: 13.2 배치, 빈 상태 문구("오늘 예정된 회차가 아직 없어요.", "최근 24시간 경고 없음")
- `_document.tsx`: `<meta httpEquiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ${NEXT_PUBLIC_CONNECT_SRC}; base-uri 'none'; form-action 'none'">`. `vercel.json`: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: frame-ancestors 'none'`, `Permissions-Policy` 최소.
- 차트·리스트 컴포넌트는 `next/dynamic(..., { ssr: false })`로 브라우저에서만 그린다(정적 HTML에 인라인 `style` 속성이 남지 않게).
- `scripts/check-csp.mjs`: `out/**/*.html`에서 `src` 없는 `<script>`(단 `type="application/json"` 빼고), `<style>` 요소, `style=` 속성을 세어 하나라도 있으면 실패. 출력 `CSP OK: 0 inline scripts, 0 inline styles`.
- `scripts/gen-types.mjs`: `src/api/schema.json` → `src/api/types.gen.ts`(`json-schema-to-typescript`).
- `package.json` 스크립트: `dev`, `build`(`next build`), `test`(`vitest run`), `gen:types`, `check:csp`, `typecheck`(`tsc --noEmit`).
- BE `tests/test_dashboard_fixtures.py`: `BeEnv`(FakeBrain, FakeClock)로 만든 실제 응답을 `web/dashboard/src/test/fixtures/<이름>.json`과 비교한다(`now`, `started_at` 같은 시각은 고정 시계라 같다). `--update-dashboard-fixtures` 옵션이면 다시 쓴다. `src/api/schema.json == schema_bundle()`도 본다.

**디자인 단계** (구현 전에 한 번)
- [ ] UI UX Pro Max 스킬(github `nextlevelbuilder/ui-ux-pro-max-skill`)과 taste 스킬(github `Leonxlnx/taste-skill`)을 이 작업 세션에 불러온다(각 저장소 README의 설치 방법).
- [ ] 두 스킬로 정한다: 밝음·어두움 색 토큰(`prefers-color-scheme`), 글꼴(시스템 글꼴 또는 `public/`에 둔 자체 글꼴, 외부 글꼴 없음), 간격·반경·그림자 단계, 차트 모양(선 두께, 점, 점선, 띠 투명도), 폰 폭(360px)에서의 배치. 결과는 `src/styles/tokens.css` 변수와 머리 주석 다섯 줄 이내로 남긴다.
- [ ] taste 스킬의 점검 항목으로 13.2 시안을 한 번 고친다(같은 크기의 카드 격자, 무의미한 그라데이션, 장식 이모지 같은 AI 티를 뺀다).

**Slices** (`cd web/dashboard && npx vitest run <파일> -t "<이름>"`로 FAIL → PASS)
- [ ] `connection.test.ts` `normalizes and rejects BE URLs` (Review Focus 3): `" https://lap.tail1234.ts.net/api/v1/ "` → `https://lap.tail1234.ts.net`, `http://…` → `not_https`, `https://evil.example.com` → `out_of_range`
- [ ] `connection.test.ts` `blocked localStorage returns null`: `getItem`이 던지면 `loadLastHealthOk() === null`
- [ ] `api.test.ts` (MSW): 401 → `unauthorized`, 429, 503 `safe_mode`, 500 `internal` → `broken("internal")`, 필드 빠진 200 → `broken("shape")`, 응답 없음 10초(가짜 타이머) → `offline`, 네트워크 오류 → `offline`
- [ ] `ConnectionBand.test.tsx`: 켜짐 문구, 꺼짐 + 기록 있음 `BE 꺼짐 · 마지막 응답 10/24 17:00`, 기록 없음, `localStorage` 막힘 → 기록 없음
- [ ] `polling.test.ts`: 숨은 탭이면 부르지 않음, 60초마다 한 번, 401 뒤 멈춤
- [ ] `time.test.ts` `shows KST regardless of device time zone` (Review Focus 1): `process.env.TZ = "UTC"`와 `"America/Los_Angeles"`에서 `formatKst("2026-10-24T08:00:05Z", "HH:mm:ss") === "17:00:05"`
- [ ] `HealthScreen.test.tsx`: 고정 자료 `health.json`으로 13.2의 줄(판·스키마, 폴링, 로그인, 주 통로 "앱 (지금 텔레그램)", 오늘 회차 두 줄, 두뇌 호출 23 / 60, 경고 2), 빈 상태 두 문구, 401·503·모양 오류 문구
- [ ] `settings.test.tsx`: 범위 밖 URL은 저장되지 않고 이유가 보인다, "연결 확인"이 `/health`를 부른다
- [ ] `banned-words.test.ts`: `src/` 아래 문자열에 "놓쳤어요", "밀렸어요", "늦었지만", "실패", "연속"이 없다

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `python -m pytest tests/test_dashboard_fixtures.py -v` → `passed`(BE가 FakeBrain·FakeClock으로 만든 `/health` 응답 == FE 고정 자료)
- [ ] `cd web/dashboard && npm ci && npm test` → `0 failed`
- [ ] `cd web/dashboard && npm run typecheck` → 출력 없음, 코드 0
- [ ] `cd web/dashboard && NEXT_PUBLIC_CONNECT_SRC="https://*.example.ts.net" npm run build` → `out/index.html`, `out/settings/index.html` 생성, `.next/server/pages/api` 없음
- [ ] `cd web/dashboard && npm run check:csp` → `CSP OK: 0 inline scripts, 0 inline styles`

**마무리**
- [ ] **Review + Commit** `feat(dashboard): static dashboard skeleton, connection band and assistant status screen`

---

### 티켓 17: 대시보드 (b) 할 일 + 컨디션, (d) 상태창

**목표:** 13.3(오늘·이번 주 할 일, 아침 브리핑 펼치기, 지난 30일 컨디션 점 차트)과 13.5(레벨, HP, 스탯 막대, 디버프와 회복 퀘스트, 메인·일일 퀘스트, 칭호, 최근 경험치)를 그린다. 읽기 전용이고 체크 상자가 없다.
**막는 티켓:** 16
**라벨:** `ready-for-agent`

**Files:**
- Create: `src/pages/tasks.tsx`, `src/pages/status.tsx`, `src/screens/{TasksScreen,StatusScreen}.tsx`, `src/components/{TodoList,ConditionDots,StatBar,XpBar}.tsx`, `src/test/fixtures/{today,week,conditions,status}*.json`
- Modify: `tests/test_dashboard_fixtures.py`(고정 자료 더함)
- Test: `src/screens/TasksScreen.test.tsx`, `src/screens/StatusScreen.test.tsx`, `src/components/ConditionDots.test.tsx`

**Interfaces**
- Consumes: `fetchApi`, `usePolling`, `formatKst`, `StateNotice`, `ConnectionBand`, 토큰(16), `GET /today`·`/week`·`/conditions`·`/status`(02, 03)
- Produces:
- `TasksScreen`: 탭 `[오늘] [이번 주]`(탭 상태는 메모리). 오늘은 `todos[].group` 순서 그대로 "우선순위 / 일정 / 열린 할 일"(전에 잡은 일은 `(M/D)`), 이번 주는 `days` 7칸(빈 날도 칸). 아침 브리핑은 접힌 상태로 시작. 맨 아래 "바꾸려면 텔레그램이나 운영 앱에서 말씀해 주세요." 빈 상태 "아직 비어 있어요.", 컨디션 없음 "저녁 체크인에서 컨디션을 기록하면 여기에 그려져요."
- `ConditionDots({ items, from, to })`: x는 날짜, y는 1~5, 기록 없는 날은 점도 선도 없음(0으로 그리지 않음), 머리에 `평균 {a} · {n}일 기록`
- `StatusScreen`: `XpBar(level, into, forNext)`, HP `n/5 (오늘 컨디션)` 또는 "기록 없음", `StatBar(area, score, prev, debuff, quest)`(디버프면 `↓ 디버프 (Q3 6)`와 `└ 회복 퀘스트: … (15~30분)`), 메인·일일 퀘스트, 칭호, 최근 경험치 `+10 할 일 완료 · …`. 빈 상태 문구 13.5 그대로, 안내 "텔레그램이나 운영 앱에서 '그 퀘스트 할게'라고 말씀해 주세요."
- 연속 기록, 남은 시간, 놓친 것 수 표시 없음(ADR 0006).

**Slices**
- [ ] `TasksScreen.test.tsx` `today order equals API groups`: 고정 자료의 제목 순서 그대로, 체크 상자 없음(`role="checkbox"` 0개)
- [ ] `TasksScreen.test.tsx` `week shows 7 day cells including empty`
- [ ] `TasksScreen.test.tsx` `empty, offline, 401, 503, shape states`
- [ ] `ConditionDots.test.tsx` `gaps are not zero`: 기록 21일 → 점 21개, 빈 날의 y=0 점 없음
- [ ] `StatusScreen.test.tsx` `renders snapshot`: `Lv. 6`, `130 / 400 XP`, `HP 4/5`, 건강 `↓ 디버프 (Q3 6)`과 회복 퀘스트
- [ ] `StatusScreen.test.tsx` `empty states` (영역 점수 없음, 메인 퀘스트 없음, 칭호 없음, 경험치 0)
- [ ] `StatusScreen.test.tsx` `no streak or countdown words`: 화면 글에 "연속", "남은", "놓친"이 없다

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `python -m pytest tests/test_dashboard_fixtures.py -v` → `passed`(`/today`, `/week`, `/conditions`, `/status` 고정 자료가 `BeEnv` 응답과 같다. 시나리오는 티켓 15 수용 시험의 7일)
- [ ] `cd web/dashboard && npm test && npm run build && npm run check:csp` → `0 failed`, `CSP OK: 0 inline scripts, 0 inline styles`

**마무리**
- [ ] **Review + Commit** `feat(dashboard): tasks and conditions screen, status window screen`

---

### 티켓 18: 대시보드 (c) 인생곡선

**목표:** 13.4: 확대 `[일] [주] [월] [분기] [년]`, 챕터 띠, 사다리(지금 실선, 5년 뒤 점선), 컨디션(0~10로 옮긴 옅은 점), 사건(▲ 고점, ▼ 저점, ◆ 전환점, 누르면 날짜·종류·제목·메모), 영역 레이더(최근 분기 실선, 앞 분기 점선, 내려간 꼭짓점 ↓), 안심 보기 문구(8.3).
**막는 티켓:** 16
**라벨:** `ready-for-agent`

**Files:**
- Create: `src/pages/curve.tsx`, `src/screens/CurveScreen.tsx`, `src/components/{CurveChart,AreaRadar,Reassurance,MilestonePopover}.tsx`, `src/lib/curveLayout.ts`, `src/test/fixtures/curve*.json`
- Modify: `tests/test_dashboard_fixtures.py`
- Test: `src/lib/curveLayout.test.ts`, `src/screens/CurveScreen.test.tsx`

**Interfaces**
- Consumes: `fetchApi`, `usePolling`, `StateNotice`(16), `GET /curve`(03)
- Produces:
- `src/lib/curveLayout.ts`(순수 함수)
  - `ladderSeries(ladder: Ladder[], from: string, to: string): { x: number; now: number | null; future: number | null }[]`: 달마다 15일 정오(KST)에 점, 기록 없는 달은 `null`(선이 끊긴다)
  - `milestoneX(date: string, precision: "year" | "month" | "day"): number`(그 기간의 가운데)
  - `conditionSeries(condition: Bucket[]): { x: number; y: number }[]`(`y = (average − 1) × 2.5`, 묶음 가운데)
  - `chapterBands(chapters, from, to): { x1: number; x2: number; title: string }[]`(끝이 null이면 `to`까지)
  - `reassuranceCopy(gap: number | null): string`: 8.3 표 그대로(`≥ +1.0`, `≤ −1.0`, 그 사이, null)
- `CurveScreen`: 확대 버튼을 누르면 `GET /curve?zoom=<z>`(기본 범위). "민감한 사건 보기"는 켜면 `include_sensitive=true`로 다시 부르고 그 화면의 메모리에만 둔다(`localStorage`에 쓰지 않는다). 빈 상태 문구 13.4 그대로 넷.
- 차트는 Recharts `ComposedChart`(`ReferenceArea` 띠, `Line` 둘, `Scatter`), `RadarChart` 둘 겹침. `ssr: false`로 불러온다.

**Slices**
- [ ] `curveLayout.test.ts` `ladder breaks on missing month`: 8월·10월만 있으면 9월이 `null`
- [ ] `curveLayout.test.ts` `ladder point on the 15th`
- [ ] `curveLayout.test.ts` `reassurance copy thresholds`: 1.0, 0.99, −1.0, null
- [ ] `CurveScreen.test.tsx` `zoom buttons request each zoom`: 다섯 번 누르면 MSW가 받은 `zoom`이 `day, week, month, quarter, year`
- [ ] `CurveScreen.test.tsx` `sensitive toggle refetches and is not persisted`: 켠 뒤 요청에 `include_sensitive=true`, `localStorage.setItem` 호출 없음, 화면을 다시 열면 꺼짐
- [ ] `CurveScreen.test.tsx` `milestone tap shows details`, `radar marks down vertex`
- [ ] `CurveScreen.test.tsx` `four empty states`
- [ ] `CurveScreen.test.tsx` `offline and 401 states`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `python -m pytest tests/test_dashboard_fixtures.py -v` → `passed`(`/curve` 다섯 확대 단위 고정 자료를 `BeEnv`가 만든다: 시드 고정 자료 가져오기(10) + 티켓 14 수용 시험의 사다리 + 컨디션 30일)
- [ ] `cd web/dashboard && npm test && npm run build && npm run check:csp` → `0 failed`, `CSP OK: 0 inline scripts, 0 inline styles`

**마무리**
- [ ] **Review + Commit** `feat(dashboard): life curve screen with zoom, radar and reassurance view`

---

### 티켓 19: Vercel 배포, Tailscale serve, 운영 안내

**목표:** 대시보드를 Vercel에 올리고, 노트북 BE를 `tailscale serve`로 tailnet에 열고, 폰과 노트북 브라우저에서 연결한다. README에 운영 안내를 쓴다.
**막는 티켓:** 15, 17, 18
**라벨:** `needs-laptop`(Vercel 계정, tailnet 관리 화면, 노트북 `.env`)

**Files:** Modify `README.md`, `config.toml`(`cors_origins`, `cors_origin_regex`), 노트북 `.env`(커밋하지 않음)

- [ ] tailnet 관리 화면: MagicDNS, HTTPS 인증서 켜기
- [ ] 노트북: `python -m my_planner gen-token` → `.env`의 `API_TOKEN`. `python -m my_planner gen-vapid` → `.env`의 `VAPID_*`, `VAPID_SUBJECT=mailto:…`
- [ ] Vercel 프로젝트: 루트 디렉터리 `web/dashboard`, 빌드 `npm run build`, 출력 `out`, 환경 변수는 `NEXT_PUBLIC_CONNECT_SRC=https://*.<tailnet>.ts.net` 하나뿐(토큰과 BE URL은 넣지 않는다). Vercel 분석 끔.
- [ ] `config.toml`: `cors_origins = ["https://<대시보드>.vercel.app", "https://<운영 앱>.vercel.app"]`, 미리보기는 팀 범위 정규식만. 다시 시작.
- [ ] `tailscale serve --bg --https=443 http://127.0.0.1:8787` → `tailscale serve status`에 `https://<노트북>.<tailnet>.ts.net (tailnet only)` → `http://127.0.0.1:8787`. Funnel은 켜지 않는다(`tailscale funnel status` → 꺼짐).
- [ ] 확인(폰 셀룰러 + Tailscale, PowerShell은 노트북):
  - `curl.exe -s -H "Authorization: Bearer $env:API_TOKEN" https://<노트북>.<tailnet>.ts.net/api/v1/health` → `"status":"ok"`
  - 토큰 없이 → `401`
  - `curl.exe -si -H "Origin: https://evil.vercel.app" -H "Authorization: Bearer …" …/health` → `Access-Control-Allow-Origin` 없음
  - 폰에서 대시보드 → 설정에 BE URL과 토큰 → 연결 띠 "BE 켜짐", 화면 넷. Chrome 권한 창이 뜨면 S9에서 정한 안내대로 허용
- [ ] README "API와 대시보드" 절: 위 명령, Funnel 금지, 토큰 바꾸기(`.env` 고침 → BE 다시 시작 → 기기마다 다시 넣기), 시드 가져오기 순서 4단계(스펙 12장), PNA 권한 창 안내(S9)
- [ ] **수용 확인**: 위 네 확인의 출력이 기대와 같다. `git status`에 `.env`, `data/`가 없다.
- [ ] **Commit** `docs: deployment and operations guide for API and dashboard`

---

### 티켓 20: 노트북 수용 테스트

**목표:** 스펙 1장 완료 조건 1, 2, 5, 9, 10을 노트북·폰·Tailscale로 확인하고 `docs/acceptance/sp3-4-checklist.md`에 남긴다. 5는 11/29 첫 월말 회고와 12/27 분기·연말 회고에서 확인한다.
**막는 티켓:** 19
**라벨:** `needs-laptop`

- [ ] `docs/acceptance/sp3-4-checklist.md`를 만든다: 스펙 16장 "수동 수용 테스트" 표의 단계와 기대 결과 그대로 + 아래, 단계마다 날짜와 결과 칸.
  - 완료 조건 1: 대시보드 화면 넷의 할 일·레벨·경험치·스탯이 같은 시각 텔레그램 `/today`, `/week`, `/status`와 같다
  - 완료 조건 2: 덮개를 닫으면 10초 안에 "BE 꺼짐 · 마지막 응답 {시각}", 사생활 보호 창에서는 "마지막 응답 기록 없음"
  - 완료 조건 5: 11/29 회고에서 사다리 두 단계 → `curve_ladder_scores`에 `2026-11`. 12/27 회고에서 영역 점수 → `curve_area_scores` `2026-Q4`, 내려간 영역이 상태창에 디버프와 회복 퀘스트 하나
  - 완료 조건 9: 운영 앱의 `/chat` 스트림을 운영 앱 스레드의 기준 응답과 같은 파서로 읽음, `/actions` → `undo_id` → `/activity/{id}/undo`가 한 번 되돌림
  - 완료 조건 10: 운영 앱 구독 뒤 아침 브리핑이 푸시로만 오고 `proactive.sent_today` +1, 구독을 지우면 다음 회차가 텔레그램으로
  - `state/logs/`에서 토큰과 보낸 문장을 찾으면 없다
  - 시드를 가져온 뒤 노트북 밖 시드 사본을 지웠다(체크)
  - 확인 SQL: `SELECT run_id, channel, mode, status, push_ok, push_failed FROM run_deliveries ORDER BY run_id DESC LIMIT 10`, `SELECT source_kind, count(*), sum(amount) FROM status_xp_ledger GROUP BY 1`
- [ ] 날마다 체크하고, 발견한 문제는 새 이슈로 남긴다.
- [ ] **Commit** `docs: SP3-4 acceptance results`

---

## 스펙 빈 곳과 이 계획의 결정

| # | 스펙 자리 | 빈 곳 | 이 계획의 결정 (티켓) |
|---|---|---|---|
| 1 | 7.4 vs 1장 조건 11 | 모든 머리글에 `@telegram`/`@app`을 붙이면 SP1 시험(`"### 01:00 사용자 [1]\n\n…"`)이 깨진다 | 앱 머리글에만 ` @app`, 텔레그램은 SP1 그대로, 표시 없는 머리글은 `telegram`으로 읽는다 (02) |
| 2 | 6.4.1 `start` 조각, `x-conversation-id` | 대화 id가 첫 조각과 응답 헤더에 필요한데, 두뇌 갈래는 큐에서 꺼낼 때 대화를 고른다 | 받을 때 동기 `Dispatcher.route_app_message`가 7.2로 고른다(쓰기는 디스패처 안) (06) |
| 3 | 14장 CSP, 13.1 Next.js | App Router 정적 HTML은 인라인 스크립트가 있어 `script-src 'self'`와 맞지 않는다. `vercel.json`은 빌드 상수를 읽지 못한다. `default-src 'self'`는 인라인 스타일도 막는다 | Pages Router, CSP는 `_document`의 `<meta>`(빌드 상수), `vercel.json`은 고정 헤더, `style-src 'self'`와 `check-csp` (16) |
| 4 | 6.1, 15장 | `API_TOKEN`이 없거나 짧을 때 동작이 없다 | API를 열지 않고 `api_token_missing` 경고, 텔레그램과 루프는 계속 (01) |
| 5 | 12장 | 읽을 수 없거나 JSON이 아닌 시드 파일의 종료 코드, BOM, 틀린 항목이 없다 | 코드 6, `utf-8-sig`, 틀린 항목은 `invalid` 개수만 (10) |
| 6 | 6.4.5 `cards` | 텔레그램 버튼 재료(`draft_task_ids`, `ask_condition_for`)가 저장되지 않는다 | `tool_events_log.run_id`와 `ask_condition_for` 규칙으로 다시 만든다. 이미 기록한 컨디션은 카드에서 뺀다 (02) |
| 7 | 6.4.7 카탈로그 | 앱에 사건·챕터 초안 카드 컴포넌트가 없다 | v1은 앱에서 자연어나 `/actions confirm_milestones`로 확정. 운영 앱 스레드에 알린다 (11) |
| 8 | 부록 A | 영역 점수 기록, 챕터 확정, 도구로 기록한 사다리의 확인 문구가 없다 | 티켓 09에 적은 문구 |
| 9 | 1장 조건 9, 16장 | 운영 앱 스레드의 기준 SSE 응답(golden)이 아직 없다 | `tests/ui_stream.py`로 스펙 예시를 읽고, 받으면 `tests/fixtures/app_golden/`에 더한다 (06, 20) |
| 10 | 13.1 "건너뜀({사유})" | 사유의 화면 문구가 없다 | 티켓 16 `labels.ts`의 표 |
| 11 | 7.5 M4 `senders: dict` | 생성자를 바꾸면 SP1 시험의 `Dispatcher(sender=…)`가 깨진다 | `sender`(텔레그램)를 두고 `app_sender`를 더한다 (06) |
| 12 | 11.1-1 "컨디션 답 아래" | SP1의 컨디션 버튼 답은 메시지가 아니라 콜백 토스트(`query.answer`)라 아래에 키보드를 붙일 수 없다 | 회고 묶음의 컨디션 누름만 새 메시지로 답하고 거기에 1단계 키보드 (14) |
| 13 | 4.3 표 | `conversations`를 앱 요청이 열 때의 작성자가 표에 없다 | 디스패처(`route_app_message`)로 둔다. 쓰기 경로 감시에 넣는다 (06, 15) |

## 스펙 대비 확인 (셀프 리뷰)

스펙 1장 완료 조건
- 1 (화면 넷, 다섯 확대, 텔레그램과 같은 값) → 02, 03, 15(같은 함수 계약), 16~18, 20
- 2 (꺼짐 10초, 기록 없음) → 16, 20
- 3 (401, CORS, 로그) → 01, 08, 15
- 4 (GET은 `mode=ro`) → 01
- 5 (월말 사다리, 분기 영역 점수, 디버프) → 03, 09, 14, 20
- 6 (초안은 확정 전 어디에도 없음) → 09, 11
- 7 (`seed-life`) → 10
- 8 (경험치는 줄지 않음, 속성 테스트) → 15
- 9 (`/chat` SSE, `/actions` `undo_id`, 한 번 되돌림) → 04, 05, 06, 20
- 10 (주 통로 `app`, 푸시, 대체, 상한 1) → 08, 20
- 11 (자동 테스트, SP1 그대로) → 작업 방식, 15

스펙 절
- 3 → 00 · 4.2~4.3 → 01, 04, 15 · 4.4 → File Structure
- 5.1 → 01, 06, 07 · 5.2 → 04, 05 · 5.3 → 08, 12 · 5.4 → 09, 10 · 5.5 → 03, 15
- 6.1 → 01 · 6.3.1 → 01, 08 · 6.3.2~6.3.4 → 02 · 6.3.5~6.3.6 → 03 · 6.4 `/schema` → 02 · 6.4.1 → 06 · 6.4.2 → 04 · 6.4.3~6.4.4 → 05 · 6.4.5 → 02, 07 · 6.4.6 → 02 · 6.4.7 → 02, 12 · 6.4.8~6.4.9 → 08
- 7.1~7.2 → 07 · 7.3 → 08 · 7.4 → 02 · 7.5 → 06
- 8 → 03, 18 · 9.1 → 15 · 9.2~9.4 → 03, 09 · 10 → 09, 11, 12, 15 · 10.1 → 13
- 11.1~11.2 → 14 · 11.3 → 11 · 11.4 → 15 · 12 → 10 · 13 → 16~18 · 14 → 01, 08, 16, 19 · 15 → 01, 08 · 16 → 각 티켓, 15 · 17 → 확정됨(Dahun 2026-10-24) · 부록 A → 09, 11, 14, 15, 16

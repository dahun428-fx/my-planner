# SP3-4 HTTP API · 인생 곡선 · 상태창 · 웹 대시보드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰하고, 지적을 반영한 뒤 다음 티켓으로 간다.

**Goal:** 노트북 BE 안에 HTTP API `/api/v1`을 열고, 그 위에 인생 곡선과 상태창을 올리고, 폰에서도 여는 읽기 전용 웹 대시보드(Vercel)를 만든다. 텔레그램, 운영 앱, 대시보드가 같은 데이터를 보고, 쓰기는 디스패처 한 곳에서만 일어난다.

**Architecture:**
- SP1 asyncio 루프에 aiohttp `AppRunner` + `TCPSite("127.0.0.1", 8787)`(ADR 0007). 밖에서는 `tailscale serve`로만 닿는다.
- 쓰기는 `Dispatcher`의 두뇌 갈래(SP1 큐)와 즉시 갈래(신규 `Dispatcher.apply_action`)뿐이다. `GET`은 `mode=ro` 연결만 받는다(스펙 4.3).
- 대시보드는 `web/dashboard/`의 Next.js 정적 내보내기이고 브라우저가 BE를 직접 부른다(ADR 0008).
- 계획은 **세로 티켓**(Matt Pocock `to-tickets`)이다. 순서: 운영 앱이 기다리는 계약 줄(뼈대·인증·`/health` → 읽기 → `/actions`·되돌리기 → `/chat` → 통로 규칙 → 푸시 → 앱 화면 조각·확인 카드) → 곡선 데이터와 `seed-life` → 곡선 두뇌 도구 → 회고 흐름 → 경험치·상태창 → 대시보드.
- BE 티켓의 수용 확인은 SP1 이음매(`FakeBrain`, `FakeClock`, `FakeSender`, 임시 SQLite)에 더하는 `tests/be_env.py BeEnv`(실제 조립 함수 `app.build_be` + aiohttp `TestClient` + 텔레그램 입력 이음매)로 끝에서 끝까지 돈다.

**Tech Stack:**
- BE: Python 3.12, SP1 의존성 + `aiohttp>=3.10,<4`, `pywebpush>=2,<3`. 개발: `hypothesis>=6`, `jsonschema>=4.23`. 판은 01·08이 `requirements.lock`에 고정.
- 대시보드: Node 20+, **Next.js 15 Pages Router + `output: "export"`**, React, Recharts, Vitest + Testing Library + MSW + jsdom, `json-schema-to-typescript`. 판은 16의 `package-lock.json`.
  - 고른 이유(한 줄): 스펙이 Next.js 정적 내보내기를 정했고(4.4, 13.1), App Router는 정적 HTML에 인라인 RSC `<script>`를 넣어 14장의 `script-src 'self'`와 맞지 않으므로 Pages Router로 한다.
- 화면 제작: UI UX Pro Max 스킬(github `nextlevelbuilder/ui-ux-pro-max-skill`), taste 스킬(github `Leonxlnx/taste-skill`). 16의 디자인 단계에서 쓴다.

**Spec:** [`docs/superpowers/specs/2026-10-24-sp3-4-life-curve-dashboard-design.md`](../specs/2026-10-24-sp3-4-life-curve-dashboard-design.md) (main `e610afb`, 17장 미결은 2026-10-24 Dahun이 적힌 안대로 확정). 상위: [마스터 설계](../specs/2026-10-23-my-planner-master-design.md), [SP1 스펙](../specs/2026-10-23-sp1-secretary-core-design.md), [SP1 계획](2026-10-23-sp1-secretary-core.md). 용어 [`GLOSSARY.md`](../../../GLOSSARY.md), 결정 [`docs/adr/`](../../adr/) 0001~0008.
- 스펙과 이 계획이 다르면 스펙이 맞다. 이 계획이 스펙의 빈 곳을 정한 자리는 끝의 "스펙 빈 곳과 이 계획의 결정"에 모았고, 티켓 21a·21b가 스펙에 옮긴다.
- 아래 티켓은 스펙을 다시 쓰지 않는다. "6.4.2 그대로"처럼 절을 가리키고, 시그니처·시험·스펙에 없는 결정만 적는다.

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

- SP1 계획의 TDD 주기: 슬라이스마다 테스트 하나 → `python -m pytest <파일>::<테스트> -v`로 FAIL(새 이름은 `ImportError`/`AttributeError`, 새 동작은 `AssertionError`) → 구현 → 같은 명령으로 PASS.
- 수용 확인 명령(모든 티켓 공통): `python -m pytest <노드 id> -v` → `1 passed`("→ `passed`"로 줄여 적은 곳도 같다).
- 티켓 끝 검증(BE 티켓 공통): `python -m pytest -q` → `0 failed`(Linux에서 Windows 전용 시험은 `skipped`), **SP1 시험 전부**가 고치지 않은 채 통과(완료 조건 11). `ruff check src tests` → `All checks passed!`. 그다음 `code-reviewer` 리뷰, 커밋.
- 생성자는 키워드 전용, 새 인자는 기본값이 있어 SP1 호출이 그대로 돈다(`Dispatcher`, `Tools`, `Runner`, `ConversationRouter`, `TranscriptStore.append`, `ConversationsRepo.open/latest_open`).
- 사용자에게 보이는 새 문구는 스펙 부록 A와 13장 그대로다. 부록 A에 없는 것은 끝의 **문구 표**(Dahun 확인 필요)에 있다.
- 시험 날짜는 요일을 박는다: 2026-10-24(토)·25(일)은 주말 일정(아침 10:00, 저녁 18:00), 10/26(월)~30(금)은 평일 일정(09:00, 17:30), 주간 회고는 일요일 18:00(`config.toml`). `kst(y, mo, d, h, mi=0)`(SP1 `tests/test_dispatcher_messages.py`)에는 초 인자가 없으니 초는 `+ timedelta(seconds=…)`로 더한다.

## Review Focus

스펙이 암시하지만 스펙 시험 표가 다루지 않고, 쓰다가 먼저 부딪힐 다섯 가지. 시험은 맡은 티켓에 있다.

1. **기기 시간대가 한국이 아닌 브라우저**: 대시보드의 모든 시각은 기기와 상관없이 `Asia/Seoul`. → 16 `time.test.ts`
2. **잘못된 쿼리 값**: `from > to`, 모르는 `zoom`, `limit=0`·`1000`, 깨진 `since`, 숫자가 아닌 경로 id, `include_sensitive=yes` → 500이 아니라 `400 invalid_request`(경로 id는 `404`), 로그는 경로 틀만. → 02, 03, 05
3. **BE URL 입력 모양**: 끝 `/`, 끝 `/api/v1`, 앞뒤 공백은 정규화, `http://`와 허용 범위 밖은 이유와 함께 거절. → 16 `connection.test.ts`
4. **메모장으로 고친 시드 파일**: BOM, 틀린 날짜(`2019-13`), 모르는 `kind` → BOM은 읽고, 틀린 항목은 이유별 개수만, 내용은 출력하지 않는다. JSON이 아니면 코드 6. → 12
5. **새벽(00:00~03:59) 경계**: 01:30에 끝낸 할 일은 전날 논리적 날짜라 전날 쉬는 날(X9)이 없고, 01:30에 누른 사다리 버튼은 버튼에 든 달에 기록된다. → 14, 15

---

## File Structure

```
pyproject.toml, requirements.lock, config.toml([api], [notify]), .env.example, README.md(19)
docs/spikes/2026-11-sp3-4.md (00), docs/acceptance/sp3-4-checklist.md (20)
src/my_planner/
  cli.py, __main__.py            # gen-token, gen-vapid, schema, seed-life
  app.py                         # build_be()와 API 수명
  config.py, domain.py
  api/{server,auth,cors,models,read,chat,actions,push,health}.py
  harness/{stream,delivery,checkins,review_steps}.py, harness/prompts/{review_month,review_quarter,review_year,channel_app}.md
  curve/{model,seed}.py, status/{xp,snapshot}.py
  store/db.py(open_ro, transaction), store/views.py, store/migrations/006~011_*.sql
  store/repos/{curve,status,activity,push,cards,channels}.py
  tools/{actions,activity,ui}.py
tests/
  be_env.py, dashboard_seed.py, fakes.py(+ ListSink, FakePushSender, FakeTurn.deltas), ui_stream.py
  fixtures/{life_seed_example.json, app_golden/}  (꾸며 낸 내용)
web/dashboard/                   # Vercel 루트 디렉터리
  package.json, next.config.mjs, vercel.json, scripts/{check-csp,gen-types}.mjs
  src/pages/{_app,_document,index,tasks,curve,status,settings}.tsx, src/{lib,components,screens,styles,api,test}/
```

## 티켓 지도

| # | 티켓 | 막는 티켓 | 라벨 |
|---|---|---|---|
| 00 | 착수 전 검증 S7~S12 | 없음 | `ready-for-agent`(클라우드 원형) + `needs-laptop`(S7~S10 기기 부분, 클라우드에 구독 로그인이 없으면 S11·S12) |
| 01 | API 뼈대: 마이그레이션, 연결 단위 트랜잭션, 인증·CORS·로그, `/health`, `BeEnv` | 00(클라우드 부분) | `ready-for-agent` |
| 02 | 읽기 API: 할 일·컨디션·답할 회차·대화·카탈로그·스키마 | 01, 21a | `ready-for-agent` |
| 03 | 읽기 API: `/curve`, `/status` 읽기 모델 | 02 | `ready-for-agent` |
| 04 | 즉시 갈래, 활동 기록, `POST /actions` | 02 | `ready-for-agent` |
| 05 | 되돌리기와 `GET /activity` | 04 | `ready-for-agent` |
| 06 | 앱 채팅 `POST /chat` (글 블록 하나, S11 대체 경로) | 04 | `ready-for-agent` |
| 06b | `/chat` 글 조각 스트리밍 | 06, 00(S11) | `ready-for-agent`(S11이 노트북에서 돌았으면 `needs-laptop` 없이) |
| 07 | 통로별 대화 규칙, 가르기, 답한 회차 | 05, 06 | `ready-for-agent` |
| 08 | 웹 푸시와 회차 전달 D1~D8 | 07 | `ready-for-agent` |
| 09 | 앱 전용 두뇌 도구: 화면 조각과 고정 카드 | 06, 05 | `ready-for-agent` |
| 10 | 회차 차례의 확인 (10.1) | 09 | `ready-for-agent` |
| 11 | 인생 곡선 데이터 계층 | 03, 05, 21b | `ready-for-agent` |
| 12 | `seed-life` 시드 가져오기 | 11 | `ready-for-agent` |
| 13 | 곡선·상태 두뇌 도구와 사건 초안 버튼·카드 | 11, 09 | `ready-for-agent` |
| 14 | 회고 단계: 월말 사다리, 분기 영역 점수, 연말 | 13, 07, 21b | `ready-for-agent` |
| 15 | 경험치, 레벨, `/status`, 쓰기 경로 감시 | 14, 08, 10 | `ready-for-agent` |
| 16 | 대시보드 뼈대와 (a) 비서 상태 | 03 | `ready-for-agent` |
| 17 | 대시보드 (b) 할 일 + 컨디션, (d) 상태창 | 16 | `ready-for-agent` |
| 18 | 대시보드 (c) 인생곡선 | 16 | `ready-for-agent` |
| 19 | Vercel 배포, Tailscale serve, 운영 안내 | 15, 17, 18 | `needs-laptop` |
| 20 | 노트북 수용 테스트 | 19 | `needs-laptop` |
| 21a | 스펙 갱신: 계약에 걸린 빈 곳 | 없음 | `ready-for-agent` + **Dahun 검토** |
| 21b | 스펙 갱신: 문구와 표시 (C1~C4, 빈 곳 8·10·12·14) | 없음 | `ready-for-agent` + **Dahun 검토** |

- **운영 앱 계약 줄**: 00 → 01 → 02 → (03, 04 → (05, 06) → 07 → 08, 06b) → 09 → 10. 운영 앱 스레드는 02 뒤 `GET /schema`로 타입을 만든다.
- **곡선·상태창 줄**: 11 → 12, 13 → 14 → 15.
- **대시보드 줄**: 16 → (17, 18)은 03 뒤 어느 때나 돈다. 고정 자료는 `tests/dashboard_seed.py`가 SQL로 바로 넣으므로 곡선 쓰기(11~15)를 기다리지 않는다.
- 21a·21b는 문서만 바꾸고 Dahun이 PR을 검토하는 사람 관문이다. 21a는 계약 줄의 02를, 21b는 문구를 쓰는 11·14를 막는다. 둘 다 01과 나란히 시작한다.

---

### 티켓 00: 착수 전 검증 (S7~S12)

**목표:** 스펙 3장 S7~S12를 확인하고 뒤 티켓이 쓸 값을 정한다. 결과는 `docs/spikes/2026-11-sp3-4.md`(SP1 `docs/spikes/2026-10-sp1.md` 모양). 실패한 항목은 스펙의 해당 절을 먼저 고친다.
**막는 티켓:** 없음
**라벨:** 클라우드 원형과 기록은 `ready-for-agent`. S7~S10의 기기 부분은 `needs-laptop`. S11·S12는 로그인된 Claude가 필요하므로 클라우드에 구독 로그인이 없으면 `needs-laptop`.

**Files:** Create `docs/spikes/2026-11-sp3-4.md`, `spikes/s7_loop.py` … `spikes/s12_tools.py`. `spikes/`는 `.gitignore`라 저장소로 오지 않는다: 노트북 쪽 항목은 Remote Control 세션이 노트북 작업 폴더에 같은 파일을 그 자리에서 쓰고 돌린다.

- [ ] **S7**: 클라우드 `s7_loop.py`(한 루프에 `AppRunner`, 가짜 롱폴링, 10초 tick, 5초 가짜 두뇌) → `curl -s -o /dev/null -w "%{time_total}\n" http://127.0.0.1:8787/ping` 10회 모두 0.1초 미만. `needs-laptop`: 작업 스케줄러에서 `pythonw.exe spikes\s7_loop.py`(Proactor), 그 루프에서 Agent SDK `query(...)` 중에도 `/ping`이 답하고 콘솔 창이 뜨지 않는다. 실패면 스펙 3장 S7 대안으로 4.3과 01 `start_api`를 고친다.
- [ ] **S8**: 클라우드 `s8_sse.py`(200ms 간격 `text-delta` 20개, `X-Accel-Buffering: no`) → `curl -N -s http://127.0.0.1:8787/sse | ts -s '%.s'`. `ts`(moreutils)가 없으면 `| python -u -c "import sys,time;t=time.time();[print(f'{time.time()-t:.3f}',l,end='') for l in sys.stdin]"`. 기대 간격 ≈ 0.2초. `needs-laptop`: MagicDNS·HTTPS 인증서 → `tailscale serve --bg --https=443 http://127.0.0.1:8787` → 폰(셀룰러)과 노트북 브라우저에서 같은 측정, 첫 조각 지연 기록.
- [ ] **S9**: 클라우드 `curl -si -X OPTIONS -H "Origin: https://example.vercel.app" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Private-Network: true" http://127.0.0.1:8787/api/v1/health` → `204`, `Access-Control-Allow-Private-Network: true`. `needs-laptop`: Vercel 미리보기의 시험 페이지에서 데스크톱 Chrome, Android Chrome, iOS Safari로 `fetch`, 권한 창 문구 기록(19의 안내에 쓴다).
- [ ] **S10**: 클라우드 `pywebpush` + VAPID로 로컬 가짜 푸시 서버(201·404·410)에 보내고 `http_ece`로 풀어 원문 비교, `TTL`·`Topic` 헤더 확인. `needs-laptop`: Windows 설치, Android Chrome과 iPhone PWA(iOS 16.4+)에서 수신.
- [ ] **S11**: `include_partial_messages=True`의 `StreamEvent` 글 조각을 이어 붙이면 `ResultMessage.result`와 같다. `resume=<id>` + `fork_session=True`: 새 `session_id`, 첫 호출의 단어 기억, 원래 세션은 갈라진 쪽을 모름. 실패면 스펙 3장 S11 대안이 06·07의 기본이다(06은 이미 대체 경로로 시작한다).
- [ ] **S12**: 더미 도구 28개(13·09·15의 실제 이름)로 SP1 S2의 두 질문 → `mcp__planner__*`만, `Read` 불가. 22개로도 한 번.
- [ ] **기록**: 항목마다 성공 여부, 명령, 출력 요약, 정한 값(`aiohttp`·`pywebpush` 판, 첫 조각 지연, PNA 안내 문구, `StreamEvent` 필드 경로, `fork_session` 형식).
- [ ] **수용 확인**: 기록에 S7~S12 행이 모두 있고(`needs-laptop` 행은 "노트북 대기"라도), 클라우드 실패 행이 있으면 스펙을 먼저 고친 커밋이 있다.
- [ ] **Commit** `docs: record SP3-4 spike results`

---

### 티켓 01: API 뼈대 — 마이그레이션, 인증·CORS·로그, `/health`, `BeEnv`

**목표:** 폴링 시작 뒤 `127.0.0.1:8787`에 API를 연다. `/health`는 6.3.1, 인증·CORS·로그는 6.1·14장 그대로. 마이그레이션 006~010(5장 SQL 그대로). 연결 단위 트랜잭션 `transaction(conn)`을 만들고 저장소의 `with self.conn:` 17곳을 바꾼다(뒤 티켓의 "한 트랜잭션"이 모두 이것을 쓴다). 회차 전달 기록(`run_deliveries`)의 텔레그램 쓰기도 여기서 시작한다. 모든 수용 시험이 쓰는 `BeEnv`를 만든다.
**막는 티켓:** 00(클라우드 부분). S7 노트북 결과가 실패면 `start_api`를 스펙 대안대로 고친다.
**라벨:** `ready-for-agent`

**Files:**
- Create: `store/migrations/006_channels.sql`~`010_status.sql`, `cli.py`, `api/{__init__,server,auth,cors,models,health}.py`, `harness/checkins.py`, `store/repos/{channels,push}.py`, `tests/be_env.py`
- Modify: `__main__.py`, `app.py`, `config.py`, `store/db.py`, `store/repos/*.py`(`with self.conn:` 17곳, `state`, `runs`, `conversations` 읽기), `harness/dispatcher.py`(생성자, `_call_brain`, `_run_delivered`), `loop/runner.py`, `config.toml`, `.env.example`, `pyproject.toml`, `requirements.lock`
- Test: `tests/test_migrations.py`, `tests/test_transaction.py`, `tests/test_api_{auth,cors,health,logging,readonly,e2e}.py`, `tests/test_app_start.py`, `tests/test_cli.py`

**Interfaces**
- Consumes: `open_db`, `migrate`, `StateRepo`, `RunsRepo`, `Runner`, `Dispatcher`, `app._serve`, `handle_update`, `handle_callback`, `TelegramSender` (SP1)
- Produces:
- `config.py`: `ApiConfig(enabled=True, host="127.0.0.1", port=8787, cors_origins=[], cors_origin_regex="", max_body_kb=64)`, `NotifyConfig(default_primary="app")`, `Settings.api_token: SecretStr | None`, `API_TOKEN_MIN_CHARS = 43`.
- `store/db.py`: `open_ro(path) -> sqlite3.Connection`(4.3의 URI). `transaction(conn) -> ContextManager[None]`: 깊이를 연결마다 센다(`_DEPTH: dict[int, int]`, 키 `id(conn)`). 가장 바깥만 `BEGIN IMMEDIATE`·`commit`·`rollback`, 안쪽은 합류하고 예외를 올린다. `TasksRepo.transaction()`은 위임. 모든 저장소의 `with self.conn:`을 `with transaction(self.conn):`으로(지금은 바깥 트랜잭션 안에서 부르면 그 자리에서 커밋한다. 예: `StateRepo.incr_usage`). `LATEST_VERSION: int`(`store/migrations/`의 가장 큰 번호).
- 읽기: `Run.answered_at/answered_via`, `RunsRepo.on_logical_date(d, tz, boundary)`, `Conversation.channel/forked_from`, `PushRepo.count_active()`, `.last_success_at()`, 상태 키 `brain_auth_state`, `brain_auth_checked_at`, `notify_primary`.
- `DeliveriesRepo(conn, clock)`: `record(run_id, channel, mode: Literal["full", "fallback"], status: Literal["sent", "not_sent"], *, push_ok=0, push_failed=0) -> None`(같은 `(run_id, channel)`은 덮어씀), `sent_channels(run_id) -> list[str]`. `Dispatcher(..., deliveries: DeliveriesRepo | None = None)`(None이면 SP1과 같다). `Dispatcher._run_delivered`가 텔레그램 전송 성공마다 `record(run.id, "telegram", "full", "sent")`를 `mark_done`·`proactive_messages` 증가와 같은 `transaction(conn)`에 쓴다(07이 `telegram_message_id`, 08이 앱·대체를 더한다).
- `Dispatcher._call_brain`: 결과마다 `brain_auth_state`(`ok` | `login` | `billing`)와 시각. `Runner.polling_down -> bool`.
- `harness/checkins.py`: `CheckinState = Literal["pending", "answered", "missed"]`, `checkin_state(run, *, runs, now, settings) -> CheckinState | None`, `runs_today(*, runs, deliveries, now, settings) -> list[dict]`.
- `api/models.py`: pydantic 모델, `MODELS`, `schema_bundle() -> dict`, `to_api_times(value)`(오프셋 붙은 ISO만 `Z`로), `error_response(status, code, message)`.
- `api/auth.py`: `bearer_ok(header, token) -> bool`(`hmac.compare_digest`), `AuthLimiter(clock, *, max_failures=10, window=1분)`. `api/cors.py`: `CorsPolicy(origins, origin_regex).allows(origin)`, `cors_middleware(policy)`(헤더는 6.1·14장 그대로, PNA 요청에만 `Allow-Private-Network`).
- `api/health.py`: `ErrorCounter(clock, *, window=24시간)`(`logging.Handler`, WARNING 이상을 `record.msg`로만 셈), `health_view(conn, deps) -> dict`(`notify.effective`는 08 전까지 `telegram`).
- `api/server.py`: `ApiDeps(settings, clock, token, read_conn: Callable[[], Connection], dispatcher, errors, polling_state, started_at, transcripts=None, safe_mode=False)`, `build_app(deps)`(미들웨어 `access_log` → `cors` → `body_limit` → `auth` → `safe_mode`, 모르는 경로 `404` JSON), `async start_api(app, host, port) -> AppRunner | None`(`access_log=None`, `OSError`면 `api_bind_error`), `async stop_api(runner)`. 접근 로그 `api_request {method, route, status, duration_ms}`, `route`는 경로 틀.
- `app.py`: `BeParts(state, convs, runs, tasks, conditions, transcripts, tools, router, dispatcher, runner, sender, deliveries, callbacks)`, `build_be(settings, conn, clock, *, brain_factory: Callable[[Tools], Brain], sender_factory: Callable[[TasksRepo], Sender], on_resume: Callable[[], Awaitable[None]] | None = None, sleep=asyncio.sleep, keep_awake=nullcontext) -> BeParts`: 지금 `_serve`의 조립(app.py 180~260행)을 옮긴다. `_serve`는 `brain_factory=lambda tools: ClaudeBrain(tools_factory=lambda: tools, …)`, `sender_factory=lambda tasks: TelegramSender(bot, owner, tasks=tasks)`, `on_resume=restart_polling`(뒤에 만드는 `application`을 닫힘으로 참조)을 넘긴다. `callbacks`는 `handle_callback` partial. 시작·종료 순서는 15장(폴링 뒤 `start_api`, `stop_api`는 updater 앞). 토큰이 없거나 43자 미만이면 열지 않는다(빈 곳 4). 안전 모드는 `/health`만.
- `cli.py main(argv=None) -> int`: 인자 없으면 `app.main()`, `gen-token`(뒤에 `schema` 02, `gen-vapid` 08, `seed-life` 12).
- `tests/be_env.py BeEnv.start(tmp_path, *, script=[], start, overrides=None)`(async 컨텍스트): 임시 DB, `build_be(brain_factory=lambda tools: FakeBrain(script, tools, clock=clock), sender_factory=lambda tasks: FakeSender(), sleep=fake_sleep(clock))`, `TestClient`. 속성 `client`, `clock`, `brain`, `sender`, `parts`. 메서드 `get/post/put/delete(path, …, token=TEST_TOKEN)`, `async telegram(text, *, sent_at=None)`(`Update.de_json` → SP1 `handle_update` 경로 → 큐가 빌 때까지), `async press(data, *, message_id=None)`(가짜 `CallbackQuery` → `parts.callbacks`), `async tick()`, `async drain()`.

**Slices**
- [ ] `test_nested_joins_outer_and_outer_commits_once`, `test_repo_write_inside_transaction_does_not_commit_outer`(`transaction(conn)` 안 `ConditionsRepo.upsert`·`StateRepo.incr_usage` 뒤 예외 → 둘 다 그대로), `test_no_with_conn_left_in_store`, `test_sp1_tasks_transaction_unchanged`(`tests/test_tools_tasks.py -q` → `0 failed`) (`tests/test_transaction.py`)
- [ ] `test_migrate_fresh_then_again`(SP1, `user_version == LATEST_VERSION`), `test_migrate_5_to_10_keeps_sp1_rows`, `test_curve_and_status_checks`(5장 CHECK마다 `IntegrityError`)
- [ ] `test_no_token_401`, `test_wrong_token_401_body_has_no_reason`, `test_right_token_200`, `test_token_in_query_or_cookie_not_accepted`, `test_ten_failures_then_429_for_a_minute`, `test_options_preflight_without_token`
- [ ] `test_allowed_origin_preflight_headers`, `test_private_network_preflight`, `test_regex_origin_allowed`, `test_other_vercel_app_not_allowed`(`https://evil.vercel.app` → `Allow-Origin` 없음), `test_expose_header_on_get`
- [ ] `test_health_fields_from_sources`(`version.schema == LATEST_VERSION`, 시각은 `Z`), `test_degraded_conditions`(매개변수 4), `test_brain_auth_unknown_until_first_call_then_written_by_dispatcher`, `test_error_counter_counts_event_names_in_24h_window`
- [ ] `test_runs_today_delivered_via_and_checkin_state`: `delivered_via == ["telegram"]`(`run_deliveries`에서), 창 안 `pending`·밖 `missed`·`answered_at` → `answered`
- [ ] `test_run_delivered_records_delivery_same_transaction`: 기록 중 예외 → `proactive_messages`와 `run_deliveries` 둘 다 그대로
- [ ] `test_safe_mode_health_only`, `test_get_handlers_receive_mode_ro_connection`
- [ ] `test_access_log_route_template_only`(`?q=SECRET-QUERY`·토큰이 로그에 없음), `test_failed_auth_log_has_no_token`, `test_body_over_64kb_413`
- [ ] `test_api_starts_after_polling_and_stops_before_updater`, `test_api_disabled_runs_like_sp1`, `test_missing_or_short_token_logs_and_skips_api`, `test_port_in_use_logs_api_bind_error_and_keeps_polling`, `test_safe_mode_opens_health_only_api`
- [ ] `test_build_be_same_wiring_as_serve`, `test_be_env_telegram_and_press`(`env.telegram("/today")` → `today_text` 글, `env.press("c:2026-10-24:4")` → 컨디션 행)
- [ ] `test_gen_token`, `test_no_args_calls_app_main`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_health_after_morning_brief`: `BeEnv.start(start=kst(2026, 10, 24, 10, 0) + timedelta(seconds=30), script=[FakeTurn([], "좋은 아침이에요")])`(토, 주말 아침) → `await env.tick()` → `GET /health`의 `runs_today[0]`이 `loop == "morning_brief"`, `status == "done"`, `delivered_via == ["telegram"]`, `checkin_state == "pending"`, `proactive.sent_today == 1`, `brain.calls_today == 1`, `brain.auth == "ok"`, `notify == {"primary": "app", "effective": "telegram"}`. `python -m pytest tests/test_api_e2e.py -v` → `1 passed`.

**마무리**
- [ ] `.env.example`에 `API_TOKEN=`, `config.toml`에 15장 `[api]`, `[notify]`.
- [ ] **Review + Commit** `feat(api): API skeleton with transactions, auth, CORS, health, deliveries and SP3-4 migrations`
---

### 티켓 02: 읽기 API — 할 일·컨디션·답할 회차·대화·카탈로그·스키마

**목표:** `GET /today`, `/week`, `/conditions`, `/checkins`, `/checkins/{id}`, `/conversations`, `/conversations/{id}/messages`, `/ui/catalog`, `/schema`가 6.3.2~6.3.4, 6.4.5~6.4.7 그대로. `/today`·`/week`와 텔레그램 `/today`·`/week`가 같은 함수에서 나온다(16장 계약 테스트).
**막는 티켓:** 01, 21a
**라벨:** `ready-for-agent`

**Files:**
- Create: `store/views.py`, `api/read.py`, `tools/ui.py`(카탈로그)
- Modify: `bot/commands.py`, `store/transcripts.py`, `store/repos/{conditions,conversations}.py`, `harness/{checkins,context,dispatcher}.py`, `api/{models,server}.py`, `cli.py`
- Test: `tests/test_api_read.py`, `tests/test_api_schema.py`, `tests/test_transcript_channels.py`

**Interfaces**
- Consumes: `TasksRepo`, `ConditionsRepo`, `RunsRepo`, `TranscriptStore`, `ApiDeps`, `checkin_state`, `DeliveriesRepo` (SP1, 01)
- Produces:
- `store/views.py`: `TodoGroup`, `TodayView(date, weekday, groups, condition)`, `today_view(tasks, conditions, now, tz, boundary)`, `DayView`, `WeekView`, `week_view(tasks, now, tz, boundary)`(7일 모두), `todo_dict(t, tasks, today)`(6.3 `Todo`, `priority`는 지금 기간 우선순위 중 가장 큰 주기), `conditions_view(conditions, from_, to)`. `today_text`·`week_text`는 뷰를 글로만 바꾼다.
- `harness/context.py ask_condition_for(run, merged, *, conditions, runs, settings) -> date | None`(`Dispatcher._ask_condition_for`를 옮긴 순수 함수).
- `harness/checkins.py`: `checkin_summaries(*, runs, convs, deliveries, d, now, settings)`, `checkin_detail(run_id, *, …)`, `checkin_cards(run, merged, *, tasks, conditions, runs, settings)`(빈 곳 6: `tool_events_log.run_id`의 남은 초안 → `h_draft_<run_id>` `ui_todo_draft`, 기록 없는 날 → `h_cond_<run_id>` `ui_condition_picker`. 13·10·14가 더한다).
- `TranscriptStore.append(…, *, channel="telegram")`: `app`이면 머리글 끝 ` @app`(빈 곳 1), 표시 없으면 `telegram`. `TranscriptMessage(at, speaker, text, tools, channel)`, `messages(conversation_id)`(04:00 전 `HH:MM`은 다음 날).
- `ConditionsRepo.between(from_, to)`, `ConversationsRepo.recent(*, channel, limit)`, `.for_run(run_id)`.
- `tools/ui.py`: `UI_CATALOG_VERSION = "2026-10-24.2"`, `UI_COMPONENTS`(6.4.7의 8개 + 하네스 출처 `ui_milestone_draft {"milestone_ids": int[1..10]}`, `ui_chapter_draft {"chapter_ids": int[1..5]}`, 빈 곳 7), `validate_props(component, props) -> str | None`.
- `api/read.py`: `get_today`(`checkins = checkin_summaries(d=오늘)`, `cards`는 09 전까지 `[]`), `get_week`, `get_conditions`, `get_checkins`, `get_checkin`, `get_conversations`, `get_conversation_messages`, `get_ui_catalog`, `get_schema`. `deps.read_conn()`만, `to_api_times` 뒤 모델 검증. 쿼리 `from <= to`, 366일 이하, `limit` 1~200, 경로 id 정수. `cli.py schema`.

**Slices**
- [ ] `test_today_matches_today_text_same_order`, `test_week_has_all_7_days_and_matches_week_text`, `test_today_checkins_equal_checkins_list`
- [ ] `test_drafts_and_soft_deleted_never_in_get`, `test_todo_priority_is_biggest_current_period`, `test_brief_from_done_morning_or_return`, `test_times_are_utc_z`(`"2026-10-27T05:00:00Z"`)
- [ ] `test_conditions_default_30_days_skips_empty`, `test_bad_query_values_400` (Review Focus 2)
- [ ] `test_checkin_states_and_detail_cards`, `test_merged_run_listed_once_with_latest_window`, `test_skipped_runs_are_not_checkins`, `test_conversations_list_and_messages`
- [ ] `test_app_header_has_marker`, `test_telegram_header_unchanged_and_legacy_reads_as_telegram`, `test_messages_time_after_midnight_belongs_to_next_calendar_day`
- [ ] `test_schema_lists_all_models`, `test_every_read_response_validates_against_schema`, `test_cli_schema_prints_bundle`, `test_ui_catalog_version_and_components`(`.2`, 10개)

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_today_after_chat_and_checkin`: `start=kst(2026, 10, 26, 9, 0) + timedelta(seconds=30)`(월) → 13:00 `env.telegram("내일 2시 치과")` → FakeBrain `add_task(10/27 14:00)` → 17:30 `env.tick()`(FakeBrain이 `propose_tasks` 2) → 바로(10/26 밤) `GET /checkins?date=2026-10-26`에 그 체크인 `pending`, 상세 `cards` 2개 → 시계를 10/27 09:00으로(답장 창은 04:00에 끝남) → `GET /today`에 치과 `scheduled`, 같은 체크인 `missed`. → `1 passed`

**마무리**
- [ ] 카탈로그 변경(두 컴포넌트, 판 `.2`)을 조정자를 거쳐 운영 앱 스레드에 보내 확인받는다. 기다리지 않는다.
- [ ] **Review + Commit** `feat(api): read endpoints for today, week, conditions, check-ins and conversations`
---

### 티켓 03: 읽기 API — `/curve`, `/status` 읽기 모델

**목표:** `GET /curve`, `GET /status`가 6.3.5, 6.3.6, 8장, 9.2~9.4의 계산대로 답한다. 읽기와 계산만(쓰기는 11 이후), 시험 고정 자료는 SQL로.
**막는 티켓:** 02
**라벨:** `ready-for-agent`

**Files:** Create `curve/{__init__,model}.py`, `status/{__init__,xp,snapshot}.py`, `store/repos/{curve,status}.py`(읽기). Modify `api/{read,models,server}.py`. Test `tests/test_curve_model.py`, `tests/test_status_snapshot.py`, `tests/test_api_curve_status.py`

**Interfaces**
- Consumes: `ConditionsRepo.between`, `TasksRepo`, `period_of`, `ApiDeps` (02)
- Produces:
- `CurveRepo(conn, clock)` 읽기: `Chapter`, `Milestone`, `Ladder`, `AreaScore`(5.4 열 그대로), `chapters_overlapping(from_month, to_month)`, `milestones_between(from_, to, *, include_sensitive)`(확정만), `ladder_between`, `area_scores_between`, `latest_area_periods(n=2)`, `area_scores(period)`, `area_default(area)`, `earliest_chapter_start()`, `get_milestone(id)`, `get_chapter(id)`
- `StatusRepo(conn, clock)` 읽기: `total()`, `recent(n=5) -> list[XpEntry(at, label, amount)]`, `titles(*, include_sensitive)`
- `curve/model.py`: `Zoom`, `MAX_BUCKETS = 400`, `Bucket(name, start, end)`, `TooManyBuckets(ValueError)`, `default_range(zoom, today, earliest_chapter)`, `buckets(zoom, from_, to)`, `bucket_conditions(conditions, bs)`, `reassurance(ladder, conditions)`, `curve_view(curve, conditions, *, zoom, from_, to, include_sensitive, today) -> dict`
- `status/xp.py`(9장 상수 그대로): `XP_*`, `SECRETARY_DAILY_MAX`, `xp_threshold(level)`, `level_for(xp_total)`, `progress(xp_total) -> (level, into, for_next)`, `AREA_LABELS`, `DEFAULT_RECOVERY_QUESTS`(부록 A), `title_name(kind, title, title_label)`
- `status/snapshot.py status_snapshot(*, now, tz, boundary, status, curve, tasks, conditions, include_sensitive=False) -> dict`(6.3.6, 9.3)
- API `get_curve`(`zoom` 기본 `month`, `include_sensitive`는 `true`|`false`만), `get_status`. `TooManyBuckets` → `400` "범위를 줄이거나 확대 단위를 키워 주세요".

**Slices**
- [ ] `test_buckets_iso_week_and_quarter_boundaries`(2026-12-28~2027-01-03 = `2026-W53`), `test_default_ranges_per_zoom`, `test_year_zoom_from_earliest_chapter`, `test_over_400_buckets_raises`
- [ ] `test_bucket_conditions_average_logged_days_only`, `test_reassurance_scaling_and_7_day_threshold`(평균 3.4·사다리 6 → `6.0`, `gap == 0.0`)
- [ ] `test_level_table`(2→150, 5→900, 10→3150, `progress(1380) == (6, 130, 400)`), `test_stats_latest_quarter_falls_back_to_previous_with_period`, `test_debuff_only_when_both_quarters_and_lower`, `test_recovery_quest_priority`, `test_no_area_scores_stats_null_no_debuff`, `test_hp_today_condition_or_null`, `test_main_and_daily_quests`, `test_titles_template_label_override_and_sensitive_excluded`
- [ ] `test_curve_excludes_drafts_and_sensitive_by_default`, `test_include_sensitive_true_marks_flag`, `test_curve_bad_query_400` (Review Focus 2), `test_curve_and_status_validate_against_schema`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_curve_and_status_read_model`: `env.telegram`으로 할 일을 만들고 분기 우선순위로(FakeBrain), 곡선 고정 자료는 SQL → `GET /curve?zoom=quarter`의 `areas`·`reassurance`, `GET /status`의 `main_quests[0].title`, `level == 1`, `xp_total == 0`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(api): curve and status read model`
---

### 티켓 04: 즉시 갈래, 활동 기록, `POST /actions`

**목표:** `POST /actions`가 6.4.2대로 답한다. 변경 도구는 데이터, `tool_events_log`, `activity`(`/actions`면 `api_idempotency`까지)를 **한 트랜잭션**에 쓴다. 트랜잭션은 01의 `transaction(conn)`을 쓴다. 텔레그램 버튼과 하루 한 번 작업이 `apply_action`을 거친다.
**막는 티켓:** 02
**라벨:** `ready-for-agent`

**Files:**
- Create: `tools/{actions,activity}.py`, `store/repos/activity.py`, `api/actions.py`
- Modify: `domain.py`, `tools/{core,confirmations}.py`, `harness/dispatcher.py`, `bot/callbacks.py`, `loop/runner.py`, `app.py`, `api/{models,server}.py`, `tests/be_env.py`
- Test: `tests/test_api_actions.py`, `tests/test_activity.py`, SP1 `tests/test_telegram_{drafts,conditions}.py`(그대로)

**Interfaces**
- Consumes: `Tools` 변경 메서드, `transaction(conn)`, `render_confirmations`, `ApiDeps.dispatcher` (SP1, 01)
- Produces:
- `domain.py`: `Channel`, `ActivityChannel`, `Actor`. `RunContext`에 `actor="secretary"`, `activity_channel=None`, `channel="telegram"`, `activity_ids`, `undo_ids`.
- `store/repos/activity.py`: `Activity(...)`(5.2 열), `ActivityRepo.add(...) -> int`, `.get(id)`, `.changed_after(target, after)`; `IdempotencyRepo.get/put/prune`; `ConfirmsRepo.create(*, action, args, summary, origin: Literal["actions", "run_turn"], expires_at, run_id=None, conversation_id=None)`(`"ct_" + token_urlsafe(16)`), `.get`, `.resolve`, `.expire`, `.prune`.
- `tools/activity.py`: `activity_origin(ctx) -> (Actor, ActivityChannel)`, `record_activity(repo, ctx, *, kind, target, summary, risk, undo) -> int`(대상 문자열은 5.2).
- `Tools(..., activity=None)`: 변경 메서드 10개가 `_finish` 안에서 `record_activity`(`summary` = 확인 문구 한 줄, `undo` = 바꾸기 전 값). `Tools.expire_drafts(ctx, older_than)`. `confirmation_line(e, today)`(지금 `_line`의 공개 이름).
- `tools/actions.py`: `ActionRequest(action, args, *, actor, channel, client_msg_id=None, confirm_token=None, endpoint="actions")`, `ActionResult(status, http_status, body)`, `ActionSpec(tool, needs_confirm=None, public=True)`, `ACTIONS`(6.4.2 표, 위험 칸 그대로 + 내부 `expire_drafts`, `prune_api_state`). `xp`는 15 전까지 `{"gained": 0, "level_up": null}`.
- `Dispatcher(..., activity=None, idempotency=None, confirms=None)`, `apply_action(req) -> ActionResult`: 동기, 6.4.2 순서. 적용 결과와 `api_idempotency`는 `transaction(conn)` 하나. 토큰 대상에 생성 뒤 활동이 있으면 `stale` → 409.
- `handle_callback(..., apply=None)`: `d:c`, `d:x`, `d:all`, `c:`를 `ActionRequest(actor="user", channel="telegram")`로(답 문구 SP1 그대로). `BeEnv.press`가 `apply`를 쓴다.
- `loop/runner.py`: 하루 한 번 `expire_drafts`, 토큰 만료·정리, `api_idempotency` 2일 정리를 `apply_action(actor="secretary", channel="scheduler")`로.
- `api/actions.py post_actions`(`client_msg_id` 필수, `user`/`app`). 모델 `ActionRequestBody`, `ActionApplied`, `ActionNeedsConfirm`, `ActionRejected`.

**Slices**
- [ ] `test_complete_task_applied_shape`(`"✓ 완료: 운동"`, `Z`), `test_every_public_action_applies`, `test_rejected_422_uses_tool_message`
- [ ] `test_needs_confirm_drop_priority_task_then_apply_with_token`, `test_set_priorities_quarter_replacing_nonempty_needs_confirm`, `test_set_priorities_quarter_first_time_applies`
- [ ] `test_confirm_token_used_or_expired_409`, `test_confirm_token_stale_409`, `test_decline_confirm_closes_token_changes_nothing`
- [ ] `test_duplicate_client_msg_id_returns_first_response`, `test_missing_client_msg_id_400`, `test_unknown_or_internal_action_400`
- [ ] `test_actions_result_and_idempotency_atomic`: `IdempotencyRepo.put`에서 예외 → 할 일·`activity`·`api_idempotency` 그대로, 재요청은 정상 적용
- [ ] `test_activity_same_transaction_as_change`(할 일), `test_record_condition_and_activity_atomic`(`ActivityRepo.add` 예외 → 컨디션 행 없음)
- [ ] `test_actor_channel_mapping`, `test_activity_summary_has_no_message_body`, `test_buttons_go_through_apply_action`(`env.press("d:c:<id>")` → `tasks_confirmed` `user`/`telegram`), `test_daily_jobs_expire_tokens_and_prune_idempotency`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_actions_end_to_end`: `env.telegram("운동 추가")` → FakeBrain `add_task` → `POST /actions complete_task` → `env.telegram("/today")` 글과 `GET /today`에서 빠짐, 같은 `client_msg_id`는 같은 본문. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(api): apply_action, activity log and POST /actions`
---

### 티켓 05: 되돌리기와 `GET /activity`

**목표:** `POST /activity/{id}/undo`가 U1~U6과 6.4.3 종류별 표대로 정확히 한 번 되돌린다. `GET /activity`는 6.4.4, 지금 되돌릴 수 있는 것에만 `undo_id`.
**막는 티켓:** 04
**라벨:** `ready-for-agent`

**Files:**
- Modify: `tools/{activity,actions,core}.py`, `store/repos/{activity,tasks,conditions}.py`, `api/{actions,models,server}.py`
- Test: `tests/test_api_undo.py`, SP1 `tests/test_tools_drafts.py`(그대로)

**Interfaces**
- Consumes: `ActivityRepo`, `IdempotencyRepo`, `apply_action`, `transaction(conn)` (01, 04)
- Produces:
- `UndoHandler = Callable[[Tools, dict, RunContext], str | None]`(칸이 차 있으면 `"superseded"`), `UNDO_HANDLERS`, `register_undo(kind, handler)`. 종류: `task_added`, `task_updated`, `task_moved`, `task_completed`, `task_reopened`, `task_dropped`, `tasks_confirmed`, `priorities_set`, `condition_recorded`(09·11이 더한다).
- 복원 함수: `TasksRepo.restore(id, *, status, completed_at, deleted_at) -> None`(넘긴 시각 그대로. `task_added` → `deleted_at` 지금, `task_reopened` → 이전 `done`·`completed_at`), `TasksRepo.restore_priority(cadence, period, rank, task_id) -> bool`(칸이 비었을 때만), `ConditionsRepo.restore(d, before: Condition | None)`(None이면 행 삭제).
- `undoable_now(a, repo, now) -> bool`(U1~U3). `ACTIONS["undo"]`(`public=False`): 결과는 6.4.3 그대로. 새 활동(`kind="undo"`)과 원래 행의 `undone_at`·`undone_by`는 한 `transaction(conn)`. 원장은 건드리지 않는다(U6).
- `TasksRepo.expire_drafts(older_than)`: 기준은 가장 최근 `task_events.kind='proposed'`(없으면 `created_at`). `tasks_confirmed` 되돌리기가 `proposed`를 새로 쓴다.
- `ActivityRepo.since(after, limit)`. `api/actions.py post_undo`, `get_activity`(`limit` 1~200 기본 50, `next_since`). 모델 `UndoRequestBody`, `UndoResponse`, `ActivityResponse`.

**Slices** (`BeEnv`, 변경은 `/actions`로)
- [ ] `test_undo_each_kind`(매개변수 9), `test_undo_task_dropped_restores_priority_only_if_slot_empty`
- [ ] `test_undo_tasks_confirmed_restarts_draft_clock`: 제안 → 2일 뒤 확정 → 바로 되돌림 → 그로부터 2일 23시간 뒤 `draft`, 3일 뒤 `dropped`
- [ ] `test_undo_and_undone_at_atomic`: `undone_at` 쓰기에서 예외 → 대상과 활동 그대로
- [ ] `test_u1_not_undoable`, `test_u2_24h_boundary`, `test_u3_superseded_chain`, `test_u4_double_undo_already_undone_same_with_same_client_msg_id`, `test_u5_undo_of_undo_not_undoable`
- [ ] `test_activity_list_shape_order_and_undo_id_now`, `test_activity_bad_query_400_and_bad_path_404` (Review Focus 2)

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_undo_end_to_end`: `env.telegram` 대화에서 FakeBrain `complete_task` → `GET /activity`에 `undo_id`(`secretary`/`telegram`) → 되돌림 → `GET /today`와 `env.telegram("/today")`에 다시 나옴, 재요청 `already_undone`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(api): undo rules U1-U6 and GET /activity`
---

### 티켓 06: 앱 채팅 `POST /chat` (글 블록 하나, S11 대체 경로)

**목표:** 운영 앱의 `POST /api/v1/chat`이 두뇌 갈래를 지나 AI SDK UI message stream으로 답한다(6.4.1, 7.5 M1~M8). 두뇌 글은 S11 대체 경로대로 **끝난 뒤 글 블록 하나**(조각 스트리밍은 06b). 명령은 같은 함수. 대화 규칙은 앱 통로의 `chat`·`plan`만(회차 대화와 가르기는 07). S11을 기다리지 않는다.
**막는 티켓:** 04
**라벨:** `ready-for-agent`

**Files:**
- Create: `harness/stream.py`, `api/chat.py`, `store/migrations/011_inbound_conversation.sql`, `tests/ui_stream.py`, `tests/fixtures/app_golden/`
- Modify: `domain.py`, `harness/{brain,dispatcher,conversations}.py`, `store/repos/{state,conversations}.py`, `loop/runner.py`(`resubmit_inbound`), `tools/mcp_adapter.py`, `bot/{commands,telegram_io}.py`, `app.py`, `api/{models,server}.py`, `tests/{fakes,conftest}.py`
- Test: `tests/test_api_chat.py`, `tests/test_dispatcher_app_channel.py`, `tests/test_app_golden.py`, `tests/test_migrations.py`, `tests/test_api_health.py`(01의 시험이 `LATEST_VERSION`과 비교하므로 고칠 숫자는 없다. `test_latest_version_is_11`과 `test_migrate_10_to_11_keeps_inbound_rows`를 더한다)

**Interfaces**
- Consumes: `Dispatcher._handle_messages`·`_drain_messages`·`_call_brain`, `StateRepo` 대기 메시지, `IdempotencyRepo`, `apply_action`, `command_of`, `build_planner_server` (SP1, 04)
- Produces:
- `011_inbound_conversation.sql`(빈 곳 15): `ALTER TABLE inbound_pending ADD COLUMN conversation_id INTEGER NULL REFERENCES conversations (id)`.
- `harness/stream.py`: `StreamSink`(Protocol `emit`, `ping`, `disconnected`), `QueueSink`(`attach() -> Queue[bytes | None]`, `detach`, `close`, 붙으면 지난 조각을 다시 넣음, M8), `encode_sse`, `SSE_DONE`, `SSE_PING`, `PING_INTERVAL_S = 15`, `UiMessageWriter(sink, message_id)`(`start`, `status`, `start_step`, `text_start/delta/end`, `text(id, whole)`, `tool_input`, `tool_output`, `tool_error`, `finish_step`, `data_activity`, `finish`, `streamed_text`), `AppReplySender.send(out)`(두뇌 글 → `h-confirm` → 하네스 조각(09·13) → `data_activity` → `finish`, 끊기면 조용히 그만둠, M7).
- `RunContext.stream`. `Inbound`에 `channel`, `client_msg_id`, `checkin_id`, `sink`, `conversation_id`. `Outbound`에 `channel`, `confirmation`, `writer`, `activity_ids`, `undo_ids`.
- `Dispatcher(..., app_sender: AppReplySender | None = None)`(빈 곳 11), `_drain_messages(lead)`(M2), `route_app_message(at, *, conversation_id, checkin_id) -> Conversation`(동기, 빈 곳 2·13. 이 티켓: 열린 앱 `plan` → 요청한 앱 `chat`이 30분 안 → 30분 안 앱 `chat` → 새 앱 `chat`. 07이 회차 규칙을 앞에 넣는다), `attach_stream(client_msg_id, sink) -> bool`(M8). 앱 `Inbound`는 `conversation_id`의 대화로 가고, 그 대화가 닫혔으면 `route_app_message`가 다시 고른다.
- `StateRepo`: `PendingInbound`에 `channel`, `client_msg_id`, `checkin_id`, `conversation_id`. `add_pending_inbound(update_id, text_redacted, sent_at, received_at, *, channel="telegram", client_msg_id=None, checkin_id=None, conversation_id=None)`, `next_app_inbound_id()`(−1, −2, …), `pending_by_client_msg_id`, `finish_app_inbound(update_id, *, client_msg_id, conversation_id, reply_text)`(M5). `resubmit_inbound`는 앱 행을 `Inbound(channel="app", sink=None, conversation_id=row.conversation_id, recovered=True)`로(M6).
- `build_options(..., include_partial_messages=False, fork_session=False)`. 이 티켓의 `ClaudeBrain.run`은 부분 메시지를 켜지 않는다. 앱이면 `system.md` + `channel_app.md`(빈 자리, 09가 채움).
- `tools/mcp_adapter.py`: `call_tool(tools, ctx, name, args) -> dict`(`ctx.stream`이 있으면 `tool_input` → `tool_output(to_api_times(result))` 또는 `tool_error`), `tool_names_for(channel)`(둘 다 `TOOL_NAMES`).
- `bot/commands.py`: `CommandDeps(tasks, conditions, state, router, clock, settings, apply)`, `run_command(cmd, text, deps, *, channel) -> str`(`/pause`·`/unpause`·`/done`은 내부 동작 `cmd_*`). 텔레그램 `_answer_command`도 이것.
- `api/chat.py post_chat(request) -> web.StreamResponse`: 6.4.1 흐름(재생 → `attach_stream` → 명령 → `route_app_message` → `add_pending_inbound(next_app_inbound_id(), …, conversation_id=…)` → `submit_message`). 헤더 6.4.1, 15초 `: ping`(주입한 `sleep`), `messageId = m-<conversation_id>-<|inbound_id|>`.
- `FakeBrain`은 `run_ctx.stream`이 있으면 도구를 `call_tool`로. `ListSink`.
- `tests/ui_stream.py`: `parse_sse(body) -> list[dict]`(첫 `start`, `text-*` `id` 짝, 같은 `toolCallId`의 출력, 마지막 `finish`, `[DONE]`, AI SDK UI message stream의 조각 종류 밖은 오류), `normalize_sse(body) -> bytes`(`messageId` → `<id>`).
- 기준 응답(빈 곳 9): `tests/test_app_golden.py`가 `BeEnv`로 `chat_add_task`, `chat_daily_cap`, `chat_replay`를 보내 `tests/fixtures/app_golden/<이름>.sse`, `headers.json`과 비교한다. `python -m pytest tests/test_app_golden.py --update-app-golden`(`tests/conftest.py` 옵션)이면 다시 쓴다.

**Slices**
- [ ] `test_chat_stream_order_and_headers`(`FakeTurn([("add_task", {...})], "내일 치과를 추가할게요.")`): 순서가 정확히 `start, data-status, start-step, tool-input-available, tool-output-available, text-start, text-delta, text-end, finish-step, text-start, text-delta, text-end, data-activity, finish`, `[DONE]`. 두뇌 글은 `text-delta` 하나, `h-confirm` 글 `✓ 추가: 치과 → 내일`, 헤더 다섯
- [ ] `test_tool_chunk_name_has_no_prefix_and_output_is_utc`, `test_daily_cap_rate_limit_login_are_text_chunks`(매개변수 3, `error` 조각 없음), `test_non_text_parts_get_non_text_reply`
- [ ] `test_same_client_msg_id_replays_without_brain`, `test_disconnect_mid_stream_completes`(M7), `test_inflight_duplicate_attaches_single_brain_call`(M8), `test_ping_every_15s_while_queued`
- [ ] `test_commands_in_app`: `/today` == `today_text`, 두뇌 없음, `/pause 3` 재요청은 다시 실행 안 함, `/plan 이사 준비`는 `kind == "plan"`
- [ ] `test_parser_reads_spec_example`, `test_app_golden_matches_stream`(매개변수 3), `test_app_golden_files_parse`
- [ ] `test_mixed_queue_batches_telegram_only`(`tests/test_dispatcher_app_channel.py`): 처리 중인 호출이 끝난 **뒤** 두뇌 호출 3회(텔레그램 묶음 1 + 앱 2), FakeSender 1개, 앱 싱크 둘이 각자 답
- [ ] `test_app_done_writes_no_telegram_updates`, `test_recovered_app_row_replies_nowhere`(M6)
- [ ] `test_resubmitted_app_row_keeps_conversation`: 재시작 뒤 같은 `conversation_id`, 닫혔으면 다시 고른 대화
- [ ] `test_daily_cap_shared_by_channels`, `test_app_tool_set_is_channel_specific`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_chat_end_to_end`: `POST /chat`("내일 치과 추가해 줘") → `parse_sse` 통과 → `GET /conversations?channel=app`, `messages`에 두 줄(`tools == ["add_task"]`) → 다음 날 `env.telegram("/today")`에 치과. → `passed`

**마무리**
- [ ] 기준 응답 네 파일과 `parse_sse` 규칙을 조정자를 거쳐 운영 앱 스레드에 보내 확인받는다. 기다리지 않는다. 차이는 새 이슈 + `--update-app-golden`.
- [ ] **Review + Commit** `feat(api): POST /chat with AI SDK UI message stream and per-channel brain lane`
---

### 티켓 06b: `/chat` 글 조각 스트리밍

**목표:** S11이 성공이면 두뇌 글을 `StreamEvent`의 글 조각대로 `text-start/delta/end`로 보낸다(6.4.1 예시 순서). S11이 실패면 이 티켓은 기록만 하고 닫는다(06이 기본).
**막는 티켓:** 06, 00(S11)
**라벨:** `ready-for-agent`(S11이 클라우드에서 돌지 못했으면 실제 SDK 확인은 노트북 결과를 쓴다)

**Files:** Modify `harness/brain.py`, `tests/fakes.py`, `tests/fixtures/app_golden/*`. Test `tests/test_brain_options.py`, `tests/test_api_chat.py`

**Interfaces**
- `ClaudeBrain.run`: `run_ctx.stream`이 있으면 `include_partial_messages=True`, S11이 정한 필드 경로의 글 조각을 `text_start/delta/end`로. 끝나고 `streamed_text`면 `AppReplySender`가 글 블록을 다시 보내지 않는다.
- `FakeTurn.deltas: list[str] | None = None`: 있으면 FakeBrain이 **도구 호출 전에** 그 조각들로 글 블록을 보낸다.

**Slices**
- [ ] `test_stream_events_become_text_deltas`: 가짜 SDK 메시지(`StreamEvent` 셋 + `ResultMessage`) → `ListSink`에 `text-start, text-delta×3, text-end`
- [ ] `test_partial_messages_only_when_streaming`
- [ ] `test_chat_stream_order_with_deltas`: `deltas=["내일 치과를 ", "추가할게요."]` → 순서 `start, data-status, start-step, text-start, text-delta, text-delta, text-end, tool-input-available, tool-output-available, finish-step, text-start, text-delta, text-end, data-activity, finish`
- [ ] 기준 응답을 `--update-app-golden`으로 다시 만들고 운영 앱 스레드에 바뀐 파일을 보낸다.

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_chat_end_to_end`가 `deltas`가 있는 FakeTurn으로도 통과. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(api): stream brain text deltas on /chat`

---

### 티켓 07: 통로별 대화 규칙, 가르기, 답한 회차

**목표:** 7.1~7.2: 텔레그램과 앱의 `chat`·`plan`은 서로 잇지 않고, 회차에 다른 통로에서 답하면 그 통로에 회차 대화를 갈라 만든다(`fork_session`). 처음 답한 통로가 `runs.answered_at`·`answered_via`에 한 번 적히고 텔레그램 버튼이 거둬진다. 다른 통로의 변경을 알림으로 받는다.
**막는 티켓:** 05, 06
**라벨:** `ready-for-agent`

**Files:**
- Modify: `harness/{conversations,dispatcher,context,checkins}.py`, `store/repos/{conversations,runs,channels,activity}.py`, `bot/{telegram_io,callbacks}.py`, `tools/actions.py`, `tests/fakes.py`
- Test: `tests/test_dispatcher_channels.py`, `tests/test_api_checkins.py`

**Interfaces**
- Consumes: `ConversationRouter`, `route_app_message`, `RunsRepo`, `DeliveriesRepo`, `apply_action`, `build_options(fork_session=…)` (SP1, 05, 06)
- Produces:
- `ConversationsRepo.open(kind, logical_date, run_id=None, *, channel="telegram", forked_from=None)`, `latest_open(kind, channel="telegram")`, `run_conversation(run_id, channel)`, `set_channel(id, channel)`.
- `ConversationRouter.for_user_message(at, *, sent_at=None, channel="telegram", checkin_id=None)`: 7.2 규칙 1~5, 이 통로의 회차 대화가 없으면 `forked_from=<원래 대화>`로 연다. `start_plan`·`end_plan(channel=…)`, `plan_open()`은 어느 통로든.
- 가르기: `forked_from`이 있고 `session_id`가 없으면 원래 `session_id` + `fork_session=True`. `resume_failed`(또는 S11 가르기 실패)면 SP1 대체 경로 + `## 회차 메시지`(원래 `outbound_text`). `Brain.run(..., fork_session=False)`.
- `RunsRepo.mark_answered(id, channel, at) -> bool`, `Dispatcher.mark_answered(run_id, channel) -> bool`(primary에, 처음이면 `TelegramSender.clear_buttons(message_id)`, 안 되면 `buttons_clear_error` 로그만. 15가 원장을 같은 트랜잭션에).
- `harness/checkins.py run_answered_by(req, *, runs, tasks, settings, now) -> int | None`(6.4.5 "답으로 치는 것", `apply_action`이 적용 뒤 부름).
- `DeliveriesRepo.record(..., telegram_message_id=None)`, `.telegram_message_id(run_id)`, `.run_for_message(message_id)`. `TelegramSender.send(out) -> int | None`(버튼이 붙은 마지막 조각 id).
- `build_notices(..., elsewhere=None)` → `## 다른 곳에서 바뀐 것` 최대 5줄(`ActivityRepo.other_channel_since(after, channel, limit=5)`, 기준은 그 대화의 `last_message_at`).
- `FakeSender.cleared`, `async clear_buttons(message_id)`.

**Slices** (날짜는 10/26(월))
- [ ] `test_telegram_chat_and_app_chat_do_not_continue`, `test_plan_is_per_channel_but_runs_wait_for_any`(앱 `/plan` 동안 17:30 회차 대기)
- [ ] `test_run_reply_from_other_channel_forks`(FakeBrain `session_id="s-run"`, `fork_session=True`, 두 번째 앱 답은 `False`), `test_fork_failure_falls_back_with_outbound_text`
- [ ] `test_checkin_id_within_window_targets_run`, `test_checkin_id_outside_window_falls_through_to_rule_2`, `test_other_channel_notice_max_5_lines`
- [ ] `test_answered_once_first_channel_wins`, `test_answer_clears_telegram_buttons`, `test_condition_action_answers_evening_checkin`, `test_draft_button_answers_its_run`, `test_late_reply_by_sent_at`(03:50에 보낸 답을 05:00에 받음)
- [ ] `test_chat_activity_ids_are_undoable`: 앱 스트림의 `data-activity.undo_ids`로 `/activity/{id}/undo` → 200(05와 06이 만나는 자리)
- [ ] `test_checkin_detail_conversation_ids_per_channel`, `test_states_pending_answered_missed_by_sent_time`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_answer_from_app_closes_telegram`: 10/26(월) 17:30 `env.tick()` → 텔레그램 체크인 → 18:00 `POST /chat {checkin_id}` → `GET /checkins/{id}` `answered`/`app`, `FakeSender.cleared`에 그 메시지, FakeBrain 두 번째 호출 `fork_session=True`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: per-channel conversations, run forking and answered check-ins`
---

### 티켓 08: 웹 푸시와 회차 전달 (D1~D8)

**목표:** 7.3 D1~D8: 주 통로와 유효한 구독에 따라 회차를 푸시 또는 텔레그램으로, 모두 안 되면 텔레그램 대체, 404/410은 끈다. `/push/*`, `/settings/notify`, `gen-vapid`.
**막는 티켓:** 07
**라벨:** `ready-for-agent`

**Files:**
- Create: `harness/delivery.py`, `api/push.py`
- Modify: `config.py`, `cli.py`, `harness/dispatcher.py`(`_send_run`, `_resend_run`, `_send_notice`), `store/repos/{push,channels}.py`, `api/{health,server,models}.py`, `tools/actions.py`, `app.py`, `pyproject.toml`, `requirements.lock`, `.env.example`, `tests/fakes.py`
- Test: `tests/test_delivery.py`, `tests/test_api_push.py`

**Interfaces**
- Consumes: `_run_delivered`, `send_with_retry`, `DeliveriesRepo.record`, `ConversationsRepo.set_channel`, `apply_action` (SP1, 01, 07)
- Produces:
- `VapidConfig(public_key, private_key: SecretStr, subject)`, `Settings.vapid | None`(셋 다 있을 때만), `cli.py gen-vapid`.
- `PushRepo`: `PushSubscription(...)`(5.3 열), `upsert(endpoint, p256dh, auth, label) -> int`, `delete(id) -> bool`, `active()`, `record_ok(id, at)`, `record_failure(id, *, gone, at)`(5회면 끔).
- `harness/delivery.py`: `PushSender`(Protocol, 동기 `send(sub, payload, *, ttl, topic) -> int`), `WebPushSender`, `effective_channel(primary, active_subscriptions, push_enabled)`, `push_payload(run, text, *, reply_until) -> (dict, ttl, topic)`(6.4.8, 부록 A 제목, `topic = "run-<id>"`), `notice_payload(text)`, `DeliveryOutcome(channel, mode, sent, telegram_message_id, push_ok, push_failed)`, `Delivery(*, telegram, push, pushes, state, clock, settings, sleep, to_thread=asyncio.to_thread)`: `effective()`, `async deliver_run(run, out, *, reply_until)`(D2~D4, 보내기는 `to_thread`, 기록은 루프 스레드), `async deliver_notice(text)`(D8), `async push_test() -> (ok, failed)`.
- `Dispatcher(..., delivery=None)`: `_send_run`이 `deliver_run` + `DeliveriesRepo.record` + D5 `set_channel`. D6·D7은 스펙 그대로.
- `ACTIONS`(내부, 되돌릴 수 없음): `push_subscribe`, `push_unsubscribe`, `notify_set`, `push_test_result`. `summary`·로그에 `endpoint` 없음.
- `api/push.py`: 6.4.8~6.4.9 그대로. VAPID가 없으면 `/push/*`는 `404`, 실제 통로는 `telegram`.
- `FakePushSender(results: dict[str, list[int | Exception]])`, `.sent`.

**Slices**
- [ ] `test_default_app_without_subscription_goes_telegram`(D1a), `test_primary_telegram_full_telegram_no_push`(D2), `test_primary_app_push_ok_no_telegram`(D3, 토 10:00 회차, `title == "아침 브리핑"`, TTL = 창 끝까지 초, `run_deliveries` `app`/`full`/`sent`)
- [ ] `test_all_push_fail_falls_back_to_telegram`(D4), `test_404_410_disable_without_retry`, `test_five_consecutive_failures_disable_then_next_run_starts_telegram`
- [ ] `test_proactive_counter_once_per_run`(D6), `test_resend_after_5_minutes_only_if_nothing_delivered`(D7), `test_run_conversation_channel_follows_full_body`(D5), `test_notice_goes_to_effective_channel_and_safe_mode_telegram_only`(D8), `test_paused_runs_silent_on_both_channels`
- [ ] `test_vapid_public_key`, `test_subscribe_same_endpoint_same_id`, `test_delete_subscription_204_then_404`, `test_push_test_not_counted_in_daily_cap`, `test_settings_notify_get_put_effective`, `test_push_routes_404_without_vapid`, `test_push_endpoint_never_logged_or_in_activity`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_push_delivery_and_fallback`: 10/24(토) 구독 → 10:00 tick → 푸시 1, 텔레그램 0, `proactive.sent_today == 1`, `delivered_via == ["app"]` → 구독을 410으로 → 18:00 tick → 텔레그램, 구독 꺼짐 → 10/25(일) 10:00 tick은 처음부터 텔레그램(`effective == "telegram"`). → `passed`

**마무리**
- [ ] `.env.example`에 `VAPID_*`. **Review + Commit** `feat: web push delivery with Telegram fallback and notify settings`
---

### 티켓 09: 앱 전용 두뇌 도구 — 화면 조각과 고정 카드

**목표:** 앱 대화의 두뇌만 `ui_todo_list`, `ui_choice`, `ui_summary_card`(그리기만)와 `pin_card`, `unpin_card`, `reorder_cards`를 쓴다(6.4.7, 10장). 하네스는 초안 카드와 컨디션 고르기를 `h_` 조각으로 붙인다. `GET /today`의 `cards`가 고정 카드를 지금 값으로 채운다.
**막는 티켓:** 06, 05
**라벨:** `ready-for-agent`

**Files:**
- Create: `store/repos/cards.py`, `harness/prompts/channel_app.md`(내용)
- Modify: `tools/{ui,core,mcp_adapter,actions,activity}.py`, `harness/stream.py`, `api/read.py`, `app.py`
- Test: `tests/test_ui_tools.py`, `tests/test_cards.py`

**Interfaces**
- Consumes: `UI_COMPONENTS`, `validate_props`, `call_tool`, `tool_names_for`, `UiMessageWriter`, `todo_dict`, `register_undo` (02, 05, 06)
- Produces:
- `Tools.ui_todo_list(ctx, title, task_ids)`, `Tools.ui_choice(ctx, question, options)`, `Tools.ui_summary_card(ctx, title, lines)`: `validate_props`면 `{"ok": true}`, 아니면 `{"error"}`. DB·파일·`ctx.events`를 건드리지 않는다.
- `CardsRepo(conn, clock)`: `Card(id, component, props, sort_order, pinned_at, unpinned_at, conversation_id)`, `pin`, `unpin`, `reorder(ids)`(전부가 아니면 `ValueError`), `active()`, `restore(card)`, `restore_order(order)`.
- `Tools.pin_card`, `unpin_card`, `reorder_cards`: 활동 `card_pinned`·`card_unpinned`·`cards_reordered`(대상 `card:<id>`, `cards:order`), `/actions`에도, `register_undo` 셋.
- `APP_ONLY_TOOLS`(여섯), `tool_names_for("app") == TOOL_NAMES + APP_ONLY_TOOLS`.
- 하네스 조각(`AppReplySender`): `out.draft_task_ids` → `h_draft_<n>` `ui_todo_draft {task_ids}` + `{"ok": true}`, `out.ask_condition_for` → `h_cond_<n>` `ui_condition_picker`. `n`은 그 답의 순번.
- `/today.cards`: `active()` 순서대로, `props.task_ids`가 있으면 `data.todos`(초안·삭제 뺌).
- `channel_app.md`: 화면 도구는 보기 좋을 때만, 글로도 같은 뜻을 말한다, 카드 고정은 사용자가 원할 때만(한 단락).

**Slices**
- [ ] `test_ui_tools_do_not_touch_db_or_files`(DB 해시와 `data/` 파일 목록·해시가 같다)
- [ ] `test_ui_schema_error_is_tool_error_and_no_component_chunk`(선택지 5개)
- [ ] `test_ui_and_card_tools_absent_from_telegram`, `test_app_prompt_includes_channel_app_only_for_app`
- [ ] `test_harness_chunks_have_h_prefix`: 앱 대화 `propose_tasks` → `h_draft_1`
- [ ] `test_pin_card_validates_against_its_own_component`, `test_card_activity_actor_secretary_and_undo_each`, `test_reorder_requires_all_pinned_ids`, `test_today_cards_filled_with_current_task_data`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_pin_card_from_app_chat`: `POST /chat` → FakeBrain(앱) `ui_todo_list` + `pin_card` → 스트림에 `ui_todo_list` 조각, `GET /today.cards[0]`와 `data` → `card_pinned` 되돌리기 → `cards == []`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: app-only UI component tools and pinned cards`

---

### 티켓 10: 회차 차례의 확인 (10.1)

**목표:** 회차 실행 호출(A1)에서 비서가 꺼낸 `drop_task`, `set_priorities`, 일정 시각을 바꾸는 `update_task`, 시각 있는 할 일의 `move_task`는 확인 토큰만 만든다(A2). 앱 `ui_confirm` 조각과 텔레그램 `k:` 버튼(A5). 사용자 메시지에 답하는 차례는 SP1 그대로(A3).
**막는 티켓:** 09
**라벨:** `ready-for-agent`

**Files:**
- Modify: `domain.py`, `tools/{core,actions}.py`, `harness/{dispatcher,stream,checkins}.py`, `bot/{telegram_io,callbacks}.py`, `harness/prompts/system.md`
- Test: `tests/test_run_turn_confirm.py`

**Interfaces**
- Consumes: `ConfirmsRepo`, `apply_action` 토큰 경로, `UiMessageWriter`, `reply_window_end`, `checkin_cards` (04, 06, 09)
- Produces:
- `RunContext.run_turn -> bool`(`run_id is not None and inbound_id is None`)
- `Tools(..., confirms=None, reply_until: Callable[[int], datetime] | None = None)`, `_request_confirm(ctx, action, args, summary) -> dict`(`origin="run_turn"`, 만료 = 답장 창 끝, ToolEvent·활동 `confirm_requested`, 결과 `{"status": "needs_confirm", "confirm_token", "summary"}`). `add_task`는 언제나 바로(A4).
- `Outbound.confirms: list[tuple[str, str]]`, `confirm_keyboard(confirms)`(`✓ 확인: {summary 16자}` `k:a:<token>`, `✗ 그대로 두기` `k:x:<token>`), 줄 순서: 초안 → 확인 → 컨디션.
- `bot/callbacks.py`: `k:a` → 토큰의 `action`·`args`로 `apply_action(confirm_token=…)`, `k:x` → `decline_confirm`, 정리된 토큰 → "이미 정리된 제안이에요."
- 앱: `confirm_requested`마다 `h_confirm_<n>` `ui_confirm {summary, confirm_token, action, args}`, `checkin_cards`도 열린 토큰마다.
- `system.md` 원칙 12(A7).

**Slices** (`tests/test_run_turn_confirm.py`)
- [ ] `test_run_turn_detection_both_channels`, `test_run_turn_tools_need_confirm`(매개변수), `test_move_task_without_schedule_applies_in_run_turn`, `test_add_task_applies_in_run_turn`
- [ ] `test_sp1_user_turn_behavior_unchanged`: `python -m pytest tests/test_tools_tasks.py tests/test_dispatcher_tools.py -q` → `0 failed`
- [ ] `test_confirm_card_and_telegram_buttons`(64바이트 이하, `h_confirm_1`), `test_confirm_applies_with_activity_and_decline_changes_nothing`, `test_double_press_expired_or_stale_not_applied`, `test_token_survives_restart`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_morning_brief_proposal_needs_confirm`: 10/26(월) 09:00 tick, FakeBrain(회차) `set_priorities(day, …)` → 그대로, `GET /checkins/{id}.cards`에 `ui_confirm` → 그 값으로 `POST /actions` → 바뀜, 활동 `actor == "user"`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: confirmation for secretary-initiated changes in run turns`

---

### 티켓 11: 인생 곡선 데이터 계층

**목표:** 곡선 쓰기와 곡선 도구 함수(사다리, 영역 점수, 사건·챕터 확정과 빼기)를 만들고 `/actions`·되돌리기에 잇는다. 초안은 빼거나 3일 뒤 **행 삭제**, 고점·전환점 확정은 칭호, 확정 되돌림은 칭호 삭제, 바뀔 때마다 `data/curve/chapters.md`.
**막는 티켓:** 03, 05, 21b(문구 C1~C4)
**라벨:** `ready-for-agent`

**Files:** Modify `store/repos/{curve,status}.py`, `store/exports.py`, `tools/{core,confirmations,actions,activity}.py`, `loop/runner.py`, `app.py`. Test `tests/test_curve_actions.py`, `tests/test_curve_drafts.py`

**Interfaces**
- Consumes: `CurveRepo` 읽기(03), `ActivityRepo`, `register_undo`, `apply_action`, `transaction(conn)` (01, 04, 05)
- Produces:
- `CurveRepo` 쓰기: `add_chapter(*, title, start_month, status, origin, end_month=None, theme=None, sketch=None, certainty="fact", seed_key=None, source_ref=None)`, `add_milestone(*, date_text, kind, title, status, origin, note=None, chapter_id=None, sensitive=False, certainty="fact", kind_certainty="fact", conversation_id=None, source_ref=None)`(`precision`·`sort_date`는 `date_text`에서), `confirm_milestones(ids)`, `confirm_chapters(ids)`, `unconfirm_milestone(id, at)`, `unconfirm_chapter(id, at)`, `delete_milestone_draft(id) -> bool`, `delete_chapter_draft(id) -> bool`, `expire_drafts(older_than)`, `set_ladder(period, *, now, future, note)`, `restore_ladder(period, before)`, `set_area_scores(period, scores, *, notes, quests)`, `restore_area_scores(period, before)`, `set_area_default`, `add_question`, `next_open_question`, `mark_question`
- `StatusRepo.add_title(milestone_id, at)`, `.remove_title(milestone_id)`(원장 쓰기는 15).
- `Tools(..., curve=None, status=None, review_date_for: Callable[[RunContext], date | None] | None = None)`: `record_ladder_score(ctx, period=None, now=None, future=None, note=None)`, `record_area_scores(ctx, scores, period=None, notes=None, recovery_quests=None)`, `confirm_milestones(ctx, ids)`, `confirm_chapters(ctx, ids)`, `drop_curve_drafts(ctx, milestone_ids=None, chapter_ids=None)`. 검증과 기간 기본값은 10장, 바뀐 뒤 `export_curve(curve, path)`(민감은 "(민감)").
- `confirmation_line`: 사건 확정·빼기·칭호는 부록 A, 영역 점수·챕터 확정·챕터 빼기·도구 사다리는 C1~C4.
- `ACTIONS`: `record_ladder_score`, `record_area_scores`, `confirm_milestones`, `confirm_chapters`, `drop_milestone`, `drop_chapter`, 내부 `expire_curve_drafts`. `register_undo`: `ladder_recorded`, `area_scores_recorded`, `milestones_confirmed`, `chapters_confirmed`(초안으로, `draft_since` = 되돌린 시각, 칭호 삭제). 빼기는 되돌릴 수 없다. 대상 `ladder:<YYYY-MM>`, `areas:<YYYY-Qn>`, `milestone:<id>`, `chapter:<id>`. 러너가 하루 한 번 `expire_curve_drafts`.

**Slices**
- [ ] `test_ladder_future_only_first_then_now_keeps_future`, `test_ladder_range_and_future_month_rejected`, `test_area_scores_range_names_and_quests_only_for_down`
- [ ] `test_confirm_high_and_turning_grant_titles_low_does_not`, `test_drop_milestone_deletes_row_and_confirmed_is_rejected`, `test_dropping_chapter_draft_nulls_milestone_chapter_id`
- [ ] `test_undo_ladder_and_areas_restore_or_delete`, `test_undo_confirm_resets_draft_since_and_removes_title`
- [ ] `test_period_default_from_review_conversation`: 11/29(일) 회고를 R1로 12/1에 보낸 넘겨 받은 회고의 회차 대화에서 `record_ladder_score(now=7)` → `"2026-11"`, 일반 대화면 `"2026-12"`
- [ ] `test_export_chapters_md_masks_sensitive`, `test_confirmation_lines`(부록 A와 C1~C4, 금지어 없음), `test_curve_drafts_deleted_after_3_days_by_draft_since`, `test_drafts_not_in_get_curve_until_confirmed`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_curve_write_path`: 초안(`high`) → `/curve`에 없음 → `POST /actions confirm_milestones` → 있음, `/status.titles`에 `「…」의 순간` → 되돌리기 → 둘 다 없음 → `clock.advance(days=3)` + tick → 행 삭제. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(curve): curve data layer, draft deletion, titles and curve actions`
---

### 티켓 12: `seed-life` 시드 가져오기

**목표:** `python -m my_planner seed-life <파일> [--dry-run]`이 12장 형식의 검토한 시드에서 챕터, 사건, 영역 기본 퀘스트, 질문을 한 트랜잭션으로 가져온다. 잠금, 한 번만, 내용 출력 없음.
**막는 티켓:** 11
**라벨:** `ready-for-agent`

**Files:**
- Create: `curve/seed.py`, `tests/fixtures/life_seed_example.json`(꾸며 낸 내용: 챕터 3, 사건 8 — 민감 미확인 1, `storage` 미확인 1, 날짜 오류 1 — 영역 6, 질문 2)
- Modify: `cli.py`, `.gitignore`(세 패턴 확인)
- Test: `tests/test_seed_life.py`

**Interfaces**
- Consumes: `CurveRepo` 쓰기, `StatusRepo.add_title`, `export_curve`, `SingleInstanceLock`, `open_db`, `migrate`, `transaction(conn)` (01, 11)
- Produces:
- `EXIT_OK = 0`, `EXIT_RUNNING = 3`, `EXIT_ALREADY = 4`, `EXIT_NOT_REVIEWED = 5`, `EXIT_BAD_FILE = 6`(빈 곳 5)
- `SkipReason = Literal["sensitive_unconfirmed", "storage_unconfirmed", "invalid"]`
- `load_seed(path) -> dict`(`utf-8-sig`), `SeedPlan(chapters, events, quests, sketches, questions, skipped: Counter[SkipReason])`, `plan_import(seed) -> SeedPlan`(순수, 12장 규칙: 확인 규칙, `certainty`·`kind` 옮기기, 오류는 `invalid`, 건너뛴 챕터를 가리키는 사건은 `chapter_id=None`, 점수·`ladder`는 읽지 않음), `apply_seed(conn, plan, clock) -> dict[str, int]`(한 트랜잭션, 모두 `confirmed`/`seed`, 칭호, 경험치 없음, `life_seed_imported_at`)
- `run_seed_life(root, file, *, dry_run, out, lock_factory=SingleInstanceLock) -> int`: 출력은 개수만 — `가져올 것: 챕터 {n}, 사건 {n}, 영역 퀘스트 {n}, 질문 {n}` / `건너뛸 것: {합} (sensitive_unconfirmed {n}, storage_unconfirmed {n}, invalid {n})` / `가져왔어요.` 또는 `--dry-run: 아무것도 쓰지 않았어요.`

**Slices** (`tests/test_seed_life.py`)
- [ ] `test_not_reviewed_imports_nothing_code_5`, `test_sensitive_and_storage_only_when_confirmed`, `test_scores_and_ladder_not_imported`
- [ ] `test_turning_maps_to_turning_point_and_certainty_mapping`, `test_skipped_chapter_nulls_event_chapter_id`, `test_titles_for_high_and_turning_no_xp`, `test_questions_are_open`, `test_sketch_goes_to_chapter`
- [ ] `test_second_run_code_4`, `test_running_be_code_3_with_message`(부록 A 문구 그대로), `test_second_instance_real_lock`(Windows 전용)
- [ ] `test_dry_run_counts_only_no_content`: 고정 자료의 모든 `title`·`note`가 출력에 없고 DB 그대로
- [ ] `test_bom_file_reads`, `test_invalid_items_counted_not_printed`(`2019-13`, `kind: "peak"` → `invalid 2`), `test_not_json_code_6` (Review Focus 4)

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_seed_then_curve`: `run_seed_life(root, fixture, dry_run=False)` → 같은 루트로 `BeEnv` → `GET /curve?zoom=year`에 챕터 3·사건(민감 제외), `include_sensitive=true`에 확인된 민감 사건, `GET /status.titles` 개수 = 고점+전환점, `ladder == []`. → `passed`

**마무리**
- [ ] `python -m my_planner seed-life --help` 출력 확인(README 순서는 19).
- [ ] **Review + Commit** `feat(curve): seed-life import CLI`

---

### 티켓 13: 곡선·상태 두뇌 도구와 사건 초안 버튼·카드

**목표:** 두뇌가 10장의 곡선·상태 도구를 쓴다(`grant_xp`는 15). 대화에서 꺼낸 사건·챕터는 초안이고, 텔레그램 답 아래 부록 A 버튼, 앱에는 `ui_milestone_draft`·`ui_chapter_draft` 하네스 조각(빈 곳 7). 자연어 확정·빼기. `system.md` 원칙 9~11.
**막는 티켓:** 11, 09
**라벨:** `ready-for-agent`

**Files:** Modify `tools/{core,mcp_adapter}.py`, `harness/{dispatcher,stream,checkins}.py`, `bot/{telegram_io,callbacks}.py`, `harness/prompts/system.md`, `app.py`. Test `tests/test_curve_tools.py`, `tests/test_telegram_curve.py`, `tests/test_app_curve_cards.py`, `tests/test_prompts.py`(SP1 금지어 시험 그대로)

**Interfaces**
- Consumes: 11의 곡선 메서드, `curve_view`, `status_snapshot`, `apply_action`, `message_keyboard`, `AppReplySender` 하네스 조각 경로 (03, 04, 09, 11)
- Produces:
- `Tools.add_milestone(ctx, date, kind, title, note=None, chapter_id=None, sensitive=False)`(초안, `milestone_proposed`), `Tools.propose_chapter(ctx, title, start, theme=None, end=None)`(`chapter_proposed`), `Tools.get_curve(ctx, from_=None, to=None, zoom="month")`(민감은 `"(민감)"`, `note` 없음), `Tools.get_status(ctx)`. `TOOL_NAMES`에 9개.
- `_handler`: 도구 스키마의 키는 `from`이고, 호출 전에 `args["from"]`을 `from_`으로 바꾼다(`method(ctx, **args)`가 깨지지 않게).
- `Outbound.draft_milestone_ids`, `draft_chapter_ids`. 앱 조각 `h_mdraft_<n>` `ui_milestone_draft {milestone_ids}`, `h_cdraft_<n>` `ui_chapter_draft {chapter_ids}`, `checkin_cards`도 남은 초안을. 순서는 텔레그램 줄과 같다(할 일 → 사건 → 챕터 → 컨디션).
- `milestone_keyboard(ids, conversation_id, titles)`(`m:c:<id>`, `m:x:<id>`, `m:all:<대화 id>`), `chapter_keyboard(ids, titles)`(`h:c:<id>`, `h:x:<id>`).
- `bot/callbacks.py`: `m:`·`h:` → `apply_action`. 정리된 사건은 부록 A "이미 정리된 사건이에요.", 챕터는 C3 비고. 원문 기록 `[버튼] 저장: {제목}`, `[버튼] 빼기: {제목}`.

**Slices**
- [ ] `test_add_milestone_is_draft_not_in_curve`, `test_milestone_date_precision_and_sort_date`(`2023-5` → 오류), `test_sensitive_default_false`, `test_get_curve_from_key_maps_to_from_`(MCP 핸들러에 `{"from": "2026-01-01"}`)
- [ ] `test_confirm_milestones_by_natural_language`, `test_drop_curve_drafts_rejects_confirmed`, `test_get_curve_masks_sensitive_title`, `test_get_status_equals_snapshot`, `test_telegram_tool_count_21_before_grant_xp`
- [ ] `test_milestone_buttons_layout_and_64_bytes`, `test_m_all_confirms_only_this_conversation_drafts`, `test_stale_milestone_button_reply`, `test_button_reply_copy`(부록 A: "✓ 저장: 제주 여행 (2019, 고점)", "칭호: 「제주 여행」의 순간", "✗ 뺐어요: 제주 여행"), `test_chapter_buttons`, `test_system_prompt_has_principles_9_to_11`
- [ ] `test_app_milestone_draft_chunk`, `test_app_chapter_draft_chunk_after_milestone`, `test_checkin_cards_include_curve_drafts_until_confirmed`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_story_to_curve`: `env.telegram("예전에 처음 혼자 제주 여행 갔을 때 정말 좋았어")`(꾸며 낸 문장) → FakeBrain `add_milestone(date="2019", kind="high", title="제주 여행")` → `env.press("m:c:<id>")` → `/curve?zoom=year`에 사건, `/status` 칭호. 3일 뒤 남은 다른 초안은 사라진다. → `passed`

**마무리**
- [ ] **Review + Commit** `feat(curve): curve and status brain tools with milestone draft buttons and cards`
---

### 티켓 14: 회고 단계 — 월말 사다리, 분기 영역 점수, 연말

**목표:** 11.1~11.2: `review(week)`가 그 달 마지막 일요일이면 사다리, 분기 마지막 달이면 영역 점수, 12월이면 올해 돌아보기를 차례로 묻는다. 새 회차 종류 없음, 한 메시지에 질문 하나·키보드 한 종류.
**막는 티켓:** 13, 07, 21b
**라벨:** `ready-for-agent`

**Files:** Create `harness/review_steps.py`, `harness/prompts/review_{month,quarter,year}.md`. Modify `harness/{dispatcher,checkins}.py`, `bot/{telegram_io,callbacks}.py`, `store/reviews.py`, `tools/core.py`(`review_date_for`), `app.py`. Test `tests/test_review_steps.py`, `tests/test_telegram_ladder.py`

**Interfaces**
- Consumes: `record_ladder_score`, `record_area_scores`, `CurveRepo.next_open_question`, `save_weekly_review`, `mark_answered`, `run_answered_by`, `apply_action` (07, 11, 13)
- Produces:
- `ReviewSteps(month, quarter, year)`, `review_steps(d) -> ReviewSteps`(판정은 회고 회차 `scheduled_for`의 논리적 날짜). 프롬프트는 `review_week.md` 뒤에 해당하는 것을 차례로, 월말만이면 열린 시드 질문 하나를 `## 이번에 물을 질문`으로.
- `ladder_keyboard(period, field: Literal["n", "f"])`(`0`~`5`, `6`~`10`, `f`면 `건너뛰기`. 콜백 `l:<YYYY-MM>:n:<v>`, `l:<YYYY-MM>:f:<v>`, `l:<YYYY-MM>:f:skip`).
- 1단계 자리(11.1-1, 빈 곳 12): (a) 회고 묶음의 컨디션 누름은 토스트 대신 **새 메시지** "컨디션 {N} 기록했어요.\n\n{부록 A 사다리 1단계}" + `n` 키보드 (b) 컨디션 버튼 없이 회고 대화의 첫 사용자 글 답에 `Outbound.ladder: tuple[str, Literal["n", "f"]] | None` (c) 그 날짜 컨디션이 이미 있으면 회고 메시지에 바로. 회차마다 한 번(`app_state.ladder_prompted_run_id`). 그 달 사다리 `now`가 이미 있으면 묻지 않는다(빈 곳 14).
- 2·3단계 문구는 부록 A(사다리 2단계, 사다리 기록과 건너뛴 경우, 영역 점수 묻기). 하루 3회에 세지 않고, 답장 창 뒤 누름은 기록만.
- `run_answered_by`: `record_ladder_score(period)` → 그 달 월말 회고 회차. `save_weekly_review(..., included=None)`: `포함: 월간(2026-10), 분기(2026-Q4)` 한 줄.
- 앱: `checkin_cards`가 월말 회고에 `ui_ladder_picker {period, field}`, 분기 회고에 `ui_area_scores {period, previous}`.

**Slices**
- [ ] `test_last_sunday_in_five_sunday_month`(11/29 → month, 11/22 → 없음), `test_1227_month_quarter_year_overlap`, `test_carried_review_uses_original_date`, `test_prompts_appended_in_order`, `test_review_file_includes_line`
- [ ] `test_review_message_has_condition_row_not_ladder`, `test_condition_press_on_review_sends_ladder_step1_message`, `test_first_text_reply_gets_step1_when_no_condition_button`, `test_condition_already_recorded_step1_on_review_message`, `test_one_keyboard_kind_per_message`
- [ ] `test_now_then_future_then_recorded_copy`, `test_skip_future_copy`: 부록 A("기록했어요: 지금 6, 5년 뒤 8", 건너뛰면 "기록했어요: 지금 6")
- [ ] `test_ladder_already_recorded_this_month_not_asked`(빈 곳 14), `test_quarter_area_prompt_with_previous_scores`, `test_late_button_after_window_records_without_next_step`, `test_late_skipped_review_next_review_does_not_ask_twice`
- [ ] `test_ladder_button_at_0130_records_button_month` (Review Focus 5), `test_ladder_press_marks_review_answered`, `test_app_checkin_cards_ladder_and_area`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_month_end_review_ladder`: 2026-11-29(일) 18:00 tick → 회고+저녁 체크인 한 메시지(컨디션 줄만) → `env.press("c:2026-11-29:4")` → 1단계 → `l:2026-11:n:6` → 2단계 → `l:2026-11:f:8` → "기록했어요: 지금 6, 5년 뒤 8" → `/curve.ladder`에 `{"period": "2026-11", "now": 6, "future": 8}`, `/checkins/{id}` `answered`. → `passed`

**마무리**
- [ ] **Review + Commit** `feat: monthly ladder, quarterly area scores and year-end review steps`
---

### 티켓 15: 경험치, 레벨, `/status`, 쓰기 경로 감시

**목표:** 9.1 X1~X10이 같은 트랜잭션에서 원장에 쌓이고(오르기만), 레벨이 오르면 부록 A "레벨 {N}이 됐어요.". 텔레그램 `/status`(11.4)와 `GET /status`가 같은 숫자. 쓰기 경로 감시와 로그 검사로 BE를 마무리한다.
**막는 티켓:** 14, 08, 10
**라벨:** `ready-for-agent`

**Files:** Modify `store/repos/status.py`, `tools/{core,confirmations,actions,mcp_adapter}.py`, `harness/dispatcher.py`, `loop/runner.py`, `bot/{commands,telegram_io}.py`, `store/db.py`. Test `tests/test_status_{xp,property,command}.py`, `tests/test_write_paths.py`, `tests/test_api_logging.py`, `tests/test_brain_options.py`

**Interfaces**
- Consumes: `status/xp.py`(03), 변경 도구, `mark_answered`(07), `review_steps`(14), `status_snapshot`(03), `transaction(conn)`(01)
- Produces:
- `StatusRepo.grant(*, at, logical_date, source_kind, source_ref, amount, label, area=None) -> bool`(`ON CONFLICT DO NOTHING`, UPDATE·DELETE 함수 없음), `count_secretary_on(d)`.
- 쌓는 자리는 9.1·4.3 표 그대로: X1/X2 `complete_task`(완료 순간 가장 큰 주기), X4, X6, X7은 그 도구, X3/X5/X8은 `Dispatcher.mark_answered`(`answered_at`과 한 `transaction(conn)`), X9는 하루 한 번 `apply_action(grant_rest_days)`, X10 `Tools.grant_xp(ctx, amount, reason)`(22/28개).
- `level_up_line(before, after) -> str`: 텔레그램 확인 문구 끝, `h-confirm` 끝, `/actions`의 `xp`·`confirmation`.
- `status_text(snapshot) -> str`(11.4, 빈 스탯은 부록 A, 칭호는 첫 하나 + "외 {n}개"), `/status`, `HELP_TEXT` 줄(`run_command`라 앱도 같다).
- `open_db(path, *, on_write: Callable[[str], None] | None = None)`(`set_trace_callback`, 시험 이음매).

**Slices**
- [ ] `test_xp_table_x1_to_x10`(매개변수 10), `test_x2_biggest_cadence_at_completion`, `test_recomplete_after_undo_does_not_double`(U6), `test_x5_once_for_bundle_and_x8_on_1227`
- [ ] `test_mark_answered_and_ledger_atomic`: `grant`에서 예외 → `answered_at` NULL, 원장 0행
- [ ] `test_rest_days_rules`, `test_task_done_at_0130_counts_previous_day_so_no_rest_day` (Review Focus 5), `test_grant_xp_amounts_reason_and_daily_cap`
- [ ] `test_level_up_line_once`(140 → 150 넘김, `xp.level_up == 2`), `test_ledger_has_no_update_delete_functions`, `test_xp_and_level_never_decrease`(`hypothesis`, 200회, 완료 조건 8)
- [ ] `test_status_text_format`, `test_status_command_and_api_same_numbers`, `test_status_empty_stats_copy`, `test_help_lists_status`, `test_tool_counts_22_and_28`(S12)
- [ ] `test_each_table_written_only_by_its_path`: `on_write`의 문마다 표 이름과 **`my_planner.store` 밖의 첫 `my_planner` 프레임**의 모듈을 4.3 표의 허용 집합과 비교. 집합은 `tests/test_write_paths.py`의 `ALLOWED: dict[str, set[str]]`(표 → 모듈)에 4.3 표의 줄마다 모두 적는다. 예: `my_planner.tools.*`, `my_planner.harness.dispatcher`, `my_planner.harness.conversations`(`conversations`), `my_planner.harness.checkins`, `my_planner.harness.delivery`, `my_planner.api.chat`(`inbound_pending`만), `my_planner.loop.*`·`my_planner.app`(운영 상태, `app_state`), `my_planner.curve.seed`(`curve_*`, `status_titles`, `app_state.life_seed_imported_at`. 잠금을 잡은 별도 프로세스, 4.3·12장). 시나리오: 01~14 수용 흐름과 `run_seed_life`. `my_planner.api.read`의 쓰기는 0
- [ ] `test_full_scenario_logs_have_no_secrets`: 시험 토큰, "비밀 문장 7f3a", 할 일 제목, 도구 인자 값, 푸시 endpoint가 로그에 없다

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `tests/test_api_e2e.py::test_week_of_xp`: `start=kst(2026, 10, 26, 8, 0)`. 10/26(월)~11/1(일) 날마다 13:00 `POST /actions complete_task` 3회(우선순위 아닌 할 일), 18:30 `env.telegram("오늘 괜찮았어")`로 저녁 체크인 답, `env.press("c:<날짜>:4")`. 11/1은 저녁 체크인과 주간 회고가 한 묶음. 기대: `xp_total == 305`(= 6 × (30 + 5 + 5) + (30 + 30 + 5)), `level == 2`, 원장 합 == `xp_total`, 텔레그램 `/status`와 같은 숫자. 11/2(월)는 아무것도 하지 않고 11/3 tick 뒤 `recent_xp[0]`이 `+5 쉬는 날`, `xp_total == 310`. → `passed`
- [ ] BE 전체 `python -m pytest -q`와 16장 묶음 명령 모두 `0 failed`.

**마무리**
- [ ] **Review + Commit** `feat(status): XP ledger rules, level-ups, /status and write-path audit`
---

### 티켓 16: 대시보드 뼈대와 (a) 비서 상태

**목표:** `web/dashboard/`에 정적 내보내기 대시보드. 설정 화면(BE URL과 토큰), 모든 화면 위 연결 띠(켜짐·꺼짐 10초·마지막 응답), 첫 화면 비서 상태(13.2). 디자인 토큰은 두 스킬로.
**막는 티켓:** 03
**라벨:** `ready-for-agent`

**Files:**
- Create: `web/dashboard/{package.json, package-lock.json, next.config.mjs, tsconfig.json, vercel.json, vitest.config.ts}`, `scripts/{check-csp,gen-types}.mjs`, `src/pages/{_app,_document,index,settings}.tsx`, `src/lib/{connection,api,time,polling,labels}.ts`, `src/components/{ConnectionBand,StateNotice,Nav}.tsx`, `src/screens/HealthScreen.tsx`, `src/styles/{tokens,globals}.css`, `src/api/{schema.json,types.gen.ts}`, `src/test/{server,handlers}.ts`, `src/test/fixtures/health*.json`
- Create (BE): `tests/dashboard_seed.py`, `tests/test_dashboard_fixtures.py`

**Interfaces**
- Consumes: `GET /health`(01), `python -m my_planner schema`(02), `BeEnv`(01)
- Produces:
- `next.config.mjs`: `output: "export"`, `trailingSlash: true`, `images.unoptimized`. Pages Router만, API 라우트·`getServerSideProps` 없음.
- `connection.ts`: `normalizeBeUrl(input, allowedPattern) -> {ok: true; url} | {ok: false; reason: "not_https" | "out_of_range" | "invalid"}`, `loadConnection`/`saveConnection`(`mp.connection`), `loadLastHealthOk`/`saveLastHealthOk`(`mp.lastHealthOk`), 모두 `try/catch`.
- `api.ts`: `ApiResult<T>`(`ok`, `offline`, `unauthorized`, `rate_limited`, `safe_mode`, `broken(code)`), `fetchApi<T>(conn, path, isT, opts?)`(10초 `AbortController`, 13.1 공통 상태 표대로), 손 검사기 `isHealth` 등.
- `polling.ts usePolling<T>(load, intervalMs = 60_000) -> {result, refresh}`(보이는 탭만, 다시 보이면 한 번, `unauthorized`면 멈춤). `time.ts formatKst(iso, style)`(`timeZone: "Asia/Seoul"`).
- `labels.ts`: 회차 이름(부록 A 푸시 제목), 상태(`done` 보냄, `pending`/`queued` 예정, `running` 보내는 중, `failed` 전송 안 됨, `skipped` `건너뜀({사유})`), 사유(빈 곳 10, `docs/acceptance/sp1-checklist.md`의 뜻을 줄임): `late` 한계 시각 지남, `merged_into_return` 복귀 인사로 합침, `paused` /pause 중, `daily_cap` 하루 두뇌 호출 상한, `auth` 로그인·결제 문제, `rate_limit` 사용 한도, 모르는 값은 `건너뜀`만.
- `ConnectionBand.tsx`, `StateNotice.tsx`, `HealthScreen.tsx`: 문구와 배치는 13.1·13.2 그대로.
- `_document.tsx`: `<head>`의 **첫 요소**로 CSP `<meta httpEquiv>`(빈 곳 3: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ${NEXT_PUBLIC_CONNECT_SRC}; base-uri 'none'; form-action 'none'`). `vercel.json`: `nosniff`, `no-referrer`, `frame-ancestors 'none'`, 최소 `Permissions-Policy`. 차트·리스트는 `next/dynamic(..., {ssr: false})`.
- `scripts/check-csp.mjs`: `out/**/*.html`마다 (1) `src` 없는 `<script>`(`application/json` 빼고), `<style>`, `style=` 0개 (2) CSP `<meta>`가 첫 `<script>`보다 앞. 출력 `CSP OK: 0 inline scripts, 0 inline styles, meta first`. `gen-types.mjs`: `schema.json` → `types.gen.ts`. 스크립트 `dev`, `build`, `test`, `gen:types`, `check:csp`, `typecheck`.
- BE `tests/dashboard_seed.py seed_dashboard_db(conn, clock) -> None`: 꾸며 낸 고정 자료를 **SQL로 바로** 넣는다(할 일·우선순위, 컨디션 30일 중 21일, 회차·전달, 챕터·사건·사다리·영역 점수, 원장·칭호). `tests/test_dashboard_fixtures.py`: 그 DB의 `BeEnv` GET 응답 == `src/test/fixtures/<이름>.json`, `schema.json == schema_bundle()`(`/health`의 `version.schema`는 `LATEST_VERSION`), `--update-dashboard-fixtures`면 다시 쓴다. 17·18은 행만 더한다.

**디자인 단계** (구현 전 한 번)
- [ ] UI UX Pro Max 스킬과 taste 스킬을 작업 세션에 불러온다(각 README의 설치 방법).
- [ ] 두 스킬로 정한다: 밝음·어두움 색 토큰, 글꼴(시스템 또는 `public/` 자체 글꼴), 간격·반경·그림자, 차트 모양, 360px 배치. 결과는 `tokens.css` 변수와 머리 주석 다섯 줄 이내.
- [ ] taste 스킬 점검 항목으로 13.2 시안을 한 번 고친다(같은 크기 카드 격자, 무의미한 그라데이션, 장식 이모지를 뺀다).

**Slices** (`cd web/dashboard && npx vitest run <파일> -t "<이름>"`)
- [ ] `connection.test.ts` `normalizes and rejects BE URLs` (Review Focus 3), `blocked localStorage returns null`
- [ ] `api.test.ts`(MSW): 401, 429, 503 `safe_mode`, 500 → `broken("internal")`, 필드 빠진 200 → `broken("shape")`, 10초 무응답·네트워크 오류 → `offline`
- [ ] `ConnectionBand.test.tsx`(`BE 꺼짐 · 마지막 응답 10/24 17:00`, 기록 없음), `polling.test.ts`, `HealthScreen.test.tsx`, `settings.test.tsx`
- [ ] `time.test.ts` `shows KST regardless of device time zone` (Review Focus 1): `TZ=UTC`·`America/Los_Angeles`에서 `formatKst("2026-10-24T08:00:05Z", "HH:mm:ss") === "17:00:05"`
- [ ] `labels.test.ts` `skip reason labels`: 여섯 사유 → `건너뜀(한계 시각 지남)` 꼴, 모르는 사유 → `건너뜀`, 키 == `schema.json`의 `SkipReason` enum
- [ ] `banned-words.test.ts`: `src/`에 "놓쳤어요", "밀렸어요", "늦었지만", "실패", "연속" 없음
- [ ] `check-csp.test.mjs`: 인라인 스크립트, `<script>` 뒤의 CSP `<meta>` → 실패 코드

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `python -m pytest tests/test_dashboard_fixtures.py -v` → `passed`
- [ ] `cd web/dashboard && npm ci && npm test && npm run typecheck` → `0 failed`, 코드 0
- [ ] `NEXT_PUBLIC_CONNECT_SRC="https://*.example.ts.net" npm run build` → `out/index.html`, `out/settings/index.html`, `.next/server/pages/api` 없음 → `npm run check:csp` → `CSP OK: 0 inline scripts, 0 inline styles, meta first`

**마무리**
- [ ] **Review + Commit** `feat(dashboard): static dashboard skeleton, connection band and assistant status screen`
---

### 티켓 17: 대시보드 (b) 할 일 + 컨디션, (d) 상태창

**목표:** 13.3(오늘·이번 주, 아침 브리핑 펼치기, 30일 컨디션 점)과 13.5(레벨, HP, 스탯, 디버프·회복 퀘스트, 퀘스트, 칭호, 최근 경험치). 읽기 전용, 체크 상자 없음.
**막는 티켓:** 16
**라벨:** `ready-for-agent`

**Files:**
- Create: `src/pages/{tasks,status}.tsx`, `src/screens/{TasksScreen,StatusScreen}.tsx`, `src/components/{TodoList,ConditionDots,StatBar,XpBar}.tsx`, `src/test/fixtures/{today,week,conditions,status}*.json`
- Modify: `tests/dashboard_seed.py`, `tests/test_dashboard_fixtures.py`

**Interfaces**
- Consumes: `fetchApi`, `usePolling`, `formatKst`, `StateNotice`, `ConnectionBand`(16), `GET /today`·`/week`·`/conditions`·`/status`(02, 03)
- Produces: `TasksScreen`(탭 `[오늘] [이번 주]`, 묶음 순서 그대로, 7칸, 문구는 13.3), `ConditionDots({items, from, to})`(빈 날은 점·선 없음, 머리 `평균 {a} · {n}일 기록`), `StatusScreen`(`XpBar`, HP, `StatBar`, 문구는 13.5). 연속·남은 시간·놓친 것 표시 없음.

**Slices**
- [ ] `TasksScreen.test.tsx`: `today order equals API groups`(`role="checkbox"` 0개), `week shows 7 day cells including empty`, `empty, offline, 401, 503, shape states`
- [ ] `ConditionDots.test.tsx` `gaps are not zero`
- [ ] `StatusScreen.test.tsx`: `renders snapshot`(`Lv. 6`, `130 / 400 XP`, `HP 4/5`, `↓ 디버프 (Q3 6)`), `empty states`, `no streak or countdown words`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `python -m pytest tests/test_dashboard_fixtures.py -v` → `passed`(`/today`, `/week`, `/conditions`, `/status` 고정 자료 == `seed_dashboard_db` DB의 `BeEnv` 응답)
- [ ] `cd web/dashboard && npm test && npm run build && npm run check:csp` → `0 failed`, `CSP OK: …`

**마무리**
- [ ] **Review + Commit** `feat(dashboard): tasks and conditions screen, status window screen`

---

### 티켓 18: 대시보드 (c) 인생곡선

**목표:** 13.4: 확대 다섯, 챕터 띠, 사다리(실선·점선), 컨디션 옅은 점, 사건 ▲▼◆(누르면 상세), 영역 레이더, 안심 보기(8.3).
**막는 티켓:** 16
**라벨:** `ready-for-agent`

**Files:**
- Create: `src/pages/curve.tsx`, `src/screens/CurveScreen.tsx`, `src/components/{CurveChart,AreaRadar,Reassurance,MilestonePopover}.tsx`, `src/lib/curveLayout.ts`, `src/test/fixtures/curve*.json`
- Modify: `tests/dashboard_seed.py`, `tests/test_dashboard_fixtures.py`

**Interfaces**
- Consumes: `fetchApi`, `usePolling`, `StateNotice`(16), `GET /curve`(03)
- Produces: `curveLayout.ts`(순수): `ladderSeries(ladder, from, to)`(15일 정오 KST, 빈 달 `null`), `milestoneX(date, precision)`, `conditionSeries(buckets)`(`(average − 1) × 2.5`), `chapterBands(chapters, from, to)`, `reassuranceCopy(gap)`(8.3 표). `CurveScreen`: 확대마다 `GET /curve?zoom=<z>`, "민감한 사건 보기"는 메모리에만(`localStorage` 안 씀), 빈 상태 13.4 넷. Recharts `ComposedChart`, `RadarChart`, `ssr: false`.

**Slices**
- [ ] `curveLayout.test.ts`: `ladder breaks on missing month`, `ladder point on the 15th`, `reassurance copy thresholds`(1.0, 0.99, −1.0, null)
- [ ] `CurveScreen.test.tsx`: `zoom buttons request each zoom`, `sensitive toggle refetches and is not persisted`, `milestone tap shows details`, `radar marks down vertex`, `four empty states`, `offline and 401 states`

**수용 확인 (가짜 두뇌 + 가짜 시계)**
- [ ] `python -m pytest tests/test_dashboard_fixtures.py -v` → `passed`(`/curve` 다섯 확대 고정 자료 == `seed_dashboard_db` DB의 `BeEnv` 응답)
- [ ] `cd web/dashboard && npm test && npm run build && npm run check:csp` → `0 failed`, `CSP OK: …`

**마무리**
- [ ] **Review + Commit** `feat(dashboard): life curve screen with zoom, radar and reassurance view`

---

### 티켓 19: Vercel 배포, Tailscale serve, 운영 안내

**목표:** 대시보드를 Vercel에, 노트북 BE를 `tailscale serve`로 tailnet에 열고, 폰과 노트북 브라우저에서 연결한다. README 운영 안내.
**막는 티켓:** 15, 17, 18
**라벨:** `needs-laptop`(Vercel 계정, tailnet 관리 화면, 노트북 `.env`)

**Files:** Modify `README.md`, `config.toml`(`cors_origins`, `cors_origin_regex`), 노트북 `.env`(커밋 안 함)

- [ ] tailnet: MagicDNS, HTTPS 인증서. 노트북: `gen-token` → `.env` `API_TOKEN`, `gen-vapid` → `VAPID_*`, `VAPID_SUBJECT=mailto:…`
- [ ] Vercel: 루트 `web/dashboard`, 빌드 `npm run build`, 출력 `out`, 환경 변수는 `NEXT_PUBLIC_CONNECT_SRC=https://*.<tailnet>.ts.net` 하나(토큰·BE URL 없음), 분석 끔
- [ ] `config.toml`: `cors_origins = ["https://<대시보드>.vercel.app", "https://<운영 앱>.vercel.app"]`, 미리보기는 팀 범위 정규식만. 다시 시작
- [ ] `tailscale serve --bg --https=443 http://127.0.0.1:8787` → `tailscale serve status`에 `(tailnet only)`, `tailscale funnel status` → 꺼짐
- [ ] 확인: `curl.exe -s -H "Authorization: Bearer $env:API_TOKEN" https://<노트북>.<tailnet>.ts.net/api/v1/health` → `"status":"ok"`, 토큰 없이 → `401`, `Origin: https://evil.vercel.app` → `Access-Control-Allow-Origin` 없음, 폰에서 설정 → "BE 켜짐", 화면 넷(PNA 권한 창은 S9 안내대로)
- [ ] 폰과 노트북 Chrome의 개발자 도구 콘솔에서 화면 넷을 차례로 열어 CSP 위반(`Refused to …`)이 0건
- [ ] README "API와 대시보드": 위 명령, Funnel 금지, 토큰 바꾸기, 시드 가져오기 순서 4단계(12장), PNA 안내(S9)
- [ ] **수용 확인**: 위 확인의 출력이 기대와 같고, `git status`에 `.env`, `data/`가 없다
- [ ] **Commit** `docs: deployment and operations guide for API and dashboard`

---

### 티켓 20: 노트북 수용 테스트

**목표:** 완료 조건 1, 2, 5, 9, 10을 노트북·폰·Tailscale로 확인하고 `docs/acceptance/sp3-4-checklist.md`에 남긴다. 5는 11/29와 12/27 회고에서.
**막는 티켓:** 19
**라벨:** `needs-laptop`

- [ ] `docs/acceptance/sp3-4-checklist.md`: 16장 "수동 수용 테스트" 표 + 아래, 단계마다 날짜·결과 칸.
  - 1: 화면 넷의 할 일·레벨·경험치·스탯이 같은 시각 텔레그램 `/today`, `/week`, `/status`와 같다
  - 2: 덮개를 닫으면 10초 안에 "BE 꺼짐 · 마지막 응답 {시각}", 사생활 보호 창은 "기록 없음"
  - 5: 11/29 사다리 두 단계 → `2026-11`, 12/27 영역 점수 → `2026-Q4`, 내려간 영역에 디버프와 회복 퀘스트 하나
  - 9: 운영 앱이 실제 `/chat` 스트림을 읽고 그 스트림이 `parse_sse`와 06(06b) 기준 응답(운영 앱 스레드 확인본)의 조각 순서와 맞다, `/actions` → `undo_id` → 한 번 되돌림
  - 10: 구독 뒤 아침 브리핑이 푸시로만 오고 `proactive.sent_today` +1, 구독을 지우면 다음 회차가 텔레그램
  - `state/logs/`에 토큰과 보낸 문장이 없다, 시드 가져온 뒤 노트북 밖 사본을 지웠다
  - 확인 SQL: `SELECT run_id, channel, mode, status, push_ok, push_failed FROM run_deliveries ORDER BY run_id DESC LIMIT 10`, `SELECT source_kind, count(*), sum(amount) FROM status_xp_ledger GROUP BY 1`
- [ ] 날마다 체크하고 문제는 새 이슈로.
- [ ] **Commit** `docs: SP3-4 acceptance results`

---

### 티켓 21a: 스펙 갱신 — 계약에 걸린 빈 곳

**목표:** 아래 "스펙 빈 곳" 표의 1·2·3·4·5·6·7·9·11·13·15를 스펙에 옮긴다. 문구가 없는 계약 결정이라 02 전에 머지한다. 스펙 PR과 같은 흐름(새 가지, PR, Dahun 검토, 머지).
**막는 티켓:** 없음(02를 막는다)
**라벨:** `ready-for-agent` + **Dahun 검토**

**Files:** Modify 스펙(7.4, 6.4.1, 7.5, 4.3 표, 5.1(011 마이그레이션), 6.1·15장, 12장, 6.4.5, 6.4.7 표·카탈로그 판, 13.1·14장 CSP, 16장, 변경 기록), 이 계획(빈 곳 표 머리에 "스펙 반영: <PR>")

- [ ] `git fetch origin && git switch -c docs/sp3-4-spec-contract origin/main`
- [ ] 각 줄의 결정 칸을 그 절의 문장으로(티켓 번호는 뺀다). 시드 내용·실제 사건·점수는 넣지 않는다.
- [ ] 변경 기록 한 줄: `| <날짜> | v4 | 구현 계획의 계약 결정(빈 곳 1~7, 9, 11, 13, 15) 반영 | SP3-4 구현 계획 |`(21b가 먼저 머지되면 `v5`)
- [ ] 확인: `grep -c "ui_milestone_draft\|ui_chapter_draft" <스펙>` ≥ 2, `grep -n "2026-10-24.2\|011_inbound_conversation" <스펙>` 각 한 줄 이상, `git diff --stat`이 스펙과 이 계획뿐
- [ ] **Commit** `docs(spec): fold SP3-4 plan contract decisions into the spec`, `git push -u origin docs/sp3-4-spec-contract`, PR(본문: 빈 곳 번호와 바꾼 절의 짝 표)
- [ ] **수용 확인**: 머지 뒤 스펙만 읽고 02·06·12·16의 해당 부분을 쓸 수 있다(짝 표의 줄마다 스펙 문장이 있다).

---

### 티켓 21b: 스펙 갱신 — 문구와 표시

**목표:** 문구 표 C1~C4와 빈 곳 8·10·12·14를 스펙(부록 A, 13.1, 11.1)에 옮기고 Dahun이 문구를 확인한다. 11·14 전에 머지한다.
**막는 티켓:** 없음(11, 14를 막는다)
**라벨:** `ready-for-agent` + **Dahun 검토**

**Files:** Modify 스펙(부록 A, 13.1 사유 표시, 11.1 1단계·이미 기록한 달, 변경 기록), 이 계획(문구 표)

- [ ] `git switch -c docs/sp3-4-spec-copy origin/main`, 각 결정을 그 절에, 변경 기록 한 줄(21a 다음 판 `v5`, 21b가 먼저 머지되면 `v4`, "확인 문구 C1~C4와 표시 반영").
- [ ] 확인: 부록 A에 C1~C4 네 줄, 13.1에 사유 여섯, `grep -nE "놓쳤어요|밀렸어요|늦었지만" <스펙>`이 금지어 목록 줄 밖에서 나오지 않음.
- [ ] **Commit** `docs(spec): add SP3-4 confirmation copy and labels`, push, PR(본문: "C1~C4 Dahun 확인 필요"). Dahun이 고치면 같은 PR에서 고치고, 같은 날 이 계획의 문구 표와 11·13·14의 기대값을 맞춘다.
- [ ] **수용 확인**: 머지 뒤 11·13·14의 문구 시험 기대값이 스펙 부록 A의 글과 같다.

---

## 문구 표 (Dahun 확인 필요)

스펙 부록 A에 없는 확인 문구만 이 계획이 정했다(빈 곳 8). 사다리 1·2단계, 사다리 기록(건너뛴 경우 포함), 영역 점수 묻기, 사건 버튼·확정·빼기, 칭호, 레벨, 되돌림은 **부록 A 그대로** 쓴다. 아래는 존댓말이고 SP1 금지어와 "연속"을 쓰지 않는다. **Dahun 확인 필요**(21b). 바뀌면 이 표와 해당 시험의 기대값만 고친다.

| # | 자리 (티켓) | 문구 | 비고 |
|---|---|---|---|
| C1 | `record_area_scores` 확인 줄 (11) | `✓ 영역 점수를 기록했어요 ({YYYY-Qn}): 커리어 7 · 경제 5` | 넣은 영역만, SP1 영역 순서 |
| C2 | `confirm_chapters` 확인 줄 (11, 13) | `✓ 챕터를 저장했어요: {제목} ({시작}~{끝 또는 "지금"})` | |
| C3 | 챕터 빼기 (11, 13) | `✗ 챕터를 뺐어요: {제목}` | 정리된 챕터 버튼은 `이미 정리된 챕터예요.` |
| C4 | 도구로 기록한 사다리 `record_ladder_score` (11) | `✓ 사다리를 기록했어요 ({YYYY-MM}): 지금 {n} · 5년 뒤 {m}` | 없는 쪽은 ` · …` 째로 뺀다 |

## 스펙 빈 곳과 이 계획의 결정

| # | 스펙 자리 | 빈 곳 | 이 계획의 결정 (티켓) | 스펙 반영 |
|---|---|---|---|---|
| 1 | 7.4 vs 1장 조건 11 | 모든 머리글에 `@telegram`/`@app`을 붙이면 SP1 시험(`"### 01:00 사용자 [1]\n\n…"`)이 깨진다 | 앱 머리글에만 ` @app`, 표시 없는 머리글은 `telegram` (02) | 21a |
| 2 | 6.4.1 `start`, `x-conversation-id` | 대화 id가 첫 조각과 헤더에 필요한데 두뇌 갈래는 꺼낼 때 대화를 고른다 | 받을 때 동기 `route_app_message`가 고른다 (06) | 21a |
| 3 | 14장 CSP, 13.1 | App Router 인라인 스크립트, `vercel.json`은 빌드 상수를 못 읽음, `default-src`가 인라인 스타일도 막음 | Pages Router, `_document`의 첫 `<meta>` CSP, `style-src 'self'`, `check-csp` (16) | 21a |
| 4 | 6.1, 15장 | `API_TOKEN`이 없거나 짧을 때 동작이 없다 | API를 열지 않고 `api_token_missing` 경고, 텔레그램·루프는 계속 (01) | 21a |
| 5 | 12장 | 읽을 수 없거나 JSON이 아닌 파일의 종료 코드, BOM, 틀린 항목 | 코드 6, `utf-8-sig`, 틀린 항목은 `invalid` 개수만 (12) | 21a |
| 6 | 6.4.5 `cards` | 텔레그램 버튼 재료가 저장되지 않는다 | `tool_events_log.run_id`와 `ask_condition_for`로 다시 만든다, 기록한 컨디션은 뺀다 (02) | 21a |
| 7 | 6.4.7 카탈로그 | 앱에 사건·챕터 초안 카드가 없다 | 하네스 출처 `ui_milestone_draft`, `ui_chapter_draft`, 판 `2026-10-24.2`, 운영 앱 스레드 확인(02 마무리) (02, 13) | 21a |
| 8 | 부록 A | 영역 점수, 챕터 확정·빼기, 도구로 기록한 사다리의 확인 문구 | 문구 표 C1~C4, Dahun 확인 필요 (11, 13) | 21b |
| 9 | 1장 조건 9, 16장 | 운영 앱의 기준 SSE 응답이 없다 | 06이 6.4.1과 AI SDK UI message stream으로 `tests/fixtures/app_golden/`를 만들고 운영 앱 스레드에 보내 확인받는다. 06은 그 답에 막히지 않는다 (06, 06b, 20) | 21a |
| 10 | 13.1 "건너뜀({사유})" | 사유 표시 문구가 없다 | `docs/acceptance/sp1-checklist.md`의 뜻을 줄인 짧은 표시 (16) | 21b |
| 11 | 7.5 M4 `senders: dict` | 생성자를 바꾸면 SP1 `Dispatcher(sender=…)` 시험이 깨진다 | `sender`(텔레그램)를 두고 `app_sender`를 더한다 (06) | 21a |
| 12 | 11.1-1 "컨디션 답 아래" | SP1 컨디션 버튼 답은 콜백 토스트라 키보드를 붙일 수 없다 | 회고 묶음의 컨디션 누름만 새 메시지로 답하고 거기에 1단계 키보드 (14) | 21b |
| 13 | 4.3 표 | 앱 요청이 여는 `conversations`의 작성자가 없다 | 디스패처(`route_app_message`), 쓰기 경로 감시에 넣는다 (06, 15) | 21a |
| 14 | 11.1 | 그 달 사다리가 이미 있을 때(사용자가 먼저 "이번 달 사다리 7") 1단계를 다시 물을지 | 그 달 `now`가 있으면 1단계를 묻지 않는다(11.1 "다음 회고가 두 번 묻지 않는다"와 같은 뜻) (14) | 21b |
| 15 | 5.1, 7.5 M6 | 받을 때 고른 대화가 `inbound_pending`에 없어 재시작 뒤 다시 넣은 앱 행의 대화가 정해지지 않는다 | `011_inbound_conversation.sql`로 `inbound_pending.conversation_id`를 더하고 `resubmit_inbound`가 넘긴다. 닫혔으면 다시 고른다 (06) | 21a |

21a·21b가 머지되면 스펙이 다시 기준이고, 이 표는 어디서 왔는지 기록으로만 남는다.

## 스펙 대비 확인 (셀프 리뷰)

스펙 1장 완료 조건
- 1 (화면 넷, 다섯 확대, 텔레그램과 같은 값) → 02, 03, 15, 16~18, 20 · 2 (꺼짐 10초) → 16, 20 · 3 (401, CORS, 로그) → 01, 08, 15 · 4 (`mode=ro`) → 01
- 5 (사다리, 영역 점수, 디버프) → 03, 11, 14, 20 · 6 (초안은 확정 전 없음) → 11, 13 · 7 (`seed-life`) → 12 · 8 (경험치 줄지 않음) → 15
- 9 (`/chat` SSE, `undo_id`) → 04, 05, 06, 06b, 07, 20 · 10 (주 통로 `app`, 푸시, 대체) → 08, 20 · 11 (자동 테스트, SP1 그대로) → 작업 방식, 04, 15

스펙 절
- 3 → 00 · 4.2~4.3 → 01, 04, 15 · 4.4 → File Structure
- 5.1 → 01, 06(011), 07 · 5.2 → 04, 05 · 5.3 → 08, 09 · 5.4 → 11, 12 · 5.5 → 03, 15
- 6.1 → 01 · 6.3.1 → 01, 08 · 6.3.2~6.3.4 → 02 · 6.3.5~6.3.6 → 03 · 6.4 `/schema` → 02 · 6.4.1 → 06, 06b · 6.4.2 → 04 · 6.4.3~6.4.4 → 05 · 6.4.5 → 02, 07 · 6.4.6 → 02 · 6.4.7 → 02, 09, 13 · 6.4.8~6.4.9 → 08
- 7.1~7.2 → 07 · 7.3 → 01, 08 · 7.4 → 02 · 7.5 → 06
- 8 → 03, 18 · 9.1 → 15 · 9.2~9.4 → 03, 11 · 10 → 11, 13, 15 · 10.1 → 10
- 11.1~11.2 → 14 · 11.3 → 13 · 11.4 → 15 · 12 → 12 · 13 → 16~18 · 14 → 01, 08, 16, 19 · 15 → 01, 08 · 16 → 각 티켓, 15 · 17 → 확정됨 · 부록 A → 11, 13, 14, 15, 16, 문구 표 · 빈 곳 → 21a, 21b

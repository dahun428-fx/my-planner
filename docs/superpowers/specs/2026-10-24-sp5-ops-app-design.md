# SP5 운영 앱 상세 설계 (청사진 · 화면 · 기능)

- 상태: 확정 v3 (Dahun 검토)
- 작성일: 2026-10-24
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP1 비서 코어](2026-10-23-sp1-secretary-core-design.md), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (BE HTTP API 계약의 **정본**)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md), 결정 기록: [`docs/adr/`](../../adr/) (이번에 [0009](../../adr/0009-ops-app-static-pwa-keeps-read-snapshot.md) 추가)
- 화면 시안: Design 캔버스 "비서 운영 앱 화면 시안" (8개 화면, https://claude.ai/artifact/76cZTQhG8ix1MVuvxQ6XAp). 이 문서의 5장이 시안의 글 버전이다. 둘이 다르면 이 문서가 맞다.
- 범위: Dahun의 아이폰에서 비서를 운영하는 앱(FE)만 다룬다. 앱이 부르는 API는 SP3-4 스펙 6장, 7장, 14장이 정하고, 이 문서는 그 계약을 **쓰기만** 한다. 계약에 더할 것은 12장에 모았다.

## 1. 목표와 완료 조건

텔레그램과 동등한 두 번째 통로를 만든다. Dahun은 아이폰 홈 화면의 앱에서 오늘을 보고, 비서와 대화하고, 체크인에 답하고, 할 일을 고치고, 비서가 바꾼 것을 되돌린다. 비서는 앱의 "오늘" 화면을 직접 정리하고, 대화 안에서 미리 정해 둔 부품으로 화면 조각을 띄운다.

**세 조각** (SP3-4 1장과 같다)

| 조각 | 이 문서에서 |
|---|---|
| BE (노트북의 my-planner) | 부르기만 한다. 두뇌와 데이터는 모두 BE에 있다 |
| 대시보드 (`web/dashboard/`) | 다루지 않는다. 같은 API, 같은 토큰, 같은 배포 방식이라 설정과 검사 스크립트를 함께 쓴다 |
| 운영 앱 (`web/app/`) | 전부 |

**완료 조건 (수용 기준)**

1. 아이폰 Safari에서 앱 주소를 열고 "홈 화면에 추가"한 뒤, 처음 연결 화면에서 BE 주소와 토큰을 넣으면 `GET /health`로 연결을 확인하고 오늘 화면으로 간다. 토큰이 틀리면 "열쇠가 맞지 않아요" 문구가 나오고 다음으로 가지 않는다.
2. 오늘 화면이 `GET /today`의 브리핑, 컨디션, 할 일 묶음(우선순위 → 일정 → 열린 할 일), 고정 카드를 같은 순서로 보여 준다. 같은 시각 텔레그램 `/today`와 할 일 목록이 같다.
3. 할 일 체크, 컨디션 기록, 날짜 옮기기, 초안 확정이 `POST /actions`로 반영되고, 응답의 확인 문구가 화면 아래 알림 줄에 4초 보이며, 그 줄의 "되돌리기"가 `POST /activity/{id}/undo`를 부른다.
4. 비서 대화 시트에서 보낸 메시지에 대한 답이 글자 단위로 흘러나오고(`POST /chat` SSE), `ui_*` 조각은 7장의 부품으로 그려진다. 카탈로그에 없는 부품은 글로 대신 보인다. 대화 도중 연결이 끊겨도 다시 열면 같은 답이 보인다(같은 `client_msg_id` 재요청).
5. 주 통로가 `app`이고 이 기기가 푸시를 구독했으면 체크인 알림이 아이폰 알림으로 오고, 알림을 누르면 그 체크인 화면이 열린다. 앱에서 답하면 텔레그램의 같은 회차 버튼이 사라진다(BE 7.3, 6.4.5).
6. 노트북이 꺼지면 다음 요청(화면의 `GET`이나 30초마다의 `/health`)이 10초 안에 응답하지 않는 순간 "비서 오프라인" 상태가 되고(꺼진 뒤 최대 40초), 마지막으로 받은 오늘 화면과 이번 주 할 일을 읽기 전용으로 보여 준다(받은 시각 표시). 쓰는 동작은 모두 막히고 이유가 보인다.
7. 기록 화면이 `GET /activity`를 최근 것부터 보여 주고(12장 R4a), 지금 되돌릴 수 있는 줄에만 "되돌리기"가 있다. 회차가 남긴 확인 요청(`ui_confirm`)은 "확인이 필요해요" 묶음에 맨 위로 나온다.
8. 화면 문구에 SP1 금지어가 없다(10장 검사 테스트). 색은 9장의 토큰만 쓰고, taste 스킬의 `lint.mjs --app`이 `FAIL` 없이 끝난다.
9. 13장의 자동 테스트가 모두 통과하고, `npm run build`가 정적 파일(`out/`)을 만들며 CSP 검사(`check:csp`)를 통과한다.

## 2. 범위

| 포함 (v1) | 제외 (언제) |
|---|---|
| 처음 연결(주소, 토큰, 알림 허용) | 여러 사용자, 로그인 화면 (하지 않음) |
| 오늘 화면(브리핑, 컨디션, 할 일, 고정 카드, 대기 중인 체크인) | 인생곡선, 상태창 화면 (대시보드가 담당) |
| 비서 대화 시트와 생성형 UI 조각 | 계획 모드 `/plan` 전용 화면 (v2. v1은 대화에서 `/plan`을 글로 보내면 된다) |
| 체크인 상세와 답장 | 주간 회고 전용 화면 (v2. v1은 회고 회차도 체크인 화면으로 연다) |
| 할 일 화면(기간 탭, 우선순위, 초안, 추가, 옮기기, 빼기) | 기억 카드 `/memory` (SP2 뒤) |
| 기록과 되돌리기, 확인 요청 | 체크인 시간 바꾸기 (노트북 `config.toml`에서 한다) |
| 웹 푸시 알림, 주 통로 설정, 시험 알림 | 네이티브 앱(React Native) |
| 오프라인 읽기 전용 보기 | 오프라인에서 쓰기를 모아 두었다 보내기 (하지 않음, 4.6) |
| 밝은·어두운 화면 | 홈 화면 위젯, 단축어 |

## 3. Dahun 결정 (2026-10-24, 이 스레드)

| # | 질문 | 결정 |
|---|---|---|
| D1 | 텔레그램과의 관계 | 둘 다 동등한 통로. 같은 비서, 같은 상태 |
| D2 | 앱 형태 | PWA(Next.js + Vercel AI SDK). 1인 전용 |
| D3 | 데이터 | 앱은 FE, 노트북 my-planner가 BE. 모든 데이터와 두뇌는 API 너머에 있다 |
| D4 | 배포 | FE는 Vercel, BE는 노트북(Tailscale 안). 나중에 BE를 클라우드로 옮길 수 있게(주소는 설정값, 첫날부터 토큰 인증) |
| D5 | 첫 화면 | "오늘" 화면. 비서가 카드를 정리하고, 비서는 아래에서 올라오는 시트로 부른다 |
| D6 | 자율성 | 되돌리기 쉬운 일은 바로 하고 되돌리기를 남긴다. 빼기, 우선순위, 시각 변경은 확인 (SP3-4 10.1이 정확한 규칙) |
| D7 | v1 범위 | 오늘, 대화, 체크인, 할 일, 기록·되돌리기, 설정. 계획 모드·주간 회고·기억은 v2 |
| D8 | 알림 | 주 통로 하나만 울린다. 기본은 앱 웹 푸시, 안 가면 텔레그램 |
| D9 | 분위기 | iOS 기본 앱 느낌(미리알림·건강 앱처럼) |
| D10 | 생성형 UI | BE가 주는 부품 목록 안에서만 조립. AI가 화면 코드를 쓰지 않는다 |
| D11 | 대화 | 대화 기록은 통로마다 따로, 상태는 공유 |
| D12 | 가정 확인 | 로그인 없음(Tailscale + 기기별 토큰), 오프라인은 읽기 전용 캐시, 한국어 화면 |
| D13 | 대시보드와의 관계 | 대시보드는 별개 앱. API 계약만 공유한다 |

**성공의 모습**: 2주 동안 아침·저녁 체크인을 주로 앱에서 하게 되고, 어느 통로에서 답해도 결과가 같다.

## 4. 청사진

### 4.1 전체 그림

```
아이폰 (홈 화면 PWA)                         Vercel                 노트북 (Tailscale 안)
┌──────────────────────────────┐   HTML/JS   ┌──────────┐          ┌─────────────────────────────┐
│ 운영 앱 (정적 Next.js)        │ ◀────────── │ web/app  │          │ my-planner (BE)             │
│  화면 · AI SDK useChat        │             │ out/     │          │  /api/v1  (aiohttp)         │
│  서비스 워커 (푸시, 앱 껍데기) │             └──────────┘          │  디스패처 = 유일한 작성자    │
│  localStorage: 주소, 토큰     │                                   │  두뇌 (Claude Agent SDK)    │
│  IndexedDB: 읽기 스냅샷, 조각 │ ── HTTPS (tailscale serve) ─────▶ │  SQLite · md 원문 기록      │
└──────────────────────────────┘ ◀── SSE (/chat) ─────────────────  └──────────────┬──────────────┘
          ▲                                                                         │ 웹 푸시 (VAPID)
          └──────────── Apple 푸시 서버 ◀───────────────────────────────────────────┘
```

- Vercel은 정적 파일만 내려 준다. 서버 함수, API 라우트, 서버 렌더링 데이터 가져오기는 없다(대시보드 ADR 0008과 같다).
- 폰 브라우저가 BE를 **직접** 부른다. 그래서 앱을 쓰려면 폰의 Tailscale이 켜져 있어야 한다. 알림은 Apple 푸시 서버를 거치므로 Tailscale이 꺼져 있어도 온다(답하려면 켜야 한다).
- 두뇌, 데이터, 규칙(자율성, 확인, 하루 상한)은 모두 BE에 있다. 앱은 규칙을 다시 구현하지 않고 응답(`needs_confirm`, `undo_id`, 고정 문구)을 그대로 보여 준다.

### 4.2 접근안과 선택

| 안 | 내용 | 판단 |
|---|---|---|
| **A. Next.js 정적 내보내기, 브라우저가 BE 직접 호출** | 서버 코드 없음. AI SDK `useChat`이 BE `/chat` 스트림에 바로 붙는다 | **선택**. 토큰이 폰 밖으로 나가지 않고, 대시보드와 같은 구성이다 |
| B. Next.js 서버 라우트가 BE를 대신 호출 | Vercel 서버가 BE에 닿아야 한다 | 버림. Vercel은 tailnet 밖이라 BE를 인터넷에 열어야 한다 |
| C. Vite 단일 페이지 앱 | 가볍다 | 버림. 대시보드와 구성, 검사 스크립트가 갈라진다 |

### 4.3 기술 구성

대시보드 계획(SP3-4 계획 16)과 같은 판을 쓴다. 판 번호는 `web/dashboard/package-lock.json`을 따른다.

| 항목 | 선택 | 이유 |
|---|---|---|
| 프레임워크 | Next.js 15 **Pages Router**, `output: "export"`, `trailingSlash: true`, `images.unoptimized` | App Router는 정적 HTML에 인라인 `<script>`를 넣어 CSP `script-src 'self'`와 맞지 않는다(대시보드와 같은 이유) |
| 대화 | `ai` 5.x + `@ai-sdk/react` 5.x의 `useChat` + `DefaultChatTransport` | BE가 AI SDK UI message stream v1을 보낸다(SP3-4 6.4.1) |
| 스타일 | CSS Modules + `src/styles/tokens.css` | CSP `style-src 'self'`라 정적 HTML의 인라인 `style` 속성은 막힌다. 그래서 컴포넌트에 `style={{…}}`를 쓰지 않는다. 줄 밀기·시트 끌기처럼 움직이는 값은 `ref`로 CSSOM(`el.style.transform = …`)에 직접 쓴다(CSP가 막지 않는다) |
| 아이콘 | 손으로 그린 인라인 SVG 8개 (`src/components/icons.tsx`) | 외부 아이콘 묶음을 들이지 않는다. 1.7px 선, 24px |
| 글꼴 | 시스템 글꼴(`-apple-system`, `Apple SD Gothic Neo`) | 아이폰에서 기본 앱처럼 보이게. 외부 글꼴을 받지 않는다(CSP) |
| 기기 저장 | `localStorage`(주소, 토큰, 마지막 연결 시각), IndexedDB `idb-keyval`(읽기 스냅샷, 최근 대화 조각) | 4.6 |
| 서비스 워커 | 손으로 쓴 `public/sw.js` (푸시, 알림 누름, 앱 껍데기 캐시) | 플러그인 없이 50줄 안팎. CSP와 충돌하지 않는다. 의존성 없는 고전 스크립트라 시험은 Node `vm`으로 돌린다. 빌드 뒤 `sw-manifest.json`이 캐시 목록과 빌드 id를 준다 |
| API 타입 | BE `GET /schema` → `json-schema-to-typescript` → `src/api/types.gen.ts` | 같은 규칙·같은 출력 문구의 `scripts/gen-types.mjs`를 `web/app/scripts/`에 따로 둔다. Vercel 루트가 패키지마다 달라 다른 패키지의 스크립트를 부르면 빌드가 루트 밖에 기대고, 대시보드가 아직 없을 수도 있다. 둘 중 하나를 고치면 다른 쪽도 같은 PR에서 고친다 |
| 조각 검사 | `@cfworker/json-schema` | `eval`·`new Function`을 쓰지 않는 JSON Schema 검사기. ajv는 실행 중 컴파일에 `new Function`을 써서 CSP `script-src 'self'`(`unsafe-eval` 없음)에서 막힌다 |
| 테스트 | Vitest + Testing Library + MSW + jsdom, Playwright(390×844) | 13장 |

### 4.4 폴더

```
web/app/                         # Vercel 루트 디렉터리
  package.json  package-lock.json  next.config.mjs  tsconfig.json  vercel.json
  vitest.config.ts  playwright.config.ts
  public/  manifest.webmanifest  sw.js  icons/{icon-192,icon-512,apple-touch-icon}.png
  src/
    pages/       _app.tsx _document.tsx index.tsx connect.tsx todos.tsx activity.tsx settings.tsx checkin.tsx
    api/         client.ts  actions.ts  validate.ts  errors.ts  types.gen.ts  schema.json
    lib/         connection.ts  ConnectionProvider.tsx  snapshot.ts  time.ts  polling.ts  push.ts
                 ids.ts  copy.ts  theme.ts
    chat/        transport.ts  ChatSheet.tsx  MessageView.tsx  parts.ts  localParts.ts  command.ts
    ui/          catalog.ts  CatalogProvider.tsx  registry.tsx
                 components/{TodoList,Choice,SummaryCard,TodoDraft,ConditionPicker,LadderPicker,
                 AreaScores,MilestoneDraft,ChapterDraft,Confirm,UnknownPart}.tsx
    screens/     Today.tsx  Checkin.tsx  Todos.tsx  AddTodoSheet.tsx  Activity.tsx  Settings.tsx  Connect.tsx
    components/  TabBar.tsx  LargeTitle.tsx  Group.tsx  Row.tsx  TodoRow.tsx  SwipeRow.tsx  Segmented.tsx
                 Sheet.tsx  Toast.tsx  ConfirmSheet.tsx  StatusDot.tsx  OfflineNotice.tsx  BlockError.tsx
                 Skeleton.tsx  ChatLauncher.tsx  icons.tsx
    styles/      tokens.css  globals.css  *.module.css(컴포넌트 옆)
    test/        setup.ts  server.ts  handlers.ts  render.tsx  fixtures/*.json
  scripts/       check-csp.mjs  gen-types.mjs  lint-copy.mjs  sw-manifest.mjs  make-icons.mjs  size.mjs  serve-csp.mjs
  e2e/           csp.spec.ts  screens.spec.ts  routes.ts
```

쓰기 동작은 `api/actions.ts`, 연결 상태 공급자는 `lib/ConnectionProvider.tsx`, 부품 목록 공급자는 `ui/CatalogProvider.tsx`, 확인 시트는 `components/ConfirmSheet.tsx`, 명령 보내기는 `chat/command.ts`에 둔다. 응답 모양 검사는 `api/validate.ts`, 화면 설정은 `lib/theme.ts`다.

모듈 경계:

| 모듈 | 하는 일 | 쓰는 쪽 | 기대는 것 |
|---|---|---|---|
| `api/client.ts` | `fetch` 감싸기: 주소·토큰 붙이기, 10초 시간 제한, 오류 모양(SP3-4 6.1)을 `ApiError`로, 네트워크 오류를 `lib/connection`에 알림. 성공 응답은 `schema.json`의 모델을 `@cfworker/json-schema`로 검사하고 모양이 다르면 `error`, 코드 `shape`로 돌려준다(`api/validate.ts`). 시험용 고정 자료도 같은 검사를 거친다(`fixtures.test.ts`) | 화면 전부 | `lib/connection` |
| `lib/connection.ts` | 주소·토큰 저장과 읽기, 연결 상태(`online`·`offline`·`unauthorized`·`safe_mode`) 하나를 앱 전체에 알림 | `_app`, 화면 | `/health` |
| `lib/snapshot.ts` | 읽기 응답을 `beUrl`과 함께 IndexedDB에 저장하고 오프라인일 때 돌려줌. 저장된 `beUrl`이 지금 BE 주소와 다르면 버린다 | 오늘, 할 일 | `idb-keyval` |
| `chat/transport.ts` | `DefaultChatTransport` 설정: 마지막 사용자 메시지 하나만 보냄, `client_msg_id`·`conversation_id`·`checkin_id` 붙임 | `ChatSheet` | `lib/connection` |
| `ui/registry.tsx` | `ui_*` 이름 → 컴포넌트. 카탈로그 판 확인, props 검증, 모르면 `UnknownPart` | 대화, 오늘, 체크인 | `ui/catalog` |
| `screens/*` | 화면 하나씩. 데이터 가져오기, 상태 표시 | `pages/*` | 위 모듈 |

### 4.5 화면 주소 (정적 내보내기)

| 주소 | 화면 | 비고 |
|---|---|---|
| `/` | 오늘 | 연결 설정이 없으면 `/connect/`로 |
| `/connect/` | 처음 연결 | 설정의 "다시 입력"도 여기 |
| `/todos/` | 할 일 | `?tab=week` 같은 쿼리로 탭 |
| `/activity/` | 기록 | |
| `/settings/` | 설정 | |
| `/checkin/?id=341` | 체크인 상세 | 정적 내보내기라 동적 경로 대신 쿼리. 푸시 페이로드 `url`은 `/checkins/341`(SP3-4 6.4.8)이므로 **서비스 워커가 `/checkins/<id>`를 `/checkin/?id=<id>`로 바꿔 연다** |

대화는 주소가 없는 시트다. 어느 화면에서나 아래 "비서에게 말하기"로 열고, 닫으면 원래 화면이 남는다.

### 4.6 데이터 흐름

**읽기**

- 화면을 열 때, 앱이 앞으로 올 때(`visibilitychange`), 보이는 동안 60초마다 그 화면의 `GET`을 부른다(대시보드와 같은 주기). 쓰기 응답을 받은 뒤에는 그 화면의 `GET`을 한 번 더 부른다.
- 성공한 `GET /today`, `GET /week` 응답은 받은 시각과 함께 IndexedDB 스냅샷에 덮어쓴다(키 `snap:today`, `snap:week`). 오늘 체크인 요약은 `/today.checkins`에 있으므로 `snap:today` 하나에 같이 남기고 `snap:checkins`는 두지 않는다. 다른 응답은 저장하지 않는다. 스냅샷에는 받은 시각과 함께 그때의 BE 주소(`beUrl`)를 두고, 지금 주소와 다르면 버린다(다른 BE로 다시 연결했을 때 옛 내용이 보이지 않게).

**쓰기**

- 모든 쓰기는 `POST /actions`, `POST /activity/{id}/undo`, `POST /chat`, `PUT /settings/notify`, `POST|DELETE /push/subscriptions`, `POST /push/test`다. 이 가운데 `/actions`, `/undo`, `/chat` 셋만 `client_msg_id`(UUID v4)를 갖는다(SP3-4 6.1). 동작마다 새 값을 만들고, 네트워크 오류로 같은 동작을 다시 보낼 때만 같은 값을 쓴다. 나머지 경로에는 넣지 않는다.
- **낙관적 반영은 체크 표시 하나만** 한다: 할 일을 체크하면 바로 줄을 그리고, 실패하면 되돌리며 오류 줄을 띄운다. 나머지는 응답을 받고 바꾼다(BE가 `needs_confirm`이나 `rejected`를 줄 수 있어서).
- 응답이 올 때까지 같은 동작·같은 인자의 두 번째 누름은 보내지 않는다(`useAction`이 열쇠별로 진행 중 표시를 둔다).
- 오프라인에서는 쓰기를 모아 두지 않는다. 쓰는 버튼은 꺼지고 "비서가 다시 연결되면 할 수 있어요"가 보인다. 나중에 보낸 쓰기가 그 사이 바뀐 상태를 덮는 일을 막기 위해서다.

**대화**

- `useChat`이 `POST /chat`으로 마지막 사용자 메시지 하나와 `client_msg_id`(= 그 사용자 `UIMessage.id`, UUID), `conversation_id`(마지막으로 받은 값), `checkin_id`(체크인 화면에서만)를 보낸다. 대화 id는 `start` 조각의 `messageMetadata.conversation_id`에서만 읽는다(`DefaultChatTransport`는 응답 헤더를 넘겨 주지 않는다). 값이 바뀌면(30분 규칙) 같은 시트에 "새 대화" 구분선을 넣고 이어 보여 준다.
- 시트를 열 때 `GET /conversations?channel=app&limit=3`과 가장 최근 대화의 `GET /conversations/{id}/messages`로 글을 채운다. BE 원문 기록에는 화면 조각이 없으므로(SP3-4 6.4.6), 앱은 받은 `ui_*` 조각을 `localParts`(IndexedDB, 비서 메시지 id = SSE `start.messageId`별, 최근 200개, 7일)에 두었다가 같은 id의 메시지에 다시 붙인다. 메시지 목록 항목에 `id`가 있어야 한다(12장 R4d). 다른 기기나 지운 뒤에는 조각 없이 글만 보인다.
- 스트림 도중 끊기면 `regenerate()`로 같은 사용자 메시지(같은 `UIMessage.id` = 같은 `client_msg_id`)를 한 번 다시 보낸다(BE가 저장한 답을 돌려준다, 6.4.1). 그래도 안 되면 메시지 아래 "답을 받지 못했어요 · 다시 받기"를 둔다. `useChat`의 `resume`은 끈다(BE에 스트림을 다시 잇는 `GET` 경로가 없다).

**푸시**

- 처음 연결이나 설정에서 알림을 허용하면 `GET /push/vapid-public-key` → `PushManager.subscribe` → `POST /push/subscriptions`(이름 `폰`)를 한다. 받은 `id`를 `localStorage["mp.pushId"]`에 둔다.
- 서비스 워커는 푸시를 받으면 `title`, `body`로 알림을 띄우고(`tag` = `run-<checkin_id>`, `type: notice`면 `notice`. 같은 회차는 덮어쓴다), 누르면 4.5 규칙으로 주소를 바꿔 연다(`url`이 없으면 `/`). 자세한 순서는 F7.
- 아이폰은 홈 화면에 추가한 앱에서만 푸시를 받는다(iOS 16.4 이상). 또 Safari 탭과 홈 화면 앱은 `localStorage`와 IndexedDB를 **따로** 쓴다. 그래서 연결은 홈 화면 앱에서 한다(5.5.8).

### 4.7 기기 저장과 보안

| 무엇 | 어디 | 언제 지우나 |
|---|---|---|
| BE 주소, 토큰 | `localStorage` `mp.beUrl`, `mp.token` | 설정 "이 기기 연결 해제" |
| 마지막 연결 시각 | `localStorage` `mp.lastHealthOk` | 같음 |
| 푸시 구독 id | `localStorage` `mp.pushId` | 같음 (BE `DELETE /push/subscriptions/{id}`도 부름) |
| 읽기 스냅샷(오늘 + 오늘 체크인 요약, 이번 주) | IndexedDB `snap:today`, `snap:week` (받을 때의 `beUrl` 포함) | 같음, 그리고 받은 지 7일 지나면 |
| 최근 대화 조각 | IndexedDB `parts:*` (200개) | 같음, 그리고 받은 지 7일 지나면 |
| 부품 목록(카탈로그) | IndexedDB `catalog` | 같음, 그리고 판이 바뀌면 |
| 화면 설정(시스템 따라 · 밝게 · 어둡게) | `localStorage` `mp.theme` | 설정 "이 기기 연결 해제" |

- 토큰은 빌드, Vercel 환경 변수, 저장소, 로그, 오류 보고 어디에도 넣지 않는다(SP3-4 14장). 화면에도 보이지 않는다(입력 칸은 `type="password"`).
- CSP는 대시보드(SP3-4 계획 16)의 문자열에 `worker-src 'self'; manifest-src 'self'` 두 개만 더한다: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ${NEXT_PUBLIC_CONNECT_SRC}; base-uri 'none'; form-action 'none'; worker-src 'self'; manifest-src 'self'`. `_document`의 첫 `<meta>`로 넣는다. `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, 최소 `Permissions-Policy`는 `<meta>`에서 듣지 않으므로 대시보드처럼 `vercel.json` 헤더로 보낸다. `check:csp` 스크립트가 `out/`의 모든 HTML에 인라인 스크립트와 인라인 스타일이 없는지 본다(대시보드와 같은 규칙·같은 출력 문구의 스크립트를 `web/app/scripts/`에 따로 둔다. 둘 중 하나를 고치면 다른 쪽도 같은 PR에서 고친다).
- 설정 화면은 `NEXT_PUBLIC_CONNECT_SRC` 범위 밖의 BE 주소를 받지 않는다(CSP가 어차피 막는다. 미리 알려 준다).
- **대시보드와 다른 점**: 대시보드는 화면 데이터를 기기에 남기지 않는다. 운영 앱은 Dahun 결정 D12에 따라 오늘·이번 주 할 일, 체크인 요약, 최근 대화 조각을 남긴다. 폰을 잃어버렸을 때의 노출 범위가 그만큼 넓다. 대신 7일이 지나면 지우고, 연결 해제 한 번으로 모두 지운다. ADR 0009.

### 4.8 BE를 클라우드로 옮길 때 (D4)

앱 쪽에서 바뀌는 것은 두 가지뿐이다.

1. Vercel 환경 변수 `NEXT_PUBLIC_CONNECT_SRC`를 새 BE 도메인으로 바꾸고 다시 빌드한다(CSP).
2. 앱 설정에서 BE 주소를 새 주소로 바꾼다. 토큰은 새 BE의 것을 넣는다.

화면, API 호출, 푸시 처리는 그대로다. Tailscale 없이 열린 서버가 되면 토큰 하나로 지키는 것이 약해지므로, 그때는 BE 쪽 인증 강화(기기별 토큰, 만료)를 BE 스펙에서 다시 정한다. 앱은 `Authorization: Bearer` 하나만 보내므로 토큰 종류가 바뀌어도 고칠 곳은 `api/client.ts` 한 곳이다.

## 5. 화면 설계 (UI/UX)

### 5.1 디자인 방향

- **바탕**: taste 스킬 앱 스타일 `achromatic-ledger`(seed 1081995691) + iOS 그룹 목록. 크롬(바탕, 탭, 제목)에는 색이 없다.
- **이 앱의 얼굴(고유 요소)**: **파란색 하나(`--hue`)는 "비서가 한 일"에만 쓴다.** 비서가 고정한 카드의 표시, 확인 요청의 테두리, 비서가 바꾼 기록의 점, 링크. Dahun이 한 일은 검정이다. 화면을 보면 비서가 손댄 곳이 바로 보인다(자율성 D6의 안전장치를 눈으로 보이게).
- **버린 것**: UI UX Pro Max가 추천한 라벤더·보라 팔레트와 Lora·Raleway 조합(전형적인 생성형 앱 느낌이고 taste 금지 목록), 그라데이션, 반짝이·AI 아이콘, 이모지, 쉬는 카드의 그림자, 유리 효과, 작은 대문자 라벨, 순번 매기기(01, 02).
- **iOS 관례**: 큰 제목(30/700), 회색 바탕 위 흰 그룹(반지름 16), 줄 높이 44~60, 하단 탭 4개, 아래에서 올라오는 시트, 줄 밀기 동작(대안 버튼 포함), 알약 모양 버튼.

### 5.2 토큰

```css
:root {
  --ground: #f2f2f5;   --surface: #ffffff;  --raised: #e9e9ee;  --bar: #f7f7f9;
  --rule: #ececf0;     --border: #e3e3e8;   --control: #d4d4da;
  --text: #111113;     --muted: #6a6a70;    --text-2: #3d3d42;
  --primary: #111113;  --on-primary: #ffffff;
  --hue: #1d5fbf;      /* 비서가 한 일, 링크. 화면의 1% 안쪽 */
  --positive: #247b50; --negative: #c4242a;
  --notice-bg: #fffbeb; --notice-border: #fde68a; --notice-ink: #5c2a07;
  --radius-group: 16px; --radius-field: 10px; --radius-pill: 999px;
  --pad: 16px; --gap: 20px; --row: 52px; --control-h: 44px; --small-control-h: 32px;
  --fs-title: 30px; --fs-section: 15px; --fs-body: 16px; --fs-meta: 13px; --fs-tab: 11px;
  --font: -apple-system, "SF Pro Text", "Apple SD Gothic Neo", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ground: #000000; --surface: #1c1c1e; --raised: #2c2c2e; --bar: #121214;
    --rule: #2c2c2e;   --border: #3a3a3c;  --control: #48484a;
    --text: #ffffff;   --muted: #a1a1a6;   --text-2: #d1d1d6;
    --primary: #ffffff; --on-primary: #000000;
    --hue: #5b9bff;    --positive: #3fc07a; --negative: #ff6b6b;
    --notice-bg: #2b2210; --notice-border: #5c4a17; --notice-ink: #f5d27a;
  }
}
```

- 대비: 모든 글자 색은 놓이는 면 위에서 4.5:1 이상(`--muted` #6a6a70은 흰 면 5.3:1, `--ground` 위 4.8:1). `--raised`(회색 알약) 위 글자는 `--muted`가 4.4:1이라 쓰지 않고 `--text` 또는 `--text-2`를 쓴다. 13장 테스트가 쓰이는 토큰 쌍을 모두 계산해 확인한다.
- 숫자는 `font-variant-numeric: tabular-nums`. 시각은 `HH:MM` 24시간.
- 크기 단계는 30 / 16 / 15 / 13 / 11 다섯 개만 쓴다. 굵기는 400, 600, 700(제목만).
- 움직임: 시트 열고 닫기 280ms, 줄 밀기 200ms, 알림 줄 나타나기 180ms. 모두 `transform`과 `opacity`만. `prefers-reduced-motion`이면 움직임 없이 바로 바뀐다. 화면 들어올 때의 연출은 없다(taste 앱 규칙).

### 5.3 내비게이션

- **하단 탭 4개**: 오늘 · 할 일 · 기록 · 설정. 아이콘 24px + 글자 11px, 현재 탭은 글자 색만 진하게(`--text`, 600). 색 있는 알약은 쓰지 않는다.
- **비서에게 말하기**: 오늘, 할 일, 기록 화면의 탭 위에 떠 있는 입력 모양 버튼(48px, 이 앱에서 그림자가 있는 유일한 것). 누르면 대화 시트가 올라온다. 설정 화면에는 없다.
- **체크인 상세**는 탭 밖의 화면이다. 위 왼쪽 "‹ 오늘"로 돌아간다.
- 안전 영역: 위 `env(safe-area-inset-top)`, 아래 `env(safe-area-inset-bottom)`을 바탕 여백에 더한다. 가짜 상태 표시줄을 그리지 않는다.

### 5.4 공통 상태

| 상태 | 판정 | 보이는 것 |
|---|---|---|
| 연결 설정 없음 | `mp.beUrl` 또는 `mp.token` 없음 | `/connect/`로 보낸다 |
| 연결됨 | 마지막 `/health`가 10초 안에 `200` | 제목 옆 초록 점 + "비서 연결됨" |
| 비서 오프라인 | 아무 요청에서나 네트워크 오류나 10초 초과 | 회색 점 + "비서 오프라인", 화면 맨 위 안내(5.5.4), 스냅샷 읽기 전용 |
| 비서 상태 나쁨 | `/health.status = degraded` | 점은 초록 그대로, 제목 아래 글로: 두뇌 로그인 문제(`brain.auth` `login`/`billing`)면 "비서가 노트북에서 다시 로그인해야 해요", 한도(`limited_until`)면 "비서가 {HH:MM}까지 답을 쉬어요". 텔레그램만 끊긴 경우(`polling: down`)는 오늘 화면에 표시하지 않고 설정의 상태 줄에만 "텔레그램 연결 끊김". 쓰기는 된다(두뇌 답만 고정 문구로 온다) |
| 토큰 틀림 | `401` | "열쇠가 맞지 않아요. 설정에서 다시 넣어 주세요." + 설정 링크. 쓰기 막음 |
| 너무 많은 시도 | `429` | "잠시 뒤에 다시 해 주세요." |
| 점검 필요 | `/health`가 `200 {"status": "safe_mode"}`, 또는 다른 경로가 `503 safe_mode` | "노트북의 데이터베이스 점검이 필요해요. README의 복구 절차를 따라 주세요." 쓰기 막음 |
| 그 밖 오류 | `5xx`, 모양 오류 | 그 블록 안에서만: "이 부분을 불러오지 못했어요 ({code}) · 다시 시도". 다른 블록은 그대로 |
| 불러오는 중 | 첫 요청 중 | 최종 배치 그대로, 값 자리에 실제 크기의 회색 막대. 반짝이 효과 없음. 데이터가 와도 배치가 움직이지 않는다 |

### 5.5 화면별 설계

각 화면은 "이 화면이 먼저 답하는 질문"을 하나 갖고, 가장 큰 것이 그 답이다.

#### 5.5.1 오늘 (`/`)

질문: **오늘 무엇을 하면 되나?**

| 순서 | 블록 | 데이터 | 동작 |
|---|---|---|---|
| 1 | 날짜(13, 회색) + 큰 제목 "오늘" + 연결 점 | `/today.date`, `weekday`, 연결 상태 | |
| 2 | **대기 중인 체크인** (있을 때만) | `/today.checkins` 중 `state = pending` | 줄을 누르면 체크인 상세. "저녁 체크인 · 답장할 수 있어요". 마감 시각은 보이지 않는다(P2: 남은 시간으로 압박하지 않는다) |
| 3 | **확인이 필요해요** (있을 때만) | 대기 중인 체크인의 `GET /checkins/{id}.cards` 중 `ui_confirm` | 7장 `Confirm` 부품 |
| 4 | 아침 브리핑 | `/today.brief.text`, `sent_at` | 없으면 블록째 숨김. 세 줄 넘으면 "더 보기" |
| 5 | 오늘 컨디션 | `/today.condition` | 1~5 알약 다섯 개(44px). 이미 있으면 그 값이 검정으로 채워지고 "바꾸기"가 된다. 누르면 `/actions record_condition` |
| 6 | 할 일 (n) | `/today.todos` 묶음 순서 그대로 | 줄 체크 = `complete_task`(완료된 줄 다시 체크 = `reopen_task`), 줄 밀기 = 내일로·빼기(5.5.5와 같음. "내일"은 `addDays(/today.date, 1)`), "전체 보기" = 할 일 화면 |
| 7 | 고정 카드 | `/today.cards` (`sort_order` 순) | 7장 부품으로 그린다. 카드 머리 오른쪽에 `--hue` 표시 "비서가 올려 둔 카드". 길게 누르면 "내리기"(`unpin_card`), "위로·아래로"(`reorder_cards`) |

- 완료된 할 일은 목록 끝에 회색 취소선으로 남는다(오늘 하루). "{HH:MM} 완료".
- 할 일이 0개면 그룹 틀은 두고 한 줄: "오늘 잡힌 할 일이 없어요. 비서에게 말하거나 + 로 추가할 수 있어요."
- 탭 위 "비서에게 말하기", 아래 탭.

#### 5.5.2 비서 대화 (시트)

질문: **비서에게 무엇을 시킬까, 비서는 뭐라고 했나?**

- 화면 위 50px을 남기고 올라오는 시트(반지름 16, 위 손잡이). 위에 "닫기" · "비서" · "앱 대화". 아래로 끌거나 "닫기"로 닫는다.
- 메시지: 내 글은 오른쪽 검정 말풍선, 비서 글은 왼쪽 말풍선 없는 본문(15px). 시각은 대화가 바뀔 때와 10분 넘게 비었을 때만 가운데 회색으로.
- **다른 곳에서 바뀐 것**: 시트를 열 때 이 대화의 마지막 메시지 뒤에 `channel != app`인 활동이 있으면(`GET /activity?since=`), 맨 아래에 회색 칸 한 줄 "다른 곳에서 바뀐 것: " 뒤에 `GET /activity` 항목의 `summary` 한 줄을 그대로 붙인다(항목에는 `summary`뿐이라 틀로 할 일 제목을 쓰지 않는다). 최대 3줄. 두뇌도 같은 알림을 받는다(SP3-4 7.1).
- **확인 문구**: `data-activity.confirmation`(예: "✓ 추가: 치과 → 10월 25일", 12장 R4b)을 회색 칸으로 그리고, 같은 조각의 `undo_ids`가 있으면 칸 오른쪽에 "되돌리기".
- **상태**: `data-status`가 `queued`면 "비서가 앞의 일을 끝내는 중이에요", `thinking`이면 점 세 개(움직임 줄이기 설정이면 멈춘 점). 15초 핑은 보이지 않는다.
- **조각**: `ui_*` 도구 조각은 7장 부품으로, 비서 글 사이 제자리에 그린다. 그 밖의 도구 조각(`add_task` 등)은 그리지 않는다(확인 문구가 대신한다).
- 입력: 아래 고정, 한 줄 입력 + 보내기(40px). 보내는 동안 보내기 버튼은 "멈춤"이 아니라 꺼진다(BE는 중간에 멈추지 않는다, 6.4.1 끊김 규칙). `/`로 시작하는 글은 그대로 보낸다(BE가 명령으로 처리).
- 두뇌 하루 상한, 사용 한도, 로그인 문제는 BE가 고정 문구 글로 보내므로 앱은 따로 처리하지 않는다.

#### 5.5.3 체크인 상세 (`/checkin/?id=`)

질문: **비서가 무엇을 물었고, 나는 무엇을 답하면 되나?**

| 블록 | 데이터 | 동작 |
|---|---|---|
| "‹ 오늘" + 오른쪽 상태 글 "답장할 수 있어요" · "{앱 \| 텔레그램}에서 답했어요" · "지나감" | `state`, `answered_via` | |
| 큰 제목 = 회차 이름(SP3-4 부록 A 그대로: 아침 브리핑, 저녁 체크인, 주간 회고, 다시 이어서) + "{HH:MM}에 보냄 · {앱 알림으로 받음 \| 텔레그램으로 받음}" | `loop`, `sent_at`, `delivered_via` | |
| 회차 본문 | `text` | |
| 카드들 | `cards` (컨디션 고르기, 초안, 사다리, 영역 점수, 확인) | 7장 부품 |
| 남은 할 일 | `/today.todos` 중 열린 것 (저녁 체크인일 때만) | "내일로"(`move_task`, 날짜는 `addDays(/today.date, 1)`), "완료"(`complete_task`). 이미 끝난 것은 회색 "완료"(어느 통로에서 끝냈는지는 기록 화면에서 본다) |
| 답장 입력 | | `POST /chat` with `checkin_id`. 보낸 뒤 시트가 아닌 이 화면 아래로 답이 이어진다(같은 `ChatSheet` 부품을 화면 안에 넣는다) |

- `state = answered`여도 카드는 그대로 쓸 수 있다(답장 창 안이면 대화도 이어진다, SP3-4 6.4.5).
- `state = missed`면 "지나감"만 보이고 답장 입력은 그대로 둔다(BE가 일반 대화로 받는다, 7.2). 압박 문구를 쓰지 않는다.

#### 5.5.4 오늘 · 비서 오프라인

오늘 화면과 같은 배치에 아래만 다르다.

- 맨 위 안내 칸(`--notice-*`): "**노트북의 비서에 닿지 않아요.** 아래는 {HH:MM}에 받은 내용이고, 지금은 볼 수만 있어요." + "다시 연결"(즉시 `/health`) · "연결 확인"(설정).
- 스냅샷이 없으면: "아직 받아 둔 내용이 없어요. 노트북이 켜지면 보여 드릴게요."
- 체크박스는 빈 원 그림으로 바뀌고(입력 아님), 컨디션 알약과 카드의 버튼은 꺼진다(`disabled` + 이유 글).
- 아침 브리핑이 아직 오지 않은 시각이면 "노트북이 켜지면 지나간 체크인부터 차례로 따라잡아요."(SP1 따라잡기 규칙의 쉬운 말).
- "비서에게 말하기"는 "비서가 다시 연결되면 말할 수 있어요"로 바뀌고 눌리지 않는다.

#### 5.5.5 할 일 (`/todos/`)

질문: **이번 기간에 무엇이 중요하고, 무엇이 남았나?**

- 큰 제목 "할 일" + 오른쪽 추가 버튼(44px 원, 검정).
- 기간 탭(분할 버튼): 오늘 · 이번 주 · 이번 달 · 분기 · 올해. 기본은 이번 주.

| 탭 | 블록 | 데이터 |
|---|---|---|
| 오늘 | 오늘 화면의 할 일 그룹과 같음 | `GET /today` |
| 이번 주 | 이번 주 우선순위(끝난 것은 체크 표시만, 개수나 비율은 보이지 않는다. P4) · 날짜별 할 일(빈 날은 접은 한 줄 "{요일} · 없음") | `GET /week` |
| 이번 달 · 분기 · 올해 | 그 기간 우선순위 | `GET /priorities?cadence=` (**12장 추가 요청**) |
| (모든 탭 아래) | 초안 (n) "확정하면 할 일이 돼요" | `GET /drafts` (**12장 추가 요청**) |

- 줄 동작: 체크 = 완료/다시 열기. **왼쪽으로 밀기** = "내일로"(회색, `move_task` planned_for = `addDays(/today.date, 1)`) · "빼기"(빨강, `drop_task`). 밀기를 못 쓰는 경우를 위해 줄을 길게 누르면 같은 두 동작과 "날짜 바꾸기", "제목 고치기"가 담긴 메뉴가 뜬다(접근성).
- `drop_task`에 BE가 `needs_confirm`을 주면(그 할 일이 지금 기간 우선순위이거나 열린 첫 걸음이 있을 때, SP3-4 6.4.2) 줄 아래로 확인 시트: `summary` + "그대로 두기" · "바꾸기". `move_task`도 같다: 시각이 잡힌 할 일의 날짜를 바꾸면 BE가 `needs_confirm`을 주고(SP6 8장, BE-2. 앱 통로에만, 텔레그램 버튼은 바로 적용) "내일로"(할 일·오늘·체크인 화면)와 "날짜 바꾸기"가 같은 확인 시트를 거친다. 시각이 없는 할 일은 바로 적용된다.
- 초안 줄: "빼기"(`drop_task`) · "확정"(`confirm_tasks`). 여러 개면 묶음 위에 "모두 확정".
- **추가 시트**: 제목(필수), 영역(6개 중 여러 개, 알약), 날짜(오늘·내일·날짜 고르기·없음. "오늘"은 `/today.date`, "내일"은 `addDays(/today.date, 1)`), 시각(선택), 메모(선택). "추가" = `add_task`. 우선순위 지정은 v1에서 대화로만 한다(비서가 `set_priorities`).

#### 5.5.6 기록 (`/activity/`)

질문: **비서와 내가 무엇을 바꿨고, 되돌릴 것이 있나?**

- 큰 제목 "기록" + 회색 한 줄 "비서와 내가 바꾼 것. 가벼운 변경은 24시간 안에 되돌릴 수 있어요."
- **확인이 필요해요**(있을 때만, 맨 위): 오늘 화면 3번과 같은 출처. 테두리 1.5px `--hue`. 남은 시간은 보이지 않는다(P2).
- 날짜 묶음(오늘, 어제, 그 전은 "10월 22일"): 각 줄은 `summary` 한 줄 + 회색 "{HH:MM} · {비서 \| 나} · {앱 대화 \| 앱 \| 텔레그램 \| 아침 브리핑 등 회차 이름}". 비서가 한 줄은 앞에 6px `--hue` 점.
- 오른쪽: `undo_id`가 있으면 "되돌리기"(32px 회색 알약). 되돌린 줄(`undone_at`)은 취소선 + "{HH:MM}에 되돌림". `undo_id`가 없는 그 밖의 줄은 오른쪽에 아무것도 두지 않는다(목록 응답에는 이유가 없다). 되돌리기를 눌렀는데 `409`/`422`가 오면 그 줄만 이유 글로 바뀐다(F8).
- 더 보기: 처음 50줄(최근 것부터), 끝에서 다음 50줄(12장 R4a).
- 되돌리기 응답의 `confirmation`("↩ 되돌림: 운동 완료")은 알림 줄로 보인다.

#### 5.5.7 설정 (`/settings/`)

| 묶음 | 줄 | 데이터·동작 |
|---|---|---|
| 비서 연결 | 상태(점 + "연결됨 · {방금 \| n분 전} 확인") · 주소(가운데 줄임) · 열쇠(토큰) "다시 입력" | `/health`, `mp.*` |
| 체크인 알림 | "어디로 울릴까요" 분할 버튼 이 앱 · 텔레그램 + 설명 "한 곳에서만 울려요. 앱 알림이 안 가면 텔레그램으로 대신 보내요." · 실제 상태(`effective`가 다르면 "지금은 텔레그램으로 가요: 알림을 받을 기기가 없어요") · 이 기기 알림 켜짐/꺼짐/허용하기 · "시험 알림 보내기" | `GET/PUT /settings/notify`, `/push/*` |
| 체크인 시간 | 평일 09:00 · 17:30, 주말 10:00 · 18:00 (읽기 전용) + "일요일 18:00은 주간 회고와 함께 와요. 시간은 노트북의 비서 설정에서 바꿔요." | v1은 앱 상수(SP1 기본값). **12장 요청 3**이 들어오면 `/health`에서 읽는다 |
| 쉬어 가기 | "체크인 잠시 멈추기" 줄. 멈추지 않았으면 누를 때 시트에서 1일 · 3일 · 7일 · 14일을 고른다. 멈췄으면 "{M}월 {D}일 {HH:MM}까지 쉬는 중" + "다시 시작" | 고르기 = `/chat`으로 `/pause N`(SP1: 1~14일, 아침 브리핑·저녁 체크인·주간 회고를 멈춤), 다시 시작 = `/unpause`(BE 명령, SP3-4 6.4.1). 대화 시트 없이 보내려고 `chat/command.ts`의 `sendCommand`가 새 id로 `/chat`에 보내고 스트림을 읽어 버린 뒤 `/health`를 다시 본다. 그 명령과 답은 앱 대화 기록에 남는다. 상태는 `/health.paused_until`. 멈춘 동안에도 말을 걸면 답한다는 SP1 문구가 BE 답으로 온다 |
| 이 기기 | 화면(시스템 따라 · 밝게 · 어둡게. 5.2의 미디어 쿼리 토큰에 `:root[data-theme="light"]`·`:root[data-theme="dark"]` 두 벌을 더하고, 고른 값은 `localStorage` `mp.theme`에 둔다. 인라인 스크립트를 쓸 수 없어 `data-theme`는 첫 그림 뒤에 바뀔 수 있다. 받아들인다) · "이 기기 연결 해제"(빨강 글자, 확인 시트: "이 폰에 저장된 주소, 열쇠, 받아 둔 내용이 지워져요") | 4.7 |
| 정보 | 앱 판, BE 판(`/health.version`), 부품 목록 판 | |

#### 5.5.8 처음 연결 (`/connect/`)

- 큰 제목 "노트북의 비서와 연결해요" + "한 번만 하면 돼요. 주소와 열쇠는 이 폰에만 저장되고 어디에도 올라가지 않아요."
- 비서 주소(`type="url"`, 도움말: "노트북에서 tailscale serve를 켠 뒤 나오는 주소예요. 폰에서도 Tailscale이 켜져 있어야 해요."), 열쇠(`type="password"`, 도움말: "노트북에서 python -m my_planner gen-token으로 만든 값이에요.").
- 입력이 끝나면(포커스가 떠나면) 자동으로 `/health`를 불러 결과 한 줄: "연결 확인됨 · 비서가 답했어요" / "열쇠가 맞지 않아요" / "주소에 닿지 않아요. 노트북과 폰의 Tailscale을 확인해 주세요."
- "알림 허용하고 시작하기"(검정 50px) = 푸시 구독 후 오늘 화면. "알림은 나중에" = 바로 오늘 화면.
- 아이폰 Safari 탭에서 열었으면(`navigator.standalone !== true`이고 iOS) 입력 칸 대신 안내만 보인다: "공유 버튼에서 ‘홈 화면에 추가’를 한 뒤, 홈 화면의 ‘비서’를 열어 연결해 주세요. 탭과 홈 화면 앱은 저장 공간이 따로라서, 여기서 넣은 값은 앱으로 넘어가지 않아요." 컴퓨터 브라우저(시험용)에서는 입력 칸을 보이고 첫 버튼은 "시작하기"(알림 없이)다.

## 6. 생성형 UI의 규칙

- 비서는 **카탈로그 안의 부품만** 쓴다(D10). 앱은 시작할 때와 `/health.version.ui_catalog`가 바뀔 때 `GET /ui/catalog`를 받아 IndexedDB에 둔다.
- 조각마다: (1) 이름이 레지스트리에 있는가, (2) `input`(props)이 받은 카탈로그의 JSON Schema에 맞는가(`@cfworker/json-schema`, 4.3. CSP 아래에서 돈다). 둘 다 맞으면 그 부품, 아니면 `UnknownPart`(회색 칸 "이 화면 조각은 아직 앱이 그릴 줄 몰라요" + props의 `title`/`question`/`summary`가 있으면 그 글).
- 할 일을 보여 주는 부품(`ui_todo_list`, `ui_todo_draft`)은 props의 `task_ids`만으로는 제목을 모른다. BE가 조각마다 지금 값을 붙여 준다(12장 R4c: 대화의 `tool-output-available.output.data.todos`, 체크인 `cards[].data.todos`, 오늘 `cards[].data.todos`는 이미 있음). 앱은 `data`가 없으면 "할 일 {n}개" 한 줄로 대신 보인다.
- 부품은 **그리기와 버튼만** 한다. 버튼은 SP3-4 6.4.7 표의 동작(`/actions`, 또는 `/chat`에 새 메시지) 외의 일을 하지 않는다. 부품이 직접 상태를 바꾸지 않고, 응답 뒤 그 화면의 `GET`을 다시 부른다.
- 같은 부품이 대화, 오늘 화면 고정 카드, 체크인 카드 세 곳에서 똑같이 보인다(한 컴포넌트).
- 하네스가 만든 조각(`toolCallId`가 `h_`로 시작)과 두뇌가 만든 조각은 생김새가 같다. 다른 점은 고정 카드의 `--hue` 표시뿐이다.
- 텔레그램에는 `ui_*`가 가지 않는다(SP3-4 6.4.7). 같은 회차를 텔레그램에서 보면 버튼 줄로 보이는 것이 정상이다.

## 7. 부품 목록 (카탈로그 `2026-10-24.2`)

| 이름 | 출처 | 생김새 | 누르면 |
|---|---|---|---|
| `ui_todo_list` | 두뇌 | 흰 그룹: 제목(15/600) + 할 일 줄(최대 30, 6줄 넘으면 "n개 더") | 체크 = `/actions complete_task` |
| `ui_choice` | 두뇌 | 질문 글 + 알약 버튼 2~4개(44px, 회색 테두리. SP6 6.1에서 36px → 44px) | 고른 `label`을 새 사용자 메시지로 `/chat`. 고른 뒤 버튼은 고른 것만 검정으로 남고 꺼진다 |
| `ui_summary_card` | 두뇌 | 흰 그룹: 제목 + 줄 최대 8개(15px, 줄 사이 6px) | 없음 |
| `ui_todo_draft` | 하네스 | 테두리 그룹 "할 일 초안" + 회색 "확정 전까지 초안이에요" + 체크 줄(기본 모두 체크) + "고른 것 빼기" · "{n}개 확정" | 확정 = `confirm_tasks`(체크한 것), 빼기 = 체크한 것마다 `drop_task` |
| `ui_condition_picker` | 하네스 | 1~5 알약 + 양끝 "많이 지침", "아주 좋음" + 선택 메모 칸 | `record_condition` (메모는 칸을 떠날 때 같은 동작으로 다시) |
| `ui_ladder_picker` | 하네스 | 0~10 알약 두 줄(6 + 5) + "지금" 또는 "5년 뒤" 설명 | `record_ladder_score` |
| `ui_area_scores` | 하네스 | 6개 영역 줄마다 1~10 분할 버튼, 지난 점수 회색 | 영역마다 고른 뒤 "저장" = `record_area_scores` |
| `ui_milestone_draft` | 하네스 | 테두리 그룹 "사건 초안" + 사건 줄(제목, 연월) + "빼기" · "확정" (줄마다) | `confirm_milestones` / `drop_milestone` |
| `ui_chapter_draft` | 하네스 | 테두리 그룹 "챕터 초안" + 챕터 줄(제목, 기간) + "빼기" · "확정" (줄마다) | `confirm_chapters` / `drop_chapter` |
| `ui_confirm` | 하네스 | 테두리 1.5px `--hue` 그룹: `summary` + "그대로 두기" · "바꾸기" | 바꾸기 = `/actions {action, args, confirm_token}`(새 `client_msg_id`), 그대로 두기 = `decline_confirm`. `409`(만료, 이미 처리)면 "이미 지나간 확인이에요"로 바뀐다 |

- 영역 이름은 용어집의 6개를 그대로 쓴다: 커리어, 경제, 건강, 관계, 배움, 삶의 질.
- **시안과 다른 점**: 시안의 고정 카드 "이번 주 운동"은 요일 막대를 그렸지만, v1 카탈로그에는 그런 부품이 없다. v1에서는 같은 내용이 `ui_summary_card`(줄 목록)로 보인다. 요일 막대 부품은 미결 3.

## 8. 기능 설계

각 기능의 흐름, 부르는 API, 지켜야 할 규칙이다. API 모양은 SP3-4 6장을 따른다.

### F1. 연결과 설치

1. `/connect/`에서 주소·토큰 입력 → `GET /health`(10초). `200`이면 `mp.beUrl`, `mp.token`, `mp.lastHealthOk` 저장.
2. 알림 허용을 고르면 F7의 구독 흐름.
3. `GET /ui/catalog`를 받아 둔다.
4. 오늘 화면으로.

규칙: 주소 끝의 `/`와 `/api/v1`은 앱이 정리한다(사용자는 `https://gp76.xxx.ts.net`만 넣어도 된다). `http://`는 받지 않는다(CSP, 혼합 콘텐츠).

### F2. 연결 감시

- `/health`를 앱이 보이는 동안 30초마다, 앞으로 올 때 즉시 부른다. 다른 요청의 네트워크 오류도 바로 오프라인으로 친다. 결과로 5.4의 상태 하나를 정해 모든 화면에 알린다.
- 오프라인에서 연결됨으로 바뀌면 지금 화면의 `GET`을 다시 부르고, 알림 줄 "다시 연결됐어요"를 2초 보인다.

### F3. 오늘

- 읽기: `GET /today`(+ 대기 체크인마다 `GET /checkins/{id}`로 `ui_confirm` 모으기).
- "내일"은 논리적 날짜의 다음 날, 곧 `addDays(/today.date, 1)`이다(00:00~04:00에는 기기 달력과 논리적 날짜가 다르다). 앱은 기기 달력으로 날짜를 만들지 않는다.
- 쓰기: `complete_task`, `reopen_task`, `move_task`, `drop_task`, `record_condition`, `unpin_card`, `reorder_cards`.
- 비서가 카드를 바꾸면(대화 중 `pin_card` 등) 대화 시트를 닫을 때 오늘 화면을 다시 읽는다.

### F4. 대화

- `useChat({ transport, onData, resume: false })`, `transport = new DefaultChatTransport({ api: <BE>/api/v1/chat, headers: () => ({ Authorization }), prepareSendMessagesRequest })`. `prepareSendMessagesRequest`는 `{client_msg_id: 마지막 사용자 메시지.id, conversation_id, checkin_id, message: 마지막 사용자 메시지}`만 본문으로 만든다(SP3-4 6.4.1). 사용자 메시지 id는 `generateId` 대신 UUID v4로 만든다.
- 메시지 조각 처리(`chat/parts.ts`): `text` → 본문, `tool-ui_*`(또는 `dynamic-tool`의 `toolName`이 `ui_`로 시작) + 상태 `input-available` 이상 → 부품, 그 밖의 `tool-*` → 그리지 않음, `data-activity` → 확인 칸(`confirmation`)과 되돌리기 id(12장 R4b). 일시 조각 `data-status`는 `message.parts`에 남지 않으므로 `onData`에서 받아 상태 줄로 쓴다.
- `ui_*` 조각을 받으면 `localParts`에 `{messageId, parts}`로 저장.
- 재요청: 스트림 오류(네트워크)면 `regenerate()`로 한 번(같은 사용자 메시지 id = 같은 `client_msg_id`). 두 번째도 안 되면 "다시 받기" 버튼(같은 방법).
- 13장 계약 테스트: BE 티켓 06이 만드는 기준 SSE는 앱으로 복사하지 않는다. 저장소의 `tests/fixtures/app_golden/`을 시험이 바로 읽어 이 파서로 화면 결과를 확인한다. 두 쪽이 늘 같은 파일을 본다.

### F5. 체크인

- 열기: 오늘 화면의 대기 줄, 푸시 알림. 기록 화면의 회차 이름은 링크로 두지 않는다(활동 항목에 회차 id가 없다. 필요하면 BE에 `run_id`를 요청한다).
- 읽기: `GET /checkins/{id}`, 저녁 체크인이면 `GET /today`도.
- 답장: `POST /chat` + `checkin_id`. 카드 버튼은 7장.
- 답장 창이 이 화면을 보는 동안 끝나면 오른쪽 위가 "지나감"으로 바뀐다(앱 시계로 `reply_until` 비교, 다음 읽기에서 BE 값으로 맞춘다).

### F6. 할 일

- 읽기: 탭별(5.5.5). 쓰기: `add_task`, `update_task`, `move_task`, `complete_task`, `reopen_task`, `drop_task`, `confirm_tasks`. "오늘"과 "내일"은 `/today.date`와 `addDays(/today.date, 1)`로 만든다(기기 달력을 쓰지 않는다).
- `needs_confirm` 응답: 확인 시트에서 "바꾸기"면 같은 `action`, `args`에 `confirm_token`을 넣고 **새 `client_msg_id`**로 보낸다(같은 id면 BE가 처음의 `needs_confirm` 응답을 그대로 돌려준다, 6.1 중복 방지). 10분 지나 `409`면 "확인 시간이 지났어요. 다시 해 주세요."
- `needs_confirm`이 오는 쓰기: `drop_task`(우선순위·열린 첫 걸음), `move_task`(시각이 잡힌 할 일의 날짜 바꾸기, SP6 8장). 오늘·체크인 화면의 "내일로"도 같은 시트를 쓴다.

### F7. 알림

- 구독: `Notification.requestPermission()` → `granted`면 `GET /push/vapid-public-key` → `registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey})` → `POST /push/subscriptions` → `mp.pushId`.
- 거절(`denied`)이면 설정에 "알림이 꺼져 있어요. 아이폰 설정 › 알림 › 비서에서 켤 수 있어요."
- 앱을 열 때마다 `pushManager.getSubscription()`이 비었는데 `mp.pushId`가 있으면(아이폰이 구독을 지운 경우) 다시 구독하고 같은 `endpoint`면 BE가 같은 id를 준다.
- 주 통로 바꾸기: `PUT /settings/notify {primary}` → 응답의 `effective`를 보여 준다.
- 서비스 워커 `push`: `showNotification(title, {body, tag: checkin_id ? "run-" + checkin_id : "notice", data: {url: url ?? "/"}})`. `notificationclick`: `url`을 4.5 규칙으로 바꾼 뒤, 열린 앱 창이 있으면 `focus()` + `postMessage({navigate: url})`(앱 라우터가 이동. iOS가 `WindowClient.navigate`를 지원하는지에 기대지 않는다), 없으면 `clients.openWindow(url)`. 실기기 체크리스트에서 두 경우를 모두 확인한다.
- 앱이 열려 있을 때 온 푸시는 알림을 띄우고, 오늘 화면이면 다시 읽는다(`postMessage`).

### F8. 기록과 되돌리기

- 읽기: `GET /activity?order=desc&limit=50`, 이어 받기 `before=<next_before>`(12장 R4a). R4a가 들어오기 전에는 `since=<7일 전>&limit=200`을 `next_since`로 끝까지 받아 기기에서 뒤집는다(1인 사용이라 7일치가 수백 줄 안쪽). 대기 체크인의 `ui_confirm`도.
- 되돌리기: `POST /activity/{id}/undo`. `200 undone` → 알림 줄 + 다시 읽기. `already_undone` → 다시 읽기만. 그 줄의 오른쪽 글을 바꾼다(오류 줄 없음): `409 superseded` → "뒤에 또 바뀌어서 못 되돌려요", `409 undo_expired` → "24시간이 지났어요", `422 not_undoable` → "되돌릴 수 없는 변경이에요".
- **알림 줄**(모든 화면 공통): 쓰기 응답의 `confirmation`을 4초 보이고, `undo_id`가 있으면 "되돌리기". 줄이 떠 있는 동안 다른 쓰기가 오면 새 것으로 바뀐다.

### F9. 오프라인 읽기

- 연결 상태가 오프라인이면 오늘·할 일 화면은 스냅샷을 읽어 5.5.4처럼 보인다. 이번 주 탭만 스냅샷이 있고, 이번 달·분기·올해·초안은 "비서가 연결되면 보여 드릴게요."
- 기록, 체크인 상세, 대화는 스냅샷이 없다: 화면 틀 + "비서가 연결되면 보여 드릴게요." 대화 시트는 `localParts`와 마지막으로 본 글(메모리)이 있으면 보여 주고 입력을 막는다.

## 9. 성능과 접근성

- 첫 화면: 아이폰에서 홈 화면 앱을 열고 1초 안에 틀과 스냅샷이 보이고, 연결되면 2초 안에 새 데이터로 바뀐다(Tailscale 지연 포함, 목표치). 자바스크립트 묶음은 첫 화면 기준 180KB(gzip) 이하.
- 터치 영역 44px 이상(작은 알약 32px은 줄 전체가 아닌 보조 동작에만, 줄 사이 8px 이상).
- 모든 버튼은 `<button>`, 이동은 `<a>`. 아이콘만 있는 버튼은 `aria-label`. 줄 밀기에는 길게 누르기 메뉴라는 대안이 있다. 시트는 열릴 때 초점을 시트 안으로, 닫힐 때 연 버튼으로 돌린다.
- 색만으로 뜻을 전하지 않는다: 연결 점 옆에 늘 글, 비서 표시 점 옆에 "비서" 글.
- 글자 크게 보기(동적 글꼴)를 따른다: 크기는 `rem`, 줄 높이는 최소값으로 둔다.

## 10. 문구

- 말투: 존댓말 "-요". 짧게. 압박, 평가, 재촉하지 않는다.
- **금지어**: SP1 5.4 "문구 규칙"의 정본 목록(`harness/prompts/system.md`의 `banned-words` 블록) "밀렸다", "놓쳤다", "실패", "놓쳤어요", "밀렸어요", "늦었지만"에 앱 화면용으로 "연속", "스트릭", "달성률"을 더한다(ADR 0006). 13장 테스트가 `src/`의 모든 한국어 문자열을 검사한다. 지나간 회차는 "지나감", 보내지 못한 것은 "안 갔어요"라고 쓴다.
- 고정 문구는 `src/lib/copy.ts` 한 곳에 둔다. 화면 코드에 한국어 문장을 직접 쓰지 않는다(검사를 한 곳에서 하기 위해).
- 회차 이름: SP3-4 부록 A와 SP1 부록 A의 이름을 그대로 쓴다.

## 11. 배포

- Vercel 프로젝트 하나: 루트 `web/app`, 빌드 `npm run build`, 출력 `out`, 환경 변수 `NEXT_PUBLIC_CONNECT_SRC=https://*.<tailnet>.ts.net` 하나(토큰·주소 없음), 분석 끔.
- BE `config.toml`의 `api.cors_origins`에 앱 주소(`https://<앱>.vercel.app`)를 더한다(SP3-4 15장).
- `manifest.webmanifest`: `name` "비서", `short_name` "비서", `display` `standalone`, `start_url` `/`, `theme_color` `#f2f2f5`, `background_color` `#f2f2f5`, 아이콘 192·512 + `apple-touch-icon` 180. 아이콘은 검정 바탕에 흰 획의 "비" 한 글자를 그린 정사각형(앱 고유 표시, 그라데이션 없음).
- `vercel.json`: 모든 경로에 `Cache-Control`은 Vercel 기본값, `sw.js`만 `no-cache`.

## 12. BE 계약에 더할 것 (SP3-4 스펙에 티켓 21a로 반영)

| # | 추가 | 이유 | 상태 |
|---|---|---|---|
| R1 | `GET /api/v1/priorities?cadence=week\|month\|quarter\|year&period=` → `{cadence, period, items: [Todo]}` (rank 순) | 할 일 화면의 이번 달·분기·올해 탭 | 수락됨, 티켓 02에서 구현(2026-10-24) |
| R2 | `GET /api/v1/drafts` → `{items: [{todo, proposed_at, expires_at, run_id, conversation_id}]}` | 할 일 화면의 초안 묶음. 지금은 초안이 어떤 `GET`에도 나오지 않는다(6.3) | 수락됨, 6.3 규칙도 고침, 티켓 02(2026-10-24) |
| R3 | `/health`에 `schedule: {weekday: ["09:00","17:30"], weekend: ["10:00","18:00"]}` | 설정 화면의 체크인 시간을 앱 상수 대신 실제 값으로 | v1 이후, 요청 전 |

| R4a | `GET /activity`에 `order=desc`(기본 `asc` 그대로)와 `before=<ISO>` 커서, 응답 `next_before` | 기록 화면은 최근 것부터 본다. 지금은 오래된 것부터만 준다(6.4.4) | 받음(2026-10-24, SP3-4 21a, 티켓 05) |
| R4b | `/chat`의 `data-activity`에 `confirmation`(확인 문구, 글). 앱 통로에서는 확인 문구를 `h-confirm` 글 조각으로 보내지 않는다 | AI SDK 5의 글 조각(`TextUIPart`)에는 스트림 id가 남지 않아 확인 문구를 다른 글과 가를 수 없다 | 받음(2026-10-24, SP3-4 21a, 티켓 06·10) |
| R4c | 할 일을 가리키는 `ui_*` 조각(`ui_todo_list`, `ui_todo_draft`)에 `/today.cards`처럼 지금 값 `data.todos`를 붙인다: 대화는 `tool-output-available.output = {"ok": true, "data": {"todos": [Todo]}}`, 체크인은 `cards[].data` (초안 할 일은 `status: draft`) | props가 `task_ids`뿐이라 대화·체크인에서 제목을 알 길이 없다 | 받음(2026-10-24, SP3-4 21a, 티켓 02·09) |
| R4d | `GET /conversations/{id}/messages` 항목에 `id`(비서 줄은 그 답의 SSE `start.messageId`, 사용자 줄은 받은 `message.id`) | 기기에 둔 화면 조각을 다시 붙일 열쇠 | 받음(2026-10-24, SP3-4 21a, 티켓 02) |

R1, R2, R4a가 들어오기 전에는: 해당 경로가 `404`면 그 탭과 묶음을 숨기고, 기록은 F8의 대체 방법을 쓴다. R4b가 없으면 확인 문구 칸 없이 글로만 보이고 되돌리기는 알림 줄과 기록 화면에서 한다. R4c가 없으면 "할 일 {n}개" 한 줄(6장). R4d가 없으면 다시 연 대화에 조각이 붙지 않는다.

## 13. 테스트

| 층 | 무엇 | 도구 | 통과 기준 |
|---|---|---|---|
| 단위 | `api/client`(토큰 붙이기, 10초 시간 제한, 오류 모양 → `ApiError`), `lib/connection` 상태 판정 표(5.4), 주소 정리(F1), 4.5 주소 바꾸기, `snapshot` 7일 만료 | Vitest | `npx vitest run src/lib src/api` → `0 failed` |
| 대화 계약 | 저장소의 `tests/fixtures/app_golden/`(BE 티켓 06의 기준 SSE, 앱에 복사하지 않음)를 `useChat` + `parts.ts`로 읽어: 글, `data-activity` 확인 칸 + 되돌리기, `ui_todo_draft` 부품, `onData`의 `data-status` 상태 줄, 대화 id(`start` 메타데이터). 끊김 뒤 `regenerate()`가 같은 `client_msg_id`를 보냄 | Vitest + MSW(SSE 응답) | `npx vitest run src/chat` → `0 failed` |
| 부품 | 7장 10개 부품: props로 그려짐, 누르면 정확한 `/actions` 본문, 스키마 틀린 props → `UnknownPart`, 모르는 이름 → `UnknownPart` | Testing Library + MSW | `npx vitest run src/ui` → `0 failed` |
| 화면 | 오늘(정상, 할 일 0개, 오프라인 + 스냅샷, 오프라인 + 스냅샷 없음, `401`, `503`), 할 일 탭 5개, 기록(되돌리기 성공·`superseded`·만료), 설정(주 통로 바꾸기 `effective` 다름), 처음 연결(성공, `401`, 닿지 않음) | Testing Library + MSW | `npx vitest run src/screens` → `0 failed` |
| 문구 | `src/lib/copy.ts`와 `src/**/*.tsx`의 한국어 문자열에 10장 금지어 없음 | Vitest | `npx vitest run src/lib/copy.test.ts` → `0 failed` |
| 대비 | 5.2 토큰의 글자·면 쌍(밝게, 어둡게) 모두 4.5:1 이상 | Vitest(대비 계산) | `npx vitest run src/styles` → `0 failed` |
| 빌드 | 정적 내보내기, CSP(인라인 스크립트·스타일 없음) | `npm run build && npm run check:csp` | `CSP OK: <n> files` |
| CSP 실행 | 빌드한 `out/`을 CSP 헤더와 함께 띄우고, 고정 SSE로 대화를 열어 `ui_todo_draft` 조각이 부품으로 그려지는지(검사기가 CSP 아래에서 도는지), 콘솔에 CSP 위반이 없는지. 원인을 가르기 쉽게 시험 둘로 나눈다(조각 그리기, 위반 0건) | Playwright | `npx playwright test csp.spec.ts` → `2 passed` |
| 디자인 | taste 규칙 | `node <taste>/scripts/lint.mjs --app web/app/src` | `0 FAIL` |
| 눈으로 | 390×844에서 화면 8개 스크린샷(밝게·어둡게)을 시안과 나란히 보고 다른 곳을 고친다 | Playwright + MSW 고정 데이터 | `npx playwright test` → 16장 저장, 사람이 확인 |
| 실기기 | 아이폰에서 Safari 탭 안내 확인 → 홈 화면 추가 → 연결 → 시험 알림 → 앱이 닫혀 있을 때와 열려 있을 때 각각 알림 눌러 체크인 열기 → 답장 → 텔레그램 버튼 사라짐 확인 | Dahun과 함께 | 체크리스트 `docs/acceptance/sp5-checklist.md` 모든 줄 확인 |

## 14. 확정된 사항 (Dahun, 2026-10-24 "추천대로")

1. **오프라인 스냅샷**(4.7): 오늘·이번 주 할 일과 체크인 요약을 폰에 7일 남긴다(D12, ADR 0009). 대시보드는 아무것도 남기지 않는다.
2. **탭 4개**: 오늘·할 일·기록·설정.
3. **요일 막대 부품**: v1에는 넣지 않는다. 요일별 진행은 `ui_summary_card`로 보이고, 쓰다가 아쉬우면 `ui_week_strip`을 BE 스펙 6.4.7에 더한다.
4. **체크인 멈추기**: 설정에서 1·3·7·14일 중 고른다(속으로는 `/pause N`, `/unpause`).
5. 코드 위치 `web/app/`, 앱 이름 "비서", 아이콘 "비" 한 글자.

## 변경 기록

| 날짜 | 판 | 내용 | 누가 |
|---|---|---|---|
| 2026-10-24 | v1 | 첫 초안: 질문 10개의 결정, 청사진, 화면 8개, 부품 8개, 기능 9개, BE 계약 추가 요청 3개 | 운영 앱 스레드 |
| 2026-10-24 | v2 | 문서 리뷰 반영: CSP 아래 도는 검사기, 기록 최근순(R4a), 확인 문구·할 일 제목·메시지 id(R4b~d), 카탈로그 `.2`(사건·챕터 초안), AI SDK 5 사용법(`onData`, `regenerate`, `resume` 끔), 확인 재요청은 새 id, 마감 시각·남은 시간·완료 개수 표시 뺌(P2, P4), 회차 이름 "다시 이어서", 오프라인 판정, CSP·헤더를 대시보드와 맞춤, Safari 탭과 홈 화면 앱의 저장 공간 분리, 알림 누름 대체 경로 | 운영 앱 스레드 |
| 2026-10-24 | v3 | 14장 미결 사항 다섯 가지를 추천대로 확정, R4a~d를 SP3-4가 받음 | Dahun |
| 2026-10-24 | v4 | 구현 계획의 결정(빈 곳 1~14) 반영 | 운영 앱 스레드 |
| 2026-10-24 | v5 | SP6 G-A2: 앱의 `move_task`도 시각 있는 할 일이면 확인 시트를 거친다(5.5.5, F6. SP6 8장) | 운영 앱 스레드 |

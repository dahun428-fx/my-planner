# SP6 운영 앱 대화의 생성형 UI 넓히기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰하고, 지적을 반영한 뒤 다음 티켓으로 간다.

**Goal:** 운영 앱 대화 시트에서 비서가 미리 만든 부품 조각(기본 부품 10개, 완성 카드 7개, 조립 카드 `ui_block`)을 골라 내놓게 한다. AI는 화면 코드를 쓰지 않고, 버튼은 다섯 가지 일만 하며, 할 일은 id로만 가리키고 BE가 붙인 지금 값으로 그린다.

**Architecture:**
- 조각의 길은 지금 그대로다: 두뇌 `mcp__planner__ui_*` → 하네스가 카탈로그 스키마·쌓기 규칙·뜻 검사·한 답 상한을 본 뒤 `tool-input-available.input`(props)과 `tool-output-available.output.data`(지금 값)를 스트림에 쓴다 → 앱 `parts.ts` → `UiPart`(이름 → 카탈로그 스키마 → `ui_block`만 `checkBlock`) → 컴포넌트. 스펙 4.1 그림 그대로.
- 계획은 **두 스레드의 세로 티켓**이다. 앱 티켓 `G-A*`는 운영 앱 스레드(이 계획을 실행하는 쪽), BE 티켓 `G-BE*`는 **SP3-4 BE 스레드**가 따로 받아 PR로 한다. BE 티켓은 그대로 넘겨줄 수 있는 독립 브리프로 썼다.
- 내보내는 순서(스펙 14장): **G-BE1과 G-A1을 나란히** → G-A2(새 카드, Vercel 배포) → **G-A2가 배포된 뒤에만** G-BE2(두뇌에게 새 도구) → G-A3(기준 SSE 계약·눈으로). 그래서 Dahun은 어느 순간에도 앱이 그릴 수 없는 조각을 받지 않는다.
- G-A0은 SP3-4 티켓 15(경험치)가 들어온 뒤의 타입 다시 만들기와 확인 문구 둘째 줄 처리다. **완료 (PR #113)**. 기록으로만 남긴다.

**Tech Stack:** 지금 `web/app` 그대로(Next.js 15 Pages Router 정적 내보내기, React 19, `ai` 5 + `@ai-sdk/react`, `@cfworker/json-schema`, CSS Modules, Vitest + Testing Library + MSW + jsdom, Playwright). **새 의존성 없음**(`parseMiniMd`는 정규식 한 번, 진행 막대는 `<progress>`). BE: Python 3.12, Pydantic 2(지금 판), pytest, ruff 0.17.

**Spec:** [`docs/superpowers/specs/2026-10-24-sp6-chat-generative-ui-design.md`](../specs/2026-10-24-sp6-chat-generative-ui-design.md) (v2, main `2b0b50f`). 상위: [SP5 스펙](../specs/2026-10-24-sp5-ops-app-design.md) 5~7장·9장, [SP3-4 스펙](../specs/2026-10-24-sp3-4-life-curve-dashboard-design.md) 6.3·6.4.1·6.4.2·6.4.7·10장(API 계약 정본). 앞 계획: [SP5 계획](2026-10-24-sp5-ops-app.md), [SP3-4 계획](2026-10-24-sp3-4-life-curve-dashboard.md).
- 스펙과 이 계획이 다르면 스펙이 맞다. 이 계획이 스펙의 빈 곳을 정한 자리는 끝의 "스펙 빈 곳과 이 계획의 결정"에 모았고, 표의 "반영" 칸의 티켓 PR이 스펙에 옮긴다.
- 티켓은 스펙을 다시 쓰지 않는다. "6.3 그대로"처럼 절을 가리키고, 시그니처·시험·스펙에 없는 결정만 적는다.

## Global Constraints

스펙의 문장을 그대로 옮긴다(절 번호). 모든 티켓의 요구 사항에 들어간다.

**CSP와 스타일 (스펙 5.1, 11.3, SP5 4.7)**
- "인라인 `style` 속성을 쓰지 않는다. 진행 막대는 `<progress>` 요소로 그려 폭을 계산해 넣을 일이 없다." 컴포넌트에 `style={{…}}`, `<style>`, 인라인 `<script>`가 없다.
- "모든 CSS는 `_app`과 함께 나간다(PR #107 규칙: Pages Router가 화면 이동 때 쪽 CSS를 인라인 `<style>`로 붙여 `style-src 'self'`에 막힌다)." 새 CSS 파일은 `src/pages/_app.tsx`에서 가져온다. `npm run check:csp`는 쪽 단위 스타일시트(`data-n-p`)가 있으면 `page-level stylesheet`로 실패한다. 대화 묶음의 자바스크립트는 늦게 읽혀도 CSS는 처음부터 한 장에 있다.
- 조각 검사는 `@cfworker/json-schema`. `ajv`, `eval`, `new Function`, props로 정하는 동적 `import()`는 없다.

**크기 (스펙 11.7, SP5 9장)**
- 첫 화면 자바스크립트는 gzip **180KB 이하**(`npm run size`, 실패 기준). SP6이 더하는 몫은 6KB 이하. 넘으면 기존 넷이 쓰지 않는 부품(`Stat`, `Progress`, `Tags`, `Group`)을 대화 묶음으로 옮긴다.
- 새 완성 카드 넷(`ui/chat/`, `ui/block/`)은 대화 묶음에서만 등록한다(첫 화면 묶음에 넣지 않는다).

**색과 글 (스펙 5.1)**
- 의미 토큰(`--surface`, `--text`, `--text-2`, `--muted`, `--raised`, `--rule`, `--border`, `--primary`, `--on-primary`, `--hue`)만. 16진수 색, 영역별 색, 프리셋 이름에 기대는 규칙이 없다. **SP6은 새 토큰을 만들지 않는다.**
- **나란히 들어오는 색 프리셋 티켓**(운영 앱 스레드, `:root[data-palette]` 6벌 × `data-theme` 밝게·어둡게 = 12벌)이 `tokens.css`를 바꾼다. SP6 CSS는 토큰 이름만 쓰므로 고칠 것이 없다. 프리셋 12벌에 걸친 대비 시험과 스크린샷 12장은 그 티켓이 병합된 뒤 G-A3에서 켠다(스펙 13장 끝).
- `--hue`는 비서가 한 일에만: `ui_period_list`의 바뀐 줄 막대와 `ui_result`의 바뀜 알약. 숫자, 진행 막대, 버튼에는 쓰지 않는다.
- 크기 30 / 16 / 15 / 13 / 11, 굵기 400·600(700은 화면 제목 전용), 숫자 `tabular-nums`. 터치 영역 44px(`ui_result`의 "되돌리기" 알약 32px은 스펙 6.3 그대로이고 누르는 영역은 44px로 넓힌다).
- props의 글은 모두 React 글 마디로 넣는다. `dangerouslySetInnerHTML` 없음. 앱은 글자 수를 다시 재지 않고 스키마만 믿는다.
- **마크다운 컴포넌트는 나란히 들어온다**: 운영 앱 스레드의 다른 티켓이 `markdown-to-jsx`로 `src/components/Markdown.tsx`를 더해 비서의 **답 글**을 그린다. 이 계획은 그것을 다시 계획하지 않는다. 조각 안의 글(`text.md`)은 그것을 쓰지 않고 `parseMiniMd`(`**`와 `\n`만)로 그린다(스펙 5.3.2, 12장). 둘 다 `chat/MessageView.tsx`를 고치므로 G-A2는 그 티켓이 먼저 병합됐으면 그 위로 다시 얹는다.

**문구 (스펙 부록 A, SP5 10장)**
- 화면의 한국어 문장은 모두 `src/lib/copy.ts`(`npm run lint:copy`). 새 문구는 부록 A 그대로(Dahun 확인 필요 표시는 부록 A에 이미 있다).
- 금지어: `system.md`의 `banned-words` 블록 + "연속", "스트릭", "달성률". 비율(%)을 보이지 않는다.

**비밀과 쓰기 (SP5 4.6~4.7, 스펙 6.5, 8장, 12장)**
- **토큰은 화면에 그리지 않고 로그에 남기지 않는다.** `console.*`에 토큰, 메시지 본문, 할 일 제목, props를 쓰지 않는다. BE 도구 오류 문구와 시스템 로그에 props 값이 없다(위치와 코드만). 시험 고정 자료는 꾸며 낸 내용만.
- **다시 연 대화(`restored`)와 오프라인(`readOnly`) 조각은 읽기 전용이다**: 체크, 확정, 되돌리기, 이어 말하기가 꺼지거나 없고, 앱 화면 열기(`open`)만 된다(6.5 표 그대로). `restored` 메시지에는 `hideCoveredActivity`를 쓰지 않는다.
- 버튼은 8장 다섯 가지(`complete`, `confirm`, `undo`, `send`, `open`)만. 쓰기에 들어가는 값은 BE가 붙인 id(`data.todos[].id`, `data.todo.id`, `data.items[].undo_id`)와 스키마로 범위를 확인한 날짜 후보뿐이다. 앱은 `ActionName`을 props에서 읽지 않는다.
- 쓰기는 지금의 `useAction`·`useUndo`·`usePartAction`만 지난다(두 번 누르기 막기, `client_msg_id` 규칙 그대로).

**BE (스펙 10장, ADR 0005)**
- 화면 도구는 그리기만 한다: DB, 파일, `ctx.events`를 건드리지 않는다. 두뇌가 받는 결과는 `{"ok": true}`, `data`는 스트림에만.
- 텔레그램 대화에는 `ui_*` 도구가 없다. 도구 수 시험은 절대 수가 아니라 "G-BE1 전후 같음", "G-BE2에서 +4"로 쓴다(9.3).
- 카탈로그 판은 **병합될 때 다음 판**(`YYYY-MM-DD.n`, 10.5). SP6에서 판을 올리는 PR은 G-BE1 하나다.

## 작업 방식

- **앱 티켓**: 모든 명령은 `cd web/app` 뒤에 돈다. 슬라이스마다 시험 하나 → `npx vitest run <파일> -t "<이름>"`으로 FAIL(새 이름은 import 오류, 새 동작은 assertion) → 구현 → 같은 명령으로 PASS.
- **앱 티켓 끝 검증(공통)**: `npx vitest run` → `0 failed`, `npm run test:tz` → `0 failed`, `npm run typecheck` → 코드 0, `npm run lint:copy` → 코드 0, `NEXT_PUBLIC_CONNECT_SRC='https://*.example.ts.net' npm run build && npm run check:csp` → `CSP OK: …`, `npm run size` → 코드 0(앞뒤 KB를 PR 설명에), `npm run e2e` → 지금 시험이 모두 `passed`. 그다음 `code-reviewer` 리뷰, 커밋.
- **BE 티켓 끝 검증(공통)**: 저장소 루트에서 `python -m pytest -q` → `0 failed`(Linux에서 Windows 전용은 `skipped`), `ruff check src tests` → `All checks passed!`. 노드 하나는 `python -m pytest <파일>::<시험> -v` → `1 passed`.
- 시험 날짜: 오늘 = **2026-10-24(토)**(`data.today`, `/today.date`). 이번 주 = `2026-W43`(10/19~10/25), 다음 주 = `2026-W44`(10/26~11/1).
- 공유 고정 자료 `tests/fixtures/ui_props/`와 기준 SSE `tests/fixtures/app_golden/`는 BE가 만들고 앱 시험이 **제자리에서** 읽는다(복사하지 않는다, SP5 빈 곳 7과 같은 방식). 앱 쪽 경로는 `src/` 기준 `../../../tests/fixtures/…`(지금 `e2e/routes.ts`의 `GOLDEN`과 같은 방식).
- BE 스키마가 바뀌면 `npm run gen:types`로 `src/api/schema.json`과 `types.gen.ts`를 다시 만들고, `src/test/fixtures/catalog.json`은 저장소 루트에서 `python -c "import json; from my_planner.tools.ui import catalog; print(json.dumps(catalog(), ensure_ascii=False, indent=2))" > web/app/src/test/fixtures/catalog.json`로 다시 만든다.

## Review Focus

스펙이 암시하지만 13장 시험 표가 다루지 않고, 쓰다가 먼저 부딪힐 다섯 가지. 시험은 맡은 티켓에 있다.

1. **확인 문구의 둘째 줄**: SP3-4 티켓 15 뒤 확인 문구 끝에 `"\n레벨 {N}이 됐어요."`가 붙을 수 있다. 알림 줄과 회색 확인 칸이 그 줄을 한 줄로 뭉개거나 잘라 내지 않고 둘째 줄로 보인다. 새 활동 종류(`xp_granted_by_secretary`, `rest_days_granted`)가 기록 화면을 `shape` 오류로 만들지 않는다. → G-A0에서 이미 시험함(PR #113: `Toast.test.tsx`, `MessageView.test.tsx`, `Activity.test.tsx`)
2. **긴 글과 좁은 화면**: 40자 제목, 16자 버튼 이름 셋, `group row`의 `stat` 셋이 390px(그리고 320px) 폭에서 가로 스크롤 없이 접힌다(`row`는 340px 아래 한 줄에 하나). → G-A1 `primitives.css.test.ts`, G-A3 `screens.spec.ts`(`scrollWidth <= 390`)
3. **날짜 후보를 누르는 사이 할 일이 바뀜**: 그린 뒤 다른 곳에서 완료·삭제·시각이 잡힌 할 일의 후보를 누르면 `rejected`(이유 알림 줄, 버튼 다시 켜짐) 또는 `needs_confirm`(확인 시트)이고, 할 일이 조용히 옮겨지지 않는다. → G-A2 `DateChoice.test.tsx`, G-BE2 `test_app_move_task_scheduled_needs_confirm`
4. **같은 메시지에 같은 할 일의 카드가 둘**: 두뇌가 한 답에 `ui_result`와 `ui_period_list`를 함께 그렸을 때(상한 2) 확인 칸 숨김은 `ui_result`만 본다. `ui_result` 둘이 같은 활동을 덮어도 확인 칸이 한 번만 숨는다. → G-A2 `hideCoveredActivity.test.ts`
5. **대화 밖에서 온 새 이름**: 오늘 화면의 고정 카드나 체크인 카드에 새 이름(`ui_block` 등)이 오면(있어서는 안 된다) 대화 묶음을 아직 읽지 않았어도 `UnknownPart`로 보이고 멈추지 않는다. 대화를 한 번 연 뒤에도 고정 카드 자리의 동작은 같다(새 넷은 고정되지 않는다). → G-A2 `registerChatParts.test.tsx`, G-BE1 `test_pin_card_rejects_new_components`

---

## File Structure

```
web/app/src/
  ui/
    primitives/        # G-A1 · 첫 화면 묶음(기존 넷이 쓴다)
      CheckRow.tsx Heading.tsx MiniText.tsx Stat.tsx Progress.tsx TodoRows.tsx Tags.tsx
      Bullets.tsx Buttons.tsx Divider.tsx Group.tsx parseMiniMd.ts dates.ts types.ts
      primitives.module.css  *.test.tsx  primitives.css.test.ts
    components/        # 기존 넷(TodoList, TodoDraft, Choice, SummaryCard)을 primitives로 다시 짬 (G-A1)
                       # Part.tsx의 CheckRow는 primitives/CheckRow.tsx로 옮긴다
    chat/              # G-A2 · 대화 묶음
      DateChoice.tsx Result.tsx PeriodList.tsx cards.module.css registerChatParts.ts *.test.tsx
    block/             # G-A2 · 대화 묶음
      Block.tsx checkBlock.ts renderElement.tsx sharedProps.test.ts checkBlock.test.ts Block.test.tsx
    openScreen.ts      # G-A2: OpenScreen → 주소
    registry.tsx  types.ts  usePartAction.ts   # 고침 (G-A2)
  chat/  parts.ts  hideCoveredActivity.ts  MessageView.tsx  ChatSheet.tsx   # 고침/새 (G-A2)
  lib/copy.ts  pages/_app.tsx  styles/contrast.test.ts  scripts/size.mjs   # 고침
  screens/ Today.tsx Checkin.tsx EditTodoSheet.tsx todoActions.tsx         # "내일로"·날짜 바꾸기 확인 시트 (G-A2)
  e2e/ csp.spec.ts screens.spec.ts routes.ts                              # G-A3
src/my_planner/                                   # G-BE1, G-BE2 (BE 스레드)
  tools/ui.py  tools/core.py  tools/mcp_adapter.py  tools/actions.py  store/views.py  api/models.py
  harness/prompts/channel_app.md  domain.py(RunContext.ui_drawn)
tests/
  fixtures/ui_props/<컴포넌트>/{ok,bad}/*.json     # G-BE1
  fixtures/app_golden/chat_{date_choice,result,period_list,block,ui_rejected,gallery}.sse   # G-BE2
  test_ui_catalog.py (새, G-BE1)  test_ui_tools.py  test_period_view.py (새, G-BE2)  test_app_golden.py
docs/acceptance/sp6-checklist.md                  # G-A3
```

- 스펙 11.1 폴더 그대로에 더한 것: `primitives/{dates,types}.ts`(날짜 표시와 부품 타입을 한 곳에), `ui/openScreen.ts`, `chat/hideCoveredActivity.ts`(순수 함수 한 파일), 시험 파일.

## 티켓 지도

| # | 티켓 | 맡는 곳 | 막는 티켓 | 라벨 |
|---|---|---|---|---|
| G-A0 | 경험치 뒤 타입 다시 만들기, 확인 문구 둘째 줄 | 운영 앱 스레드 | SP3-4 티켓 15 병합 | **완료 (PR #113)** |
| G-BE1 | 카탈로그: 모델·쌓기 규칙·글 검사·판·공유 props 자료 | **BE 스레드** | 없음 (BE 티켓 15 뒤, 16 앞) | `ready-for-agent` |
| G-A1 | 기본 부품 10개 + `CheckRow`, 기존 넷 다시 짜기 | 운영 앱 스레드 | 없음 (G-BE1과 나란히) | `ready-for-agent` |
| G-A2 | 새 카드 넷, 레지스트리, 확인 칸 숨김, `onOpen`, 확인 시트 | 운영 앱 스레드 | G-BE1, G-A1 | `ready-for-agent` + **Vercel 배포** |
| G-BE2 | 두뇌에게 주기: 도구 넷, 지금 값, 상한, `move_task` 확인, 프롬프트, 기준 SSE | **BE 스레드** | G-A2가 Vercel에 배포됨 | `ready-for-agent` + `needs-laptop`(S12만) |
| G-A3 | 기준 SSE 계약, CSP 실행, 스크린샷 26장, 대비, 실기기 | 운영 앱 스레드 | G-BE2, (프리셋 줄은) 색 프리셋 티켓 | `ready-for-agent` + `needs-laptop` + **Dahun** |

- **나란히**: G-BE1과 G-A1은 서로 기다리지 않는다(G-A0은 끝났다). G-A2는 G-BE1의 공유 props 자료와 카탈로그가 있어야 스키마 시험을 쓸 수 있다.
- **배포 문**: main의 G-A2 병합 커밋(또는 그 뒤 커밋)의 GitHub 커밋 상태 `Vercel`이 `success`(`gh api repos/dahun428-fx/my-planner/commits/<sha>/status --jq '.statuses[] | select(.context=="Vercel") | .state'` → `success`. 클라우드 컨테이너는 vercel.app에 닿지 않으므로 화면이 아니라 이 상태로 본다)을 운영 앱 스레드가 확인해 조정자에게 알린다. 그 뒤에만 BE 스레드가 G-BE2를 병합한다.
- **BE 티켓 넘겨주기**: G-BE1·G-BE2 절은 그대로 BE 스레드에 브리프로 보낸다. 각 절의 "맥락"과 "브리프에 함께 가는 규칙", Global Constraints의 **BE** 묶음, 스펙이면 충분하다. BE 스레드는 PR 번호와 카탈로그 판을 조정자에게 알린다.

---

### 티켓 G-A0: 경험치 뒤 타입 다시 만들기, 확인 문구 둘째 줄 — 완료 (PR #113)

**목표:** SP3-4 티켓 15가 더하는 `/actions` 응답의 `xp: {gained, level_up: int | null}`, 확인 문구 끝의 `"\n레벨 {N}이 됐어요."`, 활동 종류 `xp_granted_by_secretary`·`rest_days_granted`, 대화 스트림의 `grant_xp` 도구 조각을 앱이 깨지지 않고 받는다(Review Focus 1).
**막는 티켓:** SP3-4 티켓 15 병합(그 전에는 시작하지 않는다)
**맡는 곳:** 운영 앱 스레드

**Files:**
- Modify: `src/api/{schema.json,types.gen.ts}`(다시 만듦), `src/components/Toast.module.css`, `src/chat/ChatSheet.module.css`(`.activityText`), `src/test/fixtures/activity-desc-1.json`(새 종류 한 줄씩)
- Test: `src/components/Toast.test.tsx`, `src/chat/MessageView.test.tsx`, `src/chat/parts.test.ts`, `src/screens/Activity.test.tsx`, `src/api/actions.test.tsx`, `src/api/fixtures.test.ts`

**Interfaces:**
- Consumes: BE `python -m my_planner schema`(티켓 15 뒤), `parseApplied`(지금 `api/actions.ts`)
- Produces: 바뀌는 시그니처 없음. `ActionOutcome.applied.confirmation`은 여러 줄일 수 있는 글이다(앱은 자르지 않는다). `xp`는 읽지 않는다(지금 화면에 경험치 표시 없음).

- [x] **Step 1: `npm run gen:types`** → `git diff --stat src/api`가 `schema.json`, `types.gen.ts`뿐. `npx vitest run src/api/fixtures.test.ts` → 깨지는 고정 자료가 있으면 고친다(꾸며 낸 값).
- [x] **Step 2: 시험을 쓴다.**
  - `Toast.test.tsx` `shows level-up line on its own line`: `show({text: "✓ 완료: 운동\n레벨 3이 됐어요."})` → `getByRole("status")`의 `textContent`가 두 줄을 모두 담고, 글 칸의 클래스가 `white-space: pre-line` 규칙을 가진다(`Toast.module.css`를 읽어 그 클래스 블록에 `pre-line`).
  - `MessageView.test.tsx` `activity confirmation keeps second line`: 같은 문구의 `activity` 조각 → `[data-activity]` 안 글에 `"레벨 3이 됐어요."`.
  - `parts.test.ts` `grant_xp tool part is hidden`: `tool-grant_xp` 조각 → `toViewParts` 결과에 없음.
  - `actions.test.tsx` `applied with xp field parses`: 응답 `{status: "applied", activity_id: 9, undo_id: 9, confirmation: "✓ 완료: 운동\n레벨 3이 됐어요.", result: {}, xp: {gained: 10, level_up: 3}}` → `kind: "applied"`, `confirmation` 그대로.
  - `Activity.test.tsx` `new xp kinds render as rows`: 고정 자료의 `xp_granted_by_secretary`, `rest_days_granted` 줄이 `summary`로 보이고 화면에 `shape` 오류 글이 없다.
- [x] **Step 3: FAIL을 본 뒤 구현**: 두 CSS 클래스에 `white-space: pre-line`. 나머지는 Step 1로 이미 통과해야 한다(통과하지 않으면 그 모델 검사를 고친다).
- [x] **Step 4: 티켓 끝 검증**(작업 방식, 앱) → **Review + Commit** `chore(app): regenerate API types after XP and keep the level-up line`

---

### 티켓 G-BE1: 카탈로그 — 모델, 쌓기 규칙, 글 검사, 판, 공유 props 자료

> **맡는 곳: BE 스레드 (SP3-4 BE 스레드).** 이 절은 그대로 넘겨주는 브리프다. SP3-4 티켓 15 뒤, 16 앞에 한다.

**맥락:** 운영 앱 대화의 화면 조각을 넓힌다(SP6 스펙). 이 티켓은 **카탈로그만** 바꾼다: 새 조각 넷(`ui_date_choice`, `ui_result`, `ui_period_list`, `ui_block`)의 props 모델과 JSON Schema, `ui_block`의 쌓기 규칙 B1~B9, 모든 두뇌 조각의 글 검사, `TodoRef`의 필드 둘, 다음 카탈로그 판, 앱과 함께 쓰는 고정 자료. **두뇌에게는 아직 주지 않는다**: 앱이 그릴 수 있게 된 뒤(G-A2 배포) G-BE2가 준다. 그래서 이 PR 뒤에도 앱 대화 도구 목록은 그대로다.
**막는 티켓:** 없음
**브리프에 함께 가는 규칙:**
- 끝 검증: 저장소 루트에서 `python -m pytest -q` → `0 failed`(Linux에서 Windows 전용은 `skipped`), `ruff check src tests` → `All checks passed!`. 노드 하나는 `python -m pytest <파일>::<시험> -v` → `1 passed`.
- 공유 고정 자료(`tests/fixtures/ui_props/`, `tests/fixtures/app_golden/`)는 BE가 만들고 앱 시험이 제자리에서 읽는다. 앱으로 복사하지 않으며 꾸며 낸 내용만 넣는다.
- (Review Focus 5) 새 넷은 고정 카드가 되지 않는다: `pin_card`는 `PINNABLE_COMPONENTS` 셋만 받는다.
- (빈 곳 3) `todo_rows.checkable`의 기본값은 `true`.
- (빈 곳 9) 후보 날짜의 오늘~90일 범위는 스키마가 아니라 G-BE2의 뜻 검사가 본다(스키마는 형식·개수·서로 다름만).
- (빈 곳 10) `model_validator` 규칙 가운데 정수 목록의 서로 다름은 JSON Schema `uniqueItems`로도 내보내고, `period_one`, `value_over_max`, 후보 날짜 `not_unique`는 BE 전용이다(앱 공유 시험이 건너뛴다).

**스펙 절:** 5장(부품 표의 상한), 6.2~6.4(props 표), 7.1~7.2, 10.1, 10.3, 10.5, 10.6 첫 항목, 부록 B, 12장, 13장 "BE 스키마" 줄

**Files:**
- Modify: `src/my_planner/tools/ui.py`, `src/my_planner/tools/mcp_adapter.py`(`APP_ONLY_TOOLS`, `pin_card` 스키마 `enum`), `src/my_planner/tools/core.py`(`Tools.pin_card`의 검사와 오류 문구가 `BRAIN_COMPONENTS` 대신 `PINNABLE_COMPONENTS`), `src/my_planner/store/views.py`(`todo_ref`), `src/my_planner/api/models.py`(`TodoRef`), `GLOSSARY.md`(기본 부품, 완성 카드, 조립 카드), SP3-4 스펙 6.3(`TodoRef` 예시와 설명), SP6 스펙 5.3.5·7.2·10.1(빈 곳 3·9·10)
- Create: `tests/test_ui_catalog.py`, `tests/fixtures/ui_props/{ui_date_choice,ui_result,ui_period_list,ui_block,ui_todo_list,ui_choice,ui_summary_card}/{ok,bad}/*.json`
- Test: `tests/test_ui_catalog.py`, `tests/test_ui_tools.py`, `tests/test_api_schema.py`(`test_ui_catalog_version_and_components`의 박힌 값: 판 `"2026-10-24.2"` → 새 판, 컴포넌트 10개 → 14개 순서, 두뇌 3개 → 7개), `tests/test_cards.py`

**Interfaces:**
- Produces (`tools/ui.py`):
  - 모델(모두 `_Props`): `DateCandidate{date: str(YYYY-MM-DD 형식만), note: str 1~12 | None}`, `DateChoiceProps{task_id: int, question: str 1~60, candidates: list[DateCandidate] 2~4}`(날짜가 서로 다름은 `model_validator`, 오늘~90일 범위는 **G-BE2의 뜻 검사**: 스키마는 시계를 모른다), `ResultProps{task_ids: list[int] 1~2, 서로 다름}`, `PeriodListProps{day: str | None, week: str(^\d{4}-W\d{2}$) | None, highlight_task_ids: list[int] 0~30 = []}`(`day`·`week` 꼭 하나: `model_validator`, 코드 `period_one`), `BlockProps{title: str 1~40, children: list[Element] 1~12}`.
  - 부품: `HeadingEl{type: "heading", text 1~40}`, `TextEl{type: "text", md 1~280}`, `Delta{text 1~8, trend: "up"|"down"|"same"}`, `StatEl{type: "stat", label 1~16, value 1~10, delta: Delta | None}`, `ProgressEl{type: "progress", label 1~16, value: int ≥0, max: int 1~100}`(`value > max`는 `model_validator`, 코드 `value_over_max`), `TodoRowsEl{type: "todo_rows", task_ids: list[int] 1~10 서로 다름, checkable: bool = True}`, `TextTag{text 1~12}`·`AreaTag{area: AreaName}`, `TagsEl{type: "tags", items 1~6}`, `BulletsEl{type: "bullets", items: list[str 1~80] 1~6}`, `SendDo{kind: "send"}`·`OpenDo{kind: "open", screen: Literal["today","todos_day","todos_week","todos_month","activity","settings"]}`·`CompleteDo{kind: "complete", task_id: int}`(`kind`로 가름), `Button{label 1~16, do}`, `ButtonsEl{type: "buttons", items: list[Button] 1~3}`, `DividerEl{type: "divider"}`, `RowGroup{type: "group", layout: "row", children: list[StatEl | ProgressEl] 2~3}`, `StackGroup{type: "group", layout: "stack", children: list[Inner] 2~6}`(`Inner` = `group`·`buttons`를 뺀 부품의 `type` 구분 유니언), `GroupEl = Annotated[Union[RowGroup, StackGroup], Field(discriminator="layout")]`, `Element = Annotated[Union[HeadingEl, …, DividerEl, GroupEl], Field(discriminator="type")]`(10.1의 두 단계).
  - "서로 다름"(`candidates[].date`, `task_ids`, `highlight_task_ids`, `todo_rows.task_ids`)은 `model_validator`가 코드 `not_unique`로 본다. 정수 목록 셋에는 JSON Schema `uniqueItems: true`도 붙인다(`json_schema_extra`, 앱 검사기가 같은 값 둘을 거른다). `day`·`week` 하나만(`period_one`), `value > max`(`value_over_max`), 날짜만 같은 후보(`not_unique`)는 JSON Schema에 나오지 않는 BE 전용 판정이다(빈 곳 10).
  - 길이는 Pydantic `max_length`(코드 포인트)로만. `model_validator(mode="after")`가 `BlockProps`의 B1, B4~B8을 보고 `PydanticCustomError(code, …)`로 7.2 표의 `code`를 낸다.
  - `_COMPONENTS`: 기존 두뇌 셋 뒤, 하네스 앞에 새 넷 `"brain"`. `BRAIN_COMPONENTS`는 7개. 새 상수 `PINNABLE_COMPONENTS = ("ui_todo_list", "ui_choice", "ui_summary_card")`.
  - `APP_BANNED_WORDS = ("연속", "스트릭", "달성률")`, `banned_words() -> tuple[str, ...]`(`harness/prompts/system.md`의 `banned-words` 블록 + `APP_BANNED_WORDS`, 한 번 읽어 캐시).
  - `validate_props(component, props) -> str | None`: 순서 (1) 스키마·쌓기 규칙 (2) B9 `json.dumps(props, ensure_ascii=False).encode()` > 8192 → `too_large` (3) 두뇌 조각 일곱의 모든 글 값에 10.3의 `bad_char`·`banned_word`·`slash`(`slash`는 `SendDo` 버튼 이름과 `ui_choice` `options[].label`만). 돌려주는 글은 `"{위치}: {code}"`(쌓기 규칙 B1, B4~B8과 `period_one`·`value_over_max`·`not_unique`는 위치 `props`), 7.2·10.3의 새 `code`면 뒤에 `" ({부록 B 한 마디})"`. 값은 넣지 않는다. 하네스 조각에는 (3)을 하지 않는다.
- Produces (그 밖):
  - `mcp_adapter.APP_ONLY_TOOLS = [*PINNABLE_COMPONENTS, "pin_card", "unpin_card", "reorder_cards"]`, `pin_card` 입력 스키마의 `component.enum = list(PINNABLE_COMPONENTS)`, `tools/core.py`의 `Tools.pin_card`도 `PINNABLE_COMPONENTS` 밖이면 도구 오류(문구의 이름 목록도 셋). `call_tool`의 `ui = name in BRAIN_COMPONENTS`는 그대로.
  - `todo_ref(...)`와 API `TodoRef`에 `planned_for: date | None`(논리적 날짜), `scheduled_at`. `todo_ref`는 다른 필드처럼 현지 시각을 내고, API·스트림 경계의 `to_api_times`가 **UTC**(`Z`)로 바꾼다(SP3-4 6.1). 고정 카드·체크인 카드도 같은 모양.
  - `UI_CATALOG_VERSION`: 병합하는 날의 다음 판(지금 `2026-10-24.2` → 예: `2026-10-2x.1`. 같은 날 습관 기록의 `ui_habit_check` PR이 먼저 들어갔으면 그다음 `n`).
  - 공유 자료: 컴포넌트마다 `ok/` 하나 이상, `bad/<code>-<설명>.json`. `ui_block/ok/`에는 부품 10개가 모두 나오는 `all-elements.json`과 7.1 예시. `ui_block/bad/`에는 B1~B9의 `code`마다 하나 이상(B2·B3은 `union_tag_invalid-*`, `union_tag_not_found-*`, `too_short-*`). 새 넷과 기존 두뇌 셋의 `bad/`에 `bad_char-*`(제어 문자, 방향 문자 각각), `banned_word-*`, `slash-*`(해당되는 곳). 모든 파일은 꾸며 낸 내용, 들여쓰기 2, UTF-8.

- [ ] **Step 1: `tests/test_ui_catalog.py`를 쓴다.**
  - `test_shared_ok_fixtures_pass`: `tests/fixtures/ui_props/*/ok/*.json` 매개변수 → `validate_props(dir, json) is None`.
  - `test_shared_bad_fixtures_fail_with_code`: `bad/<code>-*.json` 매개변수 → 결과에 `f": {code}"`가 있다.
  - `test_every_block_rule_has_bad_fixture`: `ui_block/bad/`의 파일 이름 앞부분 집합 ⊇ `{"block_too_many", "union_tag_invalid", "buttons_place", "todo_rows_too_many", "divider_place", "block_no_content", "complete_not_in_rows", "too_large"}`.
  - `test_all_elements_fixture_uses_ten_types`: `ui_block/ok/all-elements.json`에서 모은 `type` 집합 == 10개.
  - `test_error_text_has_no_values`: 제목 `"비밀제목XYZ"`를 넣은 `bad` 조각들의 오류 글에 `"비밀제목XYZ"`가 없다.
  - `test_new_codes_have_korean_hint`: 쌓기 규칙 오류는 `model_validator(mode="after")`라 위치가 비어 `props`가 된다(따로 위치를 만들지 않는다). `block_too_many` 오류 == `"props: block_too_many (부품은 모두 12개까지예요)"`, `buttons_place` == `"props: buttons_place (버튼 줄은 하나만, 맨 끝에 둬요)"`.
  - `test_text_md_allows_four_newlines_only`: `\n` 4개 → 통과, 5개 → `bad_char`. 다른 글의 `\n` → `bad_char`. `"\u202e"` → `bad_char`.
  - `test_banned_words_read_from_system_md`: `"놓쳤어요" in banned_words()`, `"달성률" in banned_words()`.
  - `test_slash_rejected_for_send_and_choice`: `send` 이름 `"/pause 3"` → `slash`, `open` 이름 `"/x"`는 통과(보내지 않으므로), `ui_choice` `label` `"/today"` → `slash`.
  - `test_period_list_needs_exactly_one`: 둘 다 → `period_one`, 둘 다 없음 → `period_one`.
  - `test_distinct_lists`: `task_ids: [53, 53]`, 같은 날짜 후보 둘 → `not_unique`. `UI_COMPONENTS["ui_result"]["schema"]`의 `task_ids`에 `"uniqueItems": true`.
  - `test_app_tool_count_unchanged`(절대 수가 아니라 이름 집합): `set(tool_names_for("app")) - set(TOOL_NAMES) == {"ui_todo_list", "ui_choice", "ui_summary_card", "pin_card", "unpin_card", "reorder_cards"}`, 새 넷은 `tool_names_for("app")`에 없다.
  - `test_pin_card_rejects_new_components`(Review Focus 5): `pin_card(component="ui_block", …)` → 도구 오류, `CardsRepo.active() == []`.
  - `test_ok_fixtures_pass_json_schema`: `ok/*.json`마다 `jsonschema.Draft202012Validator(UI_COMPONENTS[name]["schema"]).is_valid(props)`가 `True`(앱 `@cfworker/json-schema`와 같은 초안. Pydantic만 통과하는 자료를 막는다).
  - `test_catalog_schema_uses_nested_oneof`: `UI_COMPONENTS["ui_block"]["schema"]`의 `group` 정의가 `layout`별 `const`를 가진 `oneOf` 둘.
- [ ] **Step 2: `python -m pytest tests/test_ui_catalog.py -v`** → FAIL(새 이름 `ImportError`/고정 자료 없음).
- [ ] **Step 3: 모델과 검사를 `tools/ui.py`에, 공유 자료를 `tests/fixtures/ui_props/`에 만든다.** `ok` 자료는 앱 `@cfworker/json-schema`도 통과해야 한다: `$defs` 참조와 `oneOf`만 쓰고 Pydantic 전용 키워드에 기대지 않는다(앱이 G-A2에서 같은 파일로 확인한다. 다르면 조정자를 거쳐 알려 온다).
- [ ] **Step 4: `python -m pytest tests/test_ui_catalog.py -v`** → 모두 PASS.
- [ ] **Step 5: `TodoRef` 필드 둘.** `tests/test_ui_tools.py::test_todo_ref_has_dates_in_utc`(할 일 `planned_for=2026-10-25`, `scheduled_at` KST 14:00 → `to_api_times(todo_ref(...))`가 `{"planned_for": "2026-10-25", "scheduled_at": "2026-10-25T05:00:00Z", …}`. `GET /today`의 `cards[].data.todos`로도 한 번), `tests/test_api_schema.py`의 `TodoRef` 필드 시험 → FAIL → 구현 → PASS. SP3-4 스펙 6.3 예시를 고친다.
- [ ] **Step 5b: 앱 쪽 판정 맞추기(병합 전)**: PR을 연 뒤 조정자를 거쳐 운영 앱 스레드에 PR 가지를 알린다. 운영 앱 스레드가 G-A2의 `src/ui/block/sharedProps.test.ts`(먼저 쓴 가지)를 이 PR 가지의 `tests/fixtures/ui_props/`와 카탈로그로 돌려 `0 failed`를 알려 온 뒤에 병합한다. 다르면 이 PR에서 자료나 스키마를 고친다.
- [ ] **Step 6: `GLOSSARY.md`**에 "기본 부품", "완성 카드", "조립 카드"(스펙 1장 표의 뜻 한 줄씩).
- [ ] **Step 7: 티켓 끝 검증**(BE) → `python -m my_planner schema | python -c "import json,sys; print(json.load(sys.stdin)['models']['TodoRef']['properties'].keys())"`에 `planned_for`, `scheduled_at` → **Review + Commit** `feat(ui): SP6 catalog — blocks, date choice, result and period list schemas` → PR. 병합 뒤 조정자에게 PR 번호와 카탈로그 판을 알린다(운영 앱 스레드가 G-A2에서 `gen:types`와 `catalog.json`을 다시 만든다).

---

### 티켓 G-A1: 기본 부품 10개와 `CheckRow`, 기존 넷 다시 짜기

**목표:** 스펙 5장의 기본 부품 10개와 `CheckRow`를 `ui/primitives/`에 만들고, 기존 `ui_todo_list`, `ui_todo_draft`, `ui_choice`, `ui_summary_card`를 그 부품으로 다시 짠다(6.1). 보이는 차이는 `ui_choice` 알약 36px → 44px 하나. BE 변경 없이 배포할 수 있다.
**막는 티켓:** 없음 (G-BE1과 나란히)
**맡는 곳:** 운영 앱 스레드

**Files:**
- Create: `src/ui/primitives/{CheckRow,Heading,MiniText,Stat,Progress,TodoRows,Tags,Bullets,Buttons,Divider,Group}.tsx`, `src/ui/primitives/{parseMiniMd,dates,types}.ts`, `src/ui/primitives/primitives.module.css`
- Modify: `src/ui/components/{Part,TodoList,TodoDraft,Choice,SummaryCard}.tsx`(`CheckRow`를 `Part.tsx`에서 빼고 `primitives/CheckRow`를 쓴다. DraftRows는 체크 줄이 없어 그대로), `src/ui/components/parts.module.css`(옮긴 규칙 지움), `src/pages/_app.tsx`(`import "../ui/primitives/primitives.module.css"`), `src/lib/copy.ts`(부록 A 가운데 부품이 쓰는 것), `src/styles/contrast.test.ts`, `package.json`(`test:tz`에 `dates.test.ts`), SP5 스펙 7장 표의 `ui_choice` "36px" → "44px", SP6 스펙 5.3.2·5.3.5·6.1·12장(빈 곳 1·2·5·12)
- Test: `src/ui/primitives/{parseMiniMd.test.ts, dates.test.ts, CheckRow.test.tsx, elements.test.tsx, Buttons.test.tsx, primitives.css.test.ts}`, 기존 `src/ui/components/*.test.tsx`(고치지 않고 통과)

**Interfaces:**
- Consumes: `PartTodo`, `PartContext`(`ui/types.ts`), `copy`, `copy.areas`
- Produces:
  - `primitives/types.ts`(G-BE1 스키마와 같은 이름): `Delta`, `HeadingEl`, `TextEl`, `StatEl`, `ProgressEl`, `TodoRowsEl`, `Tag = {text: string} | {area: AreaKey}`, `TagsEl`, `BulletsEl`, `OpenScreen = "today" | "todos_day" | "todos_week" | "todos_month" | "activity" | "settings"`, `ButtonDo = {kind: "send"} | {kind: "open"; screen: OpenScreen} | {kind: "complete"; task_id: number}`, `ButtonItem = {label: string; do: ButtonDo}`, `ButtonsEl`, `DividerEl`, `RowGroup`, `StackGroup`, `BlockElement`(10개 유니언), `InnerElement`.
  - `parseMiniMd(md: string): MiniLine[]`, `type MiniLine = {text: string; strong: boolean}[]`. `\n`으로 줄을 나누고 줄마다 `/\*\*([^*\n]+?)\*\*/g` 한 번. 짝 없는 `**`와 그 밖의 기호는 글자 그대로.
  - `dates.ts`: `weekdayKo(date: string): string`("일"~"토", 시간대 없는 `YYYY-MM-DD` 산술), `dayLabel(date: string): string`(= `copy.parts.dayLabel(m, d, w)`, 예 `"10월 27일 (화)"`), `relativeDay(date: string, today: string): "today" | "tomorrow" | "yesterday" | null`, `rowMeta(todo: PartTodo, today: string | undefined): string | null`(5.3.5: `scheduled_at` → `formatKst(…, "HH:mm")`, 아니면 `planned_for !== today`면 `dayLabel`, 아니면 `null`. `today`가 `undefined`(옛 BE)면 날짜를 숨긴다(오늘과 가를 수 없다). `status = dropped`면 `copy.parts.dropped`).
  - `CheckRow({title, meta?, checked, disabled, struck?, highlight?, mark = "circle", onToggle})`. `mark: "circle" | "dot" | "none"`(빈 곳 1). 원은 `role="checkbox"` 44px, `aria-checked`, `aria-label={copy.parts.checkLabel(title)}`. `highlight`면 왼쪽 3px `--hue` 막대 클래스 + 눈에 안 보이는 `copy.parts.changedBySecretary`.
  - 부품(받는 값 = 그 요소의 props, `type` 빼고): `Heading({text, first?})`(`<h4>`), `MiniText({md})`, `Stat({label, value, delta?})`(`role="group"`, `aria-label` = `` `${label} ${value}` `` + 변화 낭독 `copy.parts.trendAria`), `Progress({label, value, max})`(`<progress value max aria-label={copy.parts.progressAria(label, value, max)}>`, 글 `"n/m"`), `TodoRows({ids, todos?, today?, checkable, completed?: ReadonlySet<number>, ctx, onComplete(id): void})`(5.3.5: `completed`는 그린 뒤 카드가 완료한 id(그 줄은 끝남으로), `todos` 없으면 `copy.parts.todoCount(ids.length)`, 비면 `copy.parts.noTodos`, `done` → `struck` + 채운 원 + 꺼짐, `dropped` → `struck` + `mark="none"`, `checkable=false` → `mark="dot"`), `Tags({items})`(`<ul aria-label={copy.parts.tagsLabel}>`), `Bullets({items})`, `Buttons({items, isDisabled(item): boolean, onPress(item): Promise<boolean> | boolean})`(눌러서 `true`면 `send`·`complete`는 모두 꺼지고 누른 것만 `aria-pressed="true"`, `open`은 꺼지지 않는다), `Divider()`(`<hr aria-hidden>`), `Group({layout, children: ReactNode[]})`.
  - `copy.parts`에 더함: `dayLabel`, `today`, `tomorrow`, `yesterday`, `noTodos`, `dropped`, `changedBySecretary`, `trendAria.{up,down,same}`, `progressAria`, `tagsLabel`(부록 A 그대로). 나머지 부록 A 키는 G-A2.

- [ ] **Step 1: `parseMiniMd.test.ts`**: `bold and newline`(`"이번 주는 **화요일**이\n비어요"` → `[[{text:"이번 주는 ",strong:false},{text:"화요일",strong:true},{text:"이",strong:false}],[{text:"비어요",strong:false}]]`), `unpaired stars stay literal`(`"**굵게"` → 글자 그대로 한 조각), `html and links stay literal`(`"<b>x</b> [a](b) `c` # h _i_"` → 한 조각, `strong` 없음). `MiniText`가 `<strong>`·`<br>`만 만들고 `innerHTML`에 `<b>`가 없다(`elements.test.tsx`의 `text renders only strong and br`). → FAIL → 구현 → PASS.
- [ ] **Step 2: `dates.test.ts`**: `weekday of logical date`(`"2026-10-24"` → `"토"`, `"2026-11-01"` → `"일"`), `relative day`(오늘 `2026-10-24`에 `2026-10-25` → `tomorrow`, `2026-10-23` → `yesterday`, `2026-10-27` → `null`), `row meta`(시각 있음 → `"14:00"`, 다른 날 → `"10월 27일 (화)"`, 오늘 → `null`, `dropped` → `"뺌"`). `npm run test:tz`에도 이 파일을 더한다(`package.json` `test:tz`에 경로 추가). → PASS.
- [ ] **Step 3: `CheckRow.test.tsx`**: `four states`(열림 → `role="checkbox"` `aria-checked=false` 눌림 → `onToggle`, 끝남 → 취소선 클래스 + `aria-checked=true` + `disabled`, 뺌 → checkbox 없음 + 보조 글 `"뺌"`, 점 → checkbox 없음), `highlight has hidden text`(`"비서가 바꿈"`), `meta shows`. → PASS.
- [ ] **Step 4: `elements.test.tsx`**(부품마다 하나): `heading is h4`, `stat aria label`(`"컨디션 평균 3.6, 지난번보다 올라감 0.4"`, 변화 글 앞 `"↑"`, 변화 칸 클래스는 `--text-2` 규칙 하나뿐), `progress element values`(`<progress>`의 `value=3`, `max=5`, 글 `"3/5"`, 화면에 `"%"` 없음), `todo rows fallback and empty`(`todos` 없음 → `"할 일 2개"`, `[]` → `"보여 줄 할 일이 없어요"`), `todo rows complete calls handler`(열린 줄 누름 → `onComplete(53)`), `tags show area names`(`{area: "health"}` → `"건강"`), `bullets list`, `divider hidden from a11y`, `group row and stack classes`. → PASS.
- [ ] **Step 5: `Buttons.test.tsx`**: `send disables all and marks pressed`, `open stays enabled after press`(두 번 눌러 `onPress` 2회), `isDisabled respected`, `failed press keeps buttons on`(`onPress`가 `false` → 모두 켜짐). → PASS.
- [ ] **Step 6: `primitives.css.test.ts`**(Global Constraints, Review Focus 2): `primitives.module.css`를 읽어 (1) `#[0-9a-f]{3,8}\b` 0개, (2) `var(--hue)`는 `.highlight` 선택자 블록에만(`ui_result`의 `.changeChip`은 G-A2의 `cards.module.css`), (3) `progress` 규칙에 `appearance: none`과 `::-webkit-progress-bar`, `::-webkit-progress-value`, `::-moz-progress-bar`(11.3), (4) `@media (max-width: 340px)` 안에 `.row`의 `grid-template-columns: 1fr`, (5) `font-weight: 700` 없음. `src/ui/**/*.tsx`에 `style={` 와 `dangerouslySetInnerHTML` 0개(`noInlineStyle` 시험, 스펙 12장의 "lint" 몫: 이 앱에는 ESLint가 없어 시험으로 둔다, 빈 곳 2). → FAIL → CSS → PASS.
- [ ] **Step 7: 기존 넷 다시 짜기.** `TodoList` → 카드 제목 + `CheckRow`(6줄 넘으면 `more`), `TodoDraft` → `CheckRow`(체크는 "고르기", 8장 첫 줄). DraftRows는 체크 줄이 없어 그대로, `Choice` → 질문은 `MiniText`(`text` 부품)가 아니라 같은 글 모양의 `<p>`(`**`를 읽지 않아 지금 보이는 글이 그대로다, 빈 곳 12) + `Buttons`(`send`와 같은 동작: `onPress` = `ctx.onChoose(label)`), `SummaryCard` → 카드 제목 + `Bullets` 모양. `npx vitest run src/ui/components` → 고치지 않은 기존 시험이 모두 `passed`(보이는 글과 `/actions` 본문이 같다). `Choice.test.tsx`에 `pill is 44px`(CSS 블록 `min-height: 44px`) 하나만 더한다.
- [ ] **Step 8: `contrast.test.ts`**에 `progress fill vs track`(`[--primary, --raised]` ≥ 3:1, 밝게·어둡게)을 더한다. 프리셋 12벌은 G-A3.
- [ ] **Step 9: 티켓 끝 검증**(앱). `npm run size`의 첫 화면 합계가 앞보다 6KB 넘게 늘면 `Stat`, `Progress`, `Tags`, `Group`의 import를 기존 넷에서 없앤 것을 확인한다(기존 넷은 이 넷을 쓰지 않는다). `npm run e2e`의 `screens.spec.ts` 스크린샷을 SP6 전과 나란히 본다(오늘·대화). SP5 스펙 7장 "36px"를 고친다. → **Review + Commit** `feat(app): SP6 primitives and CheckRow; existing parts redrawn from them`

---

### 티켓 G-A2: 새 카드 넷, 레지스트리, 확인 칸 숨김, 화면 열기, 확인 시트

**목표:** `ui_date_choice`, `ui_result`, `ui_period_list`, `ui_block`을 대화 묶음에서 등록해 그린다(6.2~6.5, 7장, 8장, 11.2~11.5). 확인 칸 숨김, `activityIds` 읽기, `onOpen`, `onNeedsConfirm`, 시각 있는 할 일의 "내일로"·날짜 바꾸기 확인 시트. 카드 시험은 손으로 쓴 MSW SSE·props로 돈다(BE-2의 기준 SSE는 G-A3). 병합 뒤 **Vercel에 배포하고 조정자에게 알린다**(G-BE2의 문).
**막는 티켓:** G-BE1(카탈로그·공유 자료), G-A1
**맡는 곳:** 운영 앱 스레드

**Files:**
- Create: `src/ui/chat/{DateChoice,Result,PeriodList}.tsx`, `src/ui/chat/{cards.module.css,registerChatParts.ts}`, `src/ui/block/{Block.tsx,checkBlock.ts,renderElement.tsx}`, `src/ui/openScreen.ts`, `src/chat/hideCoveredActivity.ts`
- Modify: `src/ui/{registry.tsx,types.ts,usePartAction.ts,catalog.test.ts}`, `src/chat/{parts.ts,MessageView.tsx,ChatSheet.tsx}`, `src/pages/_app.tsx`(`import "../ui/chat/cards.module.css"`), `src/lib/copy.ts`(부록 A 나머지), `src/screens/{Today,Checkin,EditTodoSheet,todoActions}.tsx`(`move_task`의 `needs_confirm` → `ConfirmSheet`), `src/api/{schema.json,types.gen.ts}`, `src/test/fixtures/catalog.json`(작업 방식의 명령), `scripts/size.mjs`(대화 묶음 알림 줄), SP5 스펙 5.5.5·F6("앱의 `move_task`는 늘 바로 적용된다" 고침), SP6 스펙 6.3·11.2·11.7(빈 곳 4·6·13)
- Test: `src/ui/block/{sharedProps.test.ts,checkBlock.test.ts,Block.test.tsx}`, `src/ui/chat/{DateChoice,Result,PeriodList,registerChatParts}.test.tsx`, `src/ui/registry.firstScreen.test.ts`, `src/chat/{hideCoveredActivity.test.ts,parts.test.ts,MessageView.test.tsx}`, `src/ui/catalog.test.ts`, `src/screens/{Today,Checkin,Todos}.test.tsx`, `scripts/size.test.mjs`

**Interfaces:**
- Consumes: 부품·`CheckRow`·`dates.ts`·`primitives/types.ts`(G-A1), `useAction`, `useUndo`, `ConfirmSheet`, `copy.activity.undoBlocked`, `copy.chat.{undo,undone}`, 공유 자료 `tests/fixtures/ui_props/`(G-BE1), `TodoRef`(`planned_for`, `scheduled_at`, G-BE1)
- Produces:
  - `ui/types.ts`: `PartTodo = Pick<TodoRef, "id" | "title" | "status" | "planned_for" | "scheduled_at">`, `ResultChange = "added" | "moved" | "completed" | "reopened" | "dropped" | "updated" | "confirmed"`, `TodoSnap = {status: string | null; planned_for: string | null; scheduled_at: string | null; title: string | null}`, `ResultItem = {todo: PartTodo; change: ResultChange; before: TodoSnap | null; after: TodoSnap; activity_ids: number[]; undo_id: number | null}`, `DayTodos = {date: string; weekday: string; is_today: boolean; todos: PartTodo[]}`, `OutsideItem = {reason: "moved" | "dropped" | "no_date"; todo: PartTodo}`. `PartData`에 `today?`, `todo?: PartTodo | null`, `items?: ResultItem[]`, `start?`, `end?`, `days?: DayTodos[]`, `outside?: OutsideItem[]`. `PartContext`에 `onOpen?(screen: OpenScreen): void`(없으면 `open` 버튼을 그리지 않는다).
  - `ui/openScreen.ts`: `screenHref(s: OpenScreen): string`(8장 표: `/`, `/todos/?tab=day`, `/todos/?tab=week`, `/todos/?tab=month`, `/activity/`, `/settings/`).
  - `registry.tsx`: `registerParts(entries: Record<string, ComponentType<PartProps<any>>>): void`(이미 있는 이름이면 `process.env.NODE_ENV !== "production"`에서 `throw`), `registerParts(entries, source: string)`의 `source`는 중복 오류 문구에 쓰는 글(대화 묶음은 `CHAT_PARTS_MARKER = "sp6-chat-parts"`, 축소해도 남는 문자열이라 `size.mjs`가 묶음을 찾는 표지가 된다), `registryNames(): string[]`(함수로 바꿈). `UiPart`의 판정 순서(이름 → `check` → 컴포넌트)는 그대로이고, `checkBlock`은 `Block` 안에서 부른다(실패면 `UnknownPart`. 첫 화면 묶음에 `checkBlock`이 들어가지 않게, 빈 곳 13).
  - `ui/chat/registerChatParts.ts`: `registerChatParts(): void`(모듈 안 깃발로 한 번만, `registerParts(…, CHAT_PARTS_MARKER)`), `MessageView.tsx`가 모듈 첫 줄에서 부른다.
  - `usePartAction()`이 돌려주는 함수: `(action, args, opts?: {confirmToken?: string; onNeedsConfirm?(o: Extract<ActionOutcome, {kind: "needs_confirm"}>): void}) => Promise<ActionOutcome | null>`. `onNeedsConfirm`이 있으면 실패 알림 대신 그것을 부른다.
  - `block/checkBlock.ts`: `checkBlock(props: unknown): boolean`(B1, B4~B8. 스키마 검사를 지난 값이라고 가정한다).
  - `block/renderElement.tsx`: `renderElement(el: BlockElement, env: {todos: PartTodo[] | undefined; today: string | undefined; ctx: PartContext; first: boolean; complete(id: number): Promise<boolean>; press(item: ButtonItem): Promise<boolean>}): ReactNode`. `Block({props, data, ctx})`: 먼저 `checkBlock(props)`, 실패면 `UnknownPart`. `Part({title})` 안에 12px 간격(그 클래스는 `cards.module.css`).
  - 버튼 동작(8장): `send` → `ctx.onChoose(label)`, `open` → `ctx.onOpen(screen)`, `complete` → `usePartAction()("complete_task", {id})`(대상이 `data.todos`에 있고 `open`일 때만 켜짐), `undo` → `useUndo`, `confirm`(날짜) → `move_task {id: data.todo.id, planned_for: candidate.date}`.
  - `parts.ts`: `activity` 조각에 `activityIds: number[]`(`data.activity_ids`, 없으면 `[]`).
  - `chat/hideCoveredActivity.ts`: `hideCoveredActivity(parts: ViewPart[]): ViewPart[]`(11.4: `undo_id`가 있는 `ui_result` 항목의 `activity_ids`가 정확히 `[id]`인 것을 모아, 확인 칸의 `activityIds`가 비어 있지 않고 모두 그 안에 있으면 그 `activity` 조각을 뺀다). `MessageView`가 `restored`가 아닌 메시지에만 부른다.
  - `ChatSheet`: `PartContext.onOpen` = `router.push(screenHref(s))` 뒤 시트 닫기.
  - `scripts/size.mjs`: 첫 화면 합계 다음 줄에 `chat sheet chunk: <n> KB`. `loadChatSheet`는 `next/dynamic`이 아닌 맨 `import()`라 `react-loadable-manifest`에 없다: `out/_next/static/chunks/**/*.js` 가운데 첫 화면 목록(`firstScreenChunks`)에 없고 `CHAT_PARTS_MARKER` 문자열이 든 파일의 gzip 크기. 없으면 `chat sheet chunk: unknown`. 종료 코드에 영향 없음.

- [ ] **Step 1: `npm run gen:types`와 `catalog.json`을 다시 만든다**(작업 방식). `catalog.test.ts`를 고친다: `registerChatParts()` 뒤 `registryNames()` 길이 14, `catalog.json`의 `components` 키 집합 == `registryNames()` 집합, 판 == 고정 자료의 판. 박힌 판 문자열 셋(`uses cached catalog when version matches`, `offline uses stored`, `catalog names match registry`의 `"2026-10-24.2"`)을 `catalogJson.version`과 비교하게 바꾼다. → FAIL(함수 없음) → `registry.tsx` → PASS.
- [ ] **Step 2: `sharedProps.test.ts`**(13장 앱 스키마): `fileURLToPath(new URL("../../../../../tests/fixtures/ui_props", import.meta.url))` 아래 `<이름>/{ok,bad}/*.json`을 `fs`로 읽는다. (G-BE1 병합 전에는 그 PR 가지를 받아 같은 시험을 돌려 결과를 조정자에게 알린다, G-BE1 Step 5b) `ok` → `check(name, props) && (name !== "ui_block" || checkBlock(props))`가 `true`, `bad`에서 **BE만 보는 코드** `BE_ONLY = ["bad_char", "banned_word", "slash", "too_large", "period_one", "value_over_max", "not_unique"]`로 시작하는 파일은 건너뛴다(10.3, B9, 그리고 JSON Schema로 다 나타낼 수 없는 `model_validator` 규칙, 빈 곳 10), 나머지 `bad` → `false`. `fixture dir is not empty`(읽은 파일 수 > 20, 경로가 틀려 비어 통과하는 일을 막는다). → FAIL → `checkBlock.ts` → PASS.
- [ ] **Step 3: `checkBlock.test.ts`**: 규칙마다 최소 예(`counts group children toward 12`: 맨 위 11 + 묶음(1+2) → `false`, `buttons must be last and single`, `two todo_rows ok three not`, `divider not first last or adjacent including inside stack`, `needs a content element`, `complete must target a row id`). → PASS.
- [ ] **Step 4: `registerChatParts.test.tsx`**(Review Focus 5): `new names are unknown before chat loads`(등록 전 `UiPart name="ui_block"` + 맞는 props → `UnknownPart` + `title`), `drawn after register`, `double register throws in dev`. 따로 `src/ui/registry.firstScreen.test.ts`(파일마다 모듈이 따로라 등록이 새지 않는다): `first-screen registry stays ten`(`registry.tsx`만 import한 상태의 `registryNames().length === 10`). → PASS.
- [ ] **Step 5: `DateChoice.test.tsx`**(6.2, 6.5, Review Focus 3): `renders question title and candidates`(질문, 할 일 제목, `"오늘 · 10월 24일 (토)"`, `"10월 27일 (화)"` + 메모 `"오후가 비어요"`, `"다른 날로 할게요"`), `no edit fields`(`textbox` 0개), `pick sends move_task`(본문 `{action: "move_task", args: {id: 53, planned_for: "2026-10-27"}}`, 기다리는 동안 버튼 모두 `disabled`), `applied marks chosen`(누른 후보 `aria-pressed="true"`, 나머지 꺼짐, `ctx.onAfterAction` 한 번), `failed re-enables`(네트워크 오류 → 5.4 문구, 버튼 다시 켜짐), `rejected re-enables`(`{status: "rejected", message: …}` → 알림 줄에 이유, 버튼 다시 켜짐), `needs confirm opens sheet`(→ `ConfirmSheet`의 "바꾸기" → 본문에 `confirm_token`, 새 `client_msg_id`), `other day sends text`(`onChoose("다른 날로 할게요")`), `already settled`(`data.todo.status = "done"` 또는 `null` → 후보 없음, `"이미 정리된 할 일이에요"`), `read only`(꺼짐 + `copy.offline.writeLater`), `restored`(보이고 모두 꺼짐, 이유 글 없음), `no data`(질문 + `"할 일 1개"`). → FAIL → 구현 → PASS.
- [ ] **Step 6: `Result.test.tsx`**(6.3): `change rows per kind`(7종 알약 글과 둘째 줄: `moved` → `"10월 25일 (일) → 10월 27일 (화)"`, `aria-label="이전 10월 25일 (일), 지금 10월 27일 (화)"`, `added` 날짜 없음 → `"날짜 없음"`, `updated` 제목 → `"이전 제목: 치과"`, `updated` 시각 → `"14:00 → 16:00"`, `updated` 날짜만 → `moved`와 같은 줄(빈 곳 4), 그 밖 → `"내용을 고쳤어요"`, `confirmed` → `"초안을 확정했어요"`, `completed`·`dropped` 취소선), `undo only with undo_id`, `undo sends and shows done`(`POST /activity/931/undo` → 그 자리 `"되돌렸어요"`, `ctx.onAfterAction` 한 번), `already undone shows done`(`200 already_undone` → `"되돌렸어요"`), `undo blocked shows reason`(`409 superseded` → `copy.activity.undoBlocked.superseded`, `422 not_undoable` → `copy.activity.undoBlocked.not_undoable`), `read only disables undo`, `restored has no undo`, `no data shows count`(`"바뀐 할 일 2개"`), `chips use hue class only`. → PASS.
- [ ] **Step 7: `PeriodList.test.tsx`**(6.4): `titles from data.today`(하루 오늘/내일/어제/`"10월 27일 (화)"`, 주 `2026-W43` → `"이번 주"`, `W44` → `"다음 주"`, `W42` → `"지난주"`, `W46` → `"11월 9일 ~ 11월 15일"`; 기기 시계를 2026-11-30으로 돌려도 같다), `week groups and empty days`(`"26일 월"`, 오늘 머리 `" · 오늘"`, 빈 날 `"화 · 없음"`), `folds over eight rows`, `highlight rows`(`highlight_task_ids` 줄에 `--hue` 막대 클래스 + `"비서가 바꿈"`), `outside groups`(`moved` 줄 보조 글에 그 날짜, `dropped` 취소선·체크 없음, `no_date`, 빈 묶음 없음), `open buttons by period`(오늘 하루 → `todos_day`, 이번 주 → `todos_week`, 그 밖 없음, `highlight_task_ids` 있으면 `"기록에서 보기"` → `onOpen("activity")`), `check completes`(본문 `complete_task {id}`, `ctx.onAfterAction` 한 번), `no undo here`, `read only keeps open`, `restored keeps open`, `no data`(`"할 일을 불러오지 못했어요"`), `no onOpen no open buttons`. → PASS.
- [ ] **Step 8: `Block.test.tsx`**(7장, 6.5): 7.1 예시 → 순서대로 그려짐(`stat` 둘, `progress`, `strong` "목요일", 줄 하나, 버튼 하나), `complete button completes row`(`ctx.onAfterAction` 한 번), `complete disabled when row not open`, `failing checkBlock renders UnknownPart with title`, `read only`(`complete`·`send` 꺼짐, `open` 켜짐), `restored`(`complete`·`send` 버튼 없음, `open` 있음), `no data`(`todo_rows`만 `"할 일 1개"`, 나머지는 그대로). → PASS.
- [ ] **Step 9: `parts.test.ts`, `hideCoveredActivity.test.ts`, `MessageView.test.tsx`**: `reads activity_ids`(없으면 `[]`), `all covered hides`(확인 칸 `[931]`, `ui_result` 항목 `undo_id: 931, activity_ids: [931]` → 없어짐), `partly covered keeps`(`[931, 932]`에 하나만), `null undo item keeps`, `period list only keeps`, `two results covering same id hide once`(Review Focus 4), `empty activityIds keeps`, `restored message keeps`(`MessageView`가 `restored` 메시지에 부르지 않음). → PASS.
- [ ] **Step 10: 시각 있는 할 일의 날짜 확인**(8장 BE-2 몫의 앱 쪽): `Today.test.tsx`, `Checkin.test.tsx`, `Todos.test.tsx`에 `tomorrow on scheduled todo opens confirm sheet`(`move_task` 응답 `needs_confirm` → `ConfirmSheet`의 `summary` → "바꾸기" → 둘째 본문 `confirm_token`, `client_msg_id`는 처음과 다름, "그대로 두기" → 요청 없음). `EditTodoSheet`의 날짜 바꾸기도 같다. 지금 BE는 `needs_confirm`을 보내지 않으므로 기존 시험은 그대로 통과한다. SP5 스펙 5.5.5·F6 문장을 고친다.
- [ ] **Step 11: 문구와 CSS**: 부록 A 나머지 키를 `copy.parts`에(`thisWeek`, `nextWeek`, `lastWeek`, `weekRange`, `dayHead`, `dayHeadToday`, `otherDay`, `alreadySettled`, `noDate`, `changeChip.*`, `prevTitle`, `editedOnly`, `confirmedDraft`, `changeAria`, `resultCount`, `outsideHead.*`, `openTodos`, `openActivity`, `periodFailed`). `copy.test.ts`가 금지어 없음을 본다. `cards.module.css`를 `_app.tsx`에서 가져온다. `primitives.css.test.ts`의 규칙을 `cards.module.css`에도 돌린다(16진수 없음, `var(--hue)`는 `ui_result` 알약 `.changeChip` 블록에만, `Block`의 12px 간격 클래스가 여기 있다).
- [ ] **Step 12: `scripts/size.test.mjs`** `prints chat chunk line`(임시 `out/`: `index.html`이 `a.js`를 읽고, `b.js`에만 `"sp6-chat-parts"` → 출력에 `chat sheet chunk:`와 `b.js` 크기, 종료 코드 0), `unknown when no chunk has the marker`, `first-screen chunk with marker is not counted`. → PASS.
- [ ] **Step 13: 티켓 끝 검증**(앱). `npm run size`의 첫 화면 합계가 G-A1 뒤보다 1KB 넘게 늘지 않는다(새 넷과 `checkBlock`은 대화 묶음, 첫 화면에는 `registerParts`·`registryNames` 몇 줄뿐). PR 설명에 첫 화면·대화 묶음 앞뒤 KB. → **Review + Commit** `feat(app): SP6 chat cards — date choice, result, period list and block` → 병합 → 배포 확인: main의 G-A2 병합 커밋(또는 그 뒤 커밋)의 GitHub 커밋 상태 `Vercel`이 `success`(`gh api repos/dahun428-fx/my-planner/commits/<sha>/status --jq '.statuses[] | select(.context=="Vercel") | .state'` → `success`. 클라우드 컨테이너는 vercel.app에 닿지 않으므로 화면이 아니라 이 상태로 본다) → **조정자에게 "G-A2 배포됨, G-BE2 병합해도 됨"**.

---

### 티켓 G-BE2: 두뇌에게 주기 — 도구 넷, 지금 값, 상한, 앱 `move_task` 확인, 프롬프트, 기준 SSE

> **맡는 곳: BE 스레드 (SP3-4 BE 스레드).** 이 절은 그대로 넘겨주는 브리프다. **운영 앱 스레드가 G-A2 Vercel 배포를 알린 뒤에만 병합한다**(PR은 먼저 열어도 된다).

**맥락:** G-BE1이 카탈로그에 새 조각 넷을 실었고, 운영 앱(G-A2)이 그것을 그릴 수 있게 됐다. 이 티켓은 앱 대화의 두뇌에게 `ui_date_choice`, `ui_result`, `ui_period_list`, `ui_block`을 준다: 도구 메서드와 뜻 검사(읽기만), 스트림에 붙이는 지금 값(`data`), 한 답 두 개 상한, 도구 설명, `channel_app.md` 새 글, 앱 통로 `move_task`의 확인, 기준 SSE 여섯. **카탈로그(스키마)는 바꾸지 않는다**(판은 G-BE1에서 한 번만. 고쳐야 하면 이 PR이 다음 판을 쓰고 조정자에게 알린다).
**막는 티켓:** G-A2 Vercel 배포(병합 문), G-BE1
**브리프에 함께 가는 규칙:**
- 끝 검증: 저장소 루트에서 `python -m pytest -q` → `0 failed`(Linux에서 Windows 전용은 `skipped`), `ruff check src tests` → `All checks passed!`. 노드 하나는 `python -m pytest <파일>::<시험> -v` → `1 passed`.
- 공유 고정 자료(`tests/fixtures/ui_props/`, `tests/fixtures/app_golden/`)는 BE가 만들고 앱 시험이 제자리에서 읽는다. 앱으로 복사하지 않으며 꾸며 낸 내용만 넣는다.
- (Review Focus 3) 그린 뒤 다른 곳에서 완료·삭제·시각이 잡힌 할 일의 날짜 후보를 누르면 `rejected` 또는 `needs_confirm`이고, 할 일이 조용히 옮겨지지 않는다.
- (빈 곳 9) 후보 날짜의 오늘~90일 범위는 이 티켓의 뜻 검사가 본다(G-BE1 스키마는 보지 않는다).

**스펙 절:** 6.2~6.4("BE가 붙이는 값", 뜻 검사), 7.3, 8장(앱 통로 `move_task` 확인), 9.1~9.3, 10.2, 10.4, 10.6 둘째 항목, 부록 B, 12장, 13장 "BE 도구"·"BE 지금 값"·"BE 기준 SSE" 줄

**Files:**
- Modify: `src/my_planner/tools/core.py`, `src/my_planner/tools/mcp_adapter.py`, `src/my_planner/tools/actions.py`, `src/my_planner/store/views.py`, `src/my_planner/domain.py`(`RunContext.ui_drawn`), `src/my_planner/harness/prompts/channel_app.md`, SP3-4 스펙 6.4.2 표의 `move_task` 줄, `docs/spikes/2026-11-sp3-4.md`(S12 SP6 줄), SP6 스펙 8장 확정 줄(누를 때 `move_task`가 `status = open`도 본다)
- Create: `tests/test_period_view.py`, `tests/fixtures/app_golden/chat_{date_choice,result,period_list,block,ui_rejected,gallery}.sse`
- Test: `tests/test_ui_tools.py`, `tests/test_period_view.py`, `tests/test_api_actions.py`, `tests/test_app_golden.py`, `tests/test_prompts.py`, `tests/test_api_e2e.py`

**Interfaces:**
- Consumes: `validate_props`, `PINNABLE_COMPONENTS`, `BRAIN_COMPONENTS`, `todo_refs(ids, tasks, today, drafts=False)`(G-BE1의 `TodoRef`), `RunContext.activity_ids`, `activity_targets`, `Tools._draw`, `Tools.today()`, `confirm_move_summary`
- Produces:
  - `Tools.ui_date_choice(ctx, task_id=None, question=None, candidates=None, **extra)`, `Tools.ui_result(ctx, task_ids=None, **extra)`, `Tools.ui_period_list(ctx, day=None, week=None, highlight_task_ids=None, **extra)`, `Tools.ui_block(ctx, title=None, children=None, **extra)`: `_draw` 뒤 뜻 검사, 맞으면 `{"ok": True}`, 아니면 `{"error": <부록 B 문구>}`. 읽기만.
  - 뜻 검사: `ui_date_choice` — 할 일이 있고 삭제 아님·`status=open`(아니면 "시각이 없는 열린 할 일만 날짜를 고를 수 있어요."), `scheduled_at is None`(아니면 "시각이 잡힌 할 일은…"), 후보 날짜 `today ≤ d ≤ today+90`(아니면 "후보 날짜는 오늘부터 90일 안이에요."). `ui_result`·`ui_period_list.highlight_task_ids` — `Tools.changed_task_ids(ctx) -> set[int]`(이번 답 `ctx.activity_ids`의 `activity_targets`에서 `task:<id>`) 안. `ui_period_list` 범위 — `day`: `today−14 ~ today+56`, `week`: 이번 주 −2 ~ +8.
  - `Tools.ui_result_items(ctx, task_ids) -> list[dict]`: 6.3의 `{todo, change, before, after, activity_ids, undo_id}`(6.3 표대로 `before`, `undo_id`는 활동 하나·대상 하나·지금 되돌릴 수 있음일 때만). 소프트 삭제한 할 일은 빠지고, 다 빠지면 `ui_result`가 도구 오류 "보여 줄 바뀐 할 일이 없어요."(이 검사는 `_stream_output` 전에, 도구 메서드 안에서).
  - `store/views.py`: 새 데이터클래스를 만들지 않고 지금 `DayView(date, weekday, is_today, tasks)`(`WeekView.days`가 쓰는 것)를 다시 쓴다. `period_view(tasks: TasksRepo, start: date, end: date, today: date) -> list[DayView]`(6.4 규칙 하나: `planned_for`가 그날이고 `open`·`done`, 순서 시각 있는 `open`(시각 순) → 시각 없는 `open` → `done`), `period_outside(tasks, ids, start, end) -> list[tuple[str, Task]]`(이유 순서 `dropped` → `no_date` → `moved`, 삭제는 뺌).
  - `mcp_adapter._stream_output`: 10.2 표대로 `data`. `UI_PARTS_PER_REPLY = 2`, `RunContext.ui_drawn: int = 0`. `call_tool`은 두뇌 화면 도구(`BRAIN_COMPONENTS`)가 검사를 지나 조각을 쓸 때 1을 더하고, 이미 상한이면 메서드를 부르지 않고 "한 답에 화면 조각은 2개까지예요."(조각 없음). 하네스 조각·`pin_card`는 세지 않는다.
  - `APP_ONLY_TOOLS = [*BRAIN_COMPONENTS, "pin_card", "unpin_card", "reorder_cards"]`(새 넷 더함, 순서는 카탈로그 순), `_SPECS`에 9.3 설명 넷, 기존 `ui_todo_list`·`ui_choice` 설명에서 "같은 뜻을 답 글에도 씁니다"·"같은 질문을 답 글에도 씁니다" 뺌.
  - `tools/core.py` `Tools.move_task`: 지금은 상태를 보지 않아 끝난·뺀 할 일도 옮겨진다. `status != open`이면 도구 오류 "열린 할 일만 날짜를 옮길 수 있어요."(앱 `/actions`에서는 `rejected`, 텔레그램·두뇌도 같다).
  - `tools/actions.py`: `move_needs_confirm(tools: Tools, args: dict[str, Any], today: date) -> str | None`(`drop_needs_confirm`과 같은 모양)(할 일에 `scheduled_at`이 있고 `planned_for`가 바뀌면 `confirm_move_summary(...)`, 아니면 `None`), `ACTIONS["move_task"] = ActionSpec("move_task", needs_confirm=move_needs_confirm, target=_task_target)`. `drop_task`처럼 앱 통로 요청에만(텔레그램 버튼은 그대로 바로).
  - `channel_app.md`: 스펙 9.2 블록 **그대로**(지금 글 전체를 바꾼다). `system.md`는 그대로.

- [ ] **Step 1: 도구와 뜻 검사 시험**(`tests/test_ui_tools.py`): `test_new_ui_tools_do_not_touch_db_files_or_events`(넷 모두, 기존 시험의 DB·`data/` 해시 방식, `ctx.events == []`), `test_date_choice_rejects_scheduled_task`, `test_date_choice_rejects_not_open`, `test_date_choice_candidate_range`(오늘 −1일, +91일 → 오류, 오늘·+90일 → 통과), `test_result_rejects_unchanged_task`, `test_result_all_deleted_is_error`, `test_period_highlight_must_be_changed`, `test_period_range`(`day` −15일, `week` +9주 → 오류), `test_reply_cap_two`(셋째 → 정확한 문구, 스트림에 셋째 조각 없음, 하네스 `h_draft_*`와 `pin_card`는 세지 않음), `test_new_tools_absent_from_telegram`, `test_app_tool_count_plus_four`(`set(tool_names_for("app")) - set(TOOL_NAMES)`가 G-BE1의 여섯 + 새 넷 = 10개), `test_ui_props_not_in_logs`(제목 `"비밀제목XYZ"`인 `ui_block`을 그린 뒤 시스템 로그에 그 글이 없다). → FAIL → 구현 → PASS.
- [ ] **Step 2: 지금 값 시험**(`tests/test_ui_tools.py`): `test_result_before_per_activity_kind`(6.3 표의 다섯 줄 매개변수), `test_result_added_then_moved_has_no_undo`(활동 둘 → `change: "added"`, `before: None`, `undo_id: None`), `test_result_single_move_has_undo`, `test_result_two_moves_before_is_first`(A→B→C → `before.planned_for == A`, `undo_id: None`), `test_result_tasks_confirmed_two_tasks_no_undo`, `test_result_confirmed_change_no_undo`(확인 토큰으로 적용, `risk=confirm`), `test_result_activity_ids_oldest_first`, `test_block_data_todos_order_and_dedupe`(두 `todo_rows` `[61, 62]`, `[62, 63]` → `todos` id `[61, 62, 63]`, 초안 뺌, `todo_rows` 없으면 `{"today"}`만), `test_date_choice_data_todo_null_when_deleted`, `test_period_data_shape`(`days` 7개 월~일, `weekday` `"월"`, `is_today`, `outside`). → PASS.
- [ ] **Step 3: `tests/test_period_view.py`**: `test_today_does_not_pull_earlier_open`(어제 `planned_for`인 열린 할 일이 오늘 칸에 없다, `today_view`와 다름), `test_only_open_and_done`(초안·삭제·`dropped` 없음), `test_each_task_once`, `test_order_scheduled_then_open_then_done`, `test_outside_reasons_order`(뺀 것 → `dropped`, 날짜 없음 → `no_date`, 기간 밖 → `moved`, 삭제 → 없음). → FAIL → 구현 → PASS.
- [ ] **Step 4: 앱 통로 `move_task` 확인**(`tests/test_api_actions.py`, Review Focus 3): `test_app_move_task_scheduled_needs_confirm`(시각 있는 할 일 날짜 바꿈 → `needs_confirm`, `summary` == 회차 차례와 같은 문구, 할 일 그대로 → 그 토큰으로 다시 보내면 `applied`), `test_app_move_task_unscheduled_applies`, `test_app_move_task_same_date_scheduled_applies`(날짜가 같으면 확인 없음), `test_telegram_move_button_still_applies`, `test_move_task_rejects_non_open`(`done`·`dropped` 할 일 → 앱 `/actions` `rejected` + 할 일 그대로, 두뇌 `move_task`도 오류. 그린 뒤 완료된 할 일의 날짜 후보 누름이 이것이다, Review Focus 3). → FAIL → 구현 → PASS. SP3-4 스펙 6.4.2 표 `move_task` 줄과 SP6 스펙 8장 확정 줄("누를 때 `/actions move_task`가 보는 것"에 `status = open`을 더함)을 고친다.
- [ ] **Step 5: 프롬프트와 설명**(`tests/test_prompts.py`): `test_channel_app_is_spec_text`(`channel_app.md` == 스펙 9.2 블록, 공백까지), `test_old_echo_sentence_gone`(`"답 글에도 같은 뜻을 씁니다"`가 프롬프트와 `_SPECS` 어디에도 없다), `test_new_tool_descriptions`(9.3 문구 그대로). → PASS.
- [ ] **Step 6: 기준 SSE**: `tests/test_app_golden.py`의 `CASES`에 `chat_date_choice`, `chat_result`, `chat_period_list`, `chat_block`, `chat_ui_rejected`, `chat_gallery`를 더한다(10.6의 FakeBrain 대본. `chat_result`는 `move_task` 하나 → `ui_result` + `data-activity`의 `activity_ids`가 그 항목의 `activity_ids`와 같다. `chat_ui_rejected`는 `ui_block` 첫 호출이 `buttons_place`로 거절 → 고친 둘째 호출만 조각. `chat_gallery`는 `monkeypatch.setattr(mcp_adapter, "UI_PARTS_PER_REPLY", 10)`으로 새 넷 + 기존 두뇌 셋을 한 답에, `BeEnv` 설정은 더하지 않는다). `python -m pytest tests/test_app_golden.py --update-app-golden`으로 만들고 → 다시 `python -m pytest tests/test_app_golden.py -v` → 모두 `passed`. 모든 조각의 제목·메모는 꾸며 낸 것.
- [ ] **Step 7: 수용 확인**: `tests/test_api_e2e.py::test_date_choice_then_move_from_app`(FakeBrain(앱) "다음 주에 치과 예약 추가해 줘" → `add_task`(날짜 없음) + `ui_date_choice` → 스트림에 `ui_result` 없음, `data-activity` 있음 → 그 후보로 `POST /actions move_task` → `applied`, `GET /today`·`/week`에 그 날짜). → `passed`.
- [ ] **Step 8: S12 다시 재기**(`needs-laptop`): 노트북 구독 로그인으로 앱 대화 도구 수(+4)와 첫 응답 지연을 `docs/spikes/2026-11-sp3-4.md` S12 절에 SP6 줄로 더한다. 클라우드에서는 이 단계만 남겨 두고 PR을 연다.
- [ ] **Step 9: 티켓 끝 검증**(BE) → **Review + Commit** `feat(ui): give the app brain date choice, result, period list and block` → PR. **G-A2 배포 알림을 받은 뒤 병합**, 조정자에게 PR 번호와 새 기준 SSE 이름을 알린다.

---

### 티켓 G-A3: 기준 SSE 계약, CSP 실행, 스크린샷, 대비, 실기기

**목표:** 13장의 "앱 대화 계약", "대비", "CSP 실행", "눈으로", "디자인", "실기기" 줄. 손으로 쓴 SSE 대신 G-BE2의 기준 SSE로 대화를 읽고, 빌드한 `out/`을 CSP 헤더로 띄워 새 카드를 그리고, 스크린샷 26장(프리셋 12장은 프리셋 티켓 뒤)과 아이폰에서 1장 완료 조건을 확인한다.
**막는 티켓:** G-BE2 병합 · 프리셋 줄은 색 프리셋 티켓 병합
**맡는 곳:** 운영 앱 스레드 · 실기기 단계는 `needs-laptop` + **Dahun**

**Files:**
- Modify: `src/chat/contract.test.tsx`, `src/styles/contrast.test.ts`, `e2e/{csp.spec.ts,screens.spec.ts,routes.ts}`
- Create: `docs/acceptance/sp6-checklist.md`
- Modify (문서): SP6 스펙 13장 실기기 줄(빈 곳 7)
- Test: 위 파일들

**Interfaces:**
- Consumes: `tests/fixtures/app_golden/chat_{date_choice,result,period_list,block,ui_rejected,gallery}.sse`(G-BE2), `hideCoveredActivity`, 카드 넷(G-A2), 프리셋 티켓의 `:root[data-palette="<이름>"]` 블록과 프리셋 이름 목록(그 티켓이 내보내는 상수를 쓴다. 이 계획은 이름을 정하지 않는다)
- `e2e/routes.ts`의 `mockBe(page, {chat?: string[]})`는 지금 모양 그대로 쓴다(기본 `["chat_propose_tasks.sse"]`).

- [ ] **Step 1: `contract.test.tsx`**에 기준 파일 다섯(`chat_date_choice`: `DateChoice`가 그려지고 `ui_result` 없음·확인 칸 보임, `chat_result`: `Result` + 확인 칸 숨김, `chat_period_list`: `PeriodList` + 확인 칸 보임 + 바뀐 줄 셋, `chat_block`: `Block` + `todo_rows` 줄, `chat_ui_rejected`: 조각 하나만)을 더하고, G-A2에서 쓴 손 SSE 가운데 이것과 겹치는 것을 지운다. `activityIds` 읽기를 기준 파일로 한 번 더 본다. → `npx vitest run src/chat` → `0 failed`.
- [ ] **Step 2: `csp.spec.ts`**에 `SP6 cards render under CSP`(`mockBe(page, {chat: ["chat_gallery.sse"]})`, 대화 시트에 한 줄 보냄 → 새 넷의 보이는 글(날짜 후보 버튼, 알약 "옮김", 날짜 머리, 블록 제목)이 모두 보이고 `<progress>` 하나 이상), `SP6 gallery has no CSP violations`(같은 대화 + 오늘·할 일 화면으로 이동, `securitypolicyviolation`·콘솔 CSP 0개). → `npx playwright test csp.spec.ts` → `5 passed`.
- [ ] **Step 3: `screens.spec.ts`**: 390×844, `chat_gallery` 대화 시트. (1) 기본 프리셋 밝게·어둡게 × 카드 7개(새 넷 + `ui_todo_list`, `ui_choice`, `ui_summary_card`, 카드마다 `locator.screenshot`) = 14장, (2) 프리셋 6개 × 밝게·어둡게 시트 전체 = 12장(프리셋 티켓 전에는 `test.skip(!PALETTES.length)`). 모든 장에서 `document.documentElement.scrollWidth <= 390`(Review Focus 2), 320px 폭 한 장 더 보고 같은 검사. → `npx playwright test screens.spec.ts` → 26장 저장(프리셋 전 14장). 다시 짠 기존 넷은 G-A1 전 스크린샷과 나란히 본다.
- [ ] **Step 4: `contrast.test.ts`**: 새 쌍 `[--text-2, --raised]`, `[--hue, --surface]`(≥ 4.5), `[--primary, --raised]`(≥ 3)를 프리셋 6 × 밝게·어둡게 12벌에서(프리셋 전에는 기본 2벌). → `npx vitest run src/styles` → `0 failed`. 어느 프리셋이 떨어지면 SP6 CSS가 아니라 프리셋 티켓 쪽에 알린다(SP6은 토큰을 만들지 않는다).
- [ ] **Step 5: taste 점검**: `<taste>`는 github `Leonxlnx/taste-skill`을 받아 둔 곳의 `skills/taste-skill`(SP5 계획 Tech Stack, A10 Step 4와 같은 자리). 받아 두지 않았으면 스크래치 폴더에 얕게 받는다. 스펙 13장 그대로 `node <taste>/scripts/lint.mjs --app web/app/src` → `0 FAIL`.
- [ ] **Step 6: 티켓 끝 검증**(앱) → **Review + Commit** `test(app): SP6 golden chat contract, CSP runtime and screen matrix`
- [ ] **Step 7: 실기기**(`needs-laptop` + Dahun): `docs/acceptance/sp6-checklist.md`(`sp1-checklist.md`와 같은 모양, 단계마다 날짜·결과 칸)에 13장 실기기 줄 넷 + 1장 완료 조건 1~4, 7: 날짜 없는 할 일 말하기 → 후보 누름 → 알림 줄 되돌리기, 할 일 둘 옮기기 → `ui_result` 줄마다 되돌리기(확인 칸 없음), 셋 옮기기 → `ui_period_list` 바뀐 줄 막대(확인 칸 있음), "이번 주 컨디션 어땠지" → `ui_block`, 앱을 닫고 다시 연 대화의 카드가 읽기 전용. 2주 뒤 "성공의 모습"(3장)을 Dahun과 본다. → **Commit** `docs: SP6 acceptance results`

---

## 스펙 빈 곳과 이 계획의 결정

| # | 스펙 자리 | 빈 곳 | 이 계획의 결정 (티켓) | 반영 |
|---|---|---|---|---|
| 1 | 5.3.5 `CheckRow` 받는 값 | `{title, meta?, checked, disabled, struck?, highlight?, onToggle}`로는 "`checkable=false`면 원 대신 점", "`dropped`면 원 없음"을 그릴 수 없다 | `mark?: "circle" \| "dot" \| "none"`(기본 `circle`)을 더한다. 습관 기록의 `ui_habit_check`는 기본값만 쓴다 (G-A1) | G-A1 PR이 스펙 5.3.5 |
| 2 | 12장 "`lint`가 `dangerouslySetInnerHTML`을 금지" | `web/app`에 ESLint가 없다 | `primitives.css.test.ts`의 `noInlineStyle` 시험이 `src/ui/**/*.tsx`에서 `style={`와 `dangerouslySetInnerHTML`을 찾는다. 나란히 들어오는 `Markdown.tsx`는 이 검사 밖이고 그 티켓이 원시 HTML을 끈다 (G-A1) | G-A1 PR이 스펙 12장 |
| 3 | 5.2 `todo_rows.checkable?` | 기본값이 없다 | `true`(지금 `ui_todo_list`처럼 체크할 수 있음) (G-BE1, G-A1) | G-BE1 PR이 스펙 5.3.5 |
| 4 | 6.3 `updated`의 둘째 줄 | `update_task`로 `planned_for`만 바뀐 경우가 없다 | `moved`와 같은 "{이전} → {지금}" 날짜 줄 (G-A2) | G-A2 PR이 스펙 6.3 |
| 5 | 5.3.2 `parseMiniMd(md): Array<{text, strong}>` "(줄 단위)" | 돌려주는 모양이 줄 배열인지 한 배열인지 | `MiniLine[]`, `MiniLine = {text, strong}[]` (G-A1) | G-A1 PR이 스펙 5.3.2 |
| 6 | 11.7 대화 묶음 크기 | 늦게 읽는 묶음 파일을 어떻게 찾는지 | `.next/react-loadable-manifest.json`의 `ChatSheet` import 항목, 못 찾으면 `unknown`(알림만) (G-A2) | G-A2 PR이 스펙 11.7 |
| 7 | 13장 실기기 "`sp5-checklist.md`에 SP6 줄" | main에 `docs/acceptance/sp5-checklist.md`가 아직 없다(SP5 A12 전) | `docs/acceptance/sp6-checklist.md`를 따로 둔다 (G-A3) | G-A3 PR이 스펙 13장 |
| 8 | 9.3 도구 수 "지금 27개" | SP3-4 티켓 15가 `grant_xp`를 더해 28개가 된다 | 시험은 스펙대로 상대 수만 쓴다(G-BE1 "그대로", G-BE2 "+4"). 절대 수는 S12 기록에만 (G-BE1, G-BE2) | 바꿀 문장 없음(스펙이 이미 상대 수) |
| 9 | 6.2 후보 범위 | 스키마가 범위를 볼 수 없다(시계를 모른다) | 형식·개수·서로 다름은 스키마, 오늘~90일은 G-BE2 뜻 검사. G-BE1만 병합된 동안에는 두뇌가 이 도구를 받지 않으므로 빈틈이 없다 (G-BE1, G-BE2) | G-BE1 PR이 스펙 10.1 |
| 10 | 7.2·13장 "두 쪽의 판정은 공유 고정 자료로 맞춘다" | `model_validator` 규칙(`day`·`week` 하나만, `value ≤ max`, 서로 다름)은 `model_json_schema()`에 나오지 않아 앱이 같은 판정을 할 수 없다 | 정수 목록의 서로 다름은 `uniqueItems`로 양쪽이 본다. `period_one`, `value_over_max`, `not_unique`(후보 날짜)는 B9·글 검사처럼 BE 전용이고 앱 공유 시험이 건너뛴다. BE가 거절한 조각은 스트림에 오지 않는다 (G-BE1, G-A2) | G-BE1 PR이 스펙 7.2·10.1 |
| 11 | 1장 조건 8, 13장 대비 | 프리셋 이름과 목록은 다른 티켓이 정한다 | G-A3은 그 티켓이 내보내는 목록을 쓰고 이름을 박지 않는다. 그 전에는 기본 2벌만 (G-A3) | 바꿀 문장 없음 |
| 12 | 6.1 `ui_choice` "`text`(질문) + 버튼 줄" | `text` 부품은 `**`를 굵게 읽는데 지금 질문은 글 그대로다 | 질문은 `text` 부품과 같은 글 모양의 `<p>`(마크다운 없음). 기존 시험과 보이는 글이 그대로다 (G-A1) | G-A1 PR이 스펙 6.1 |
| 13 | 11.2 "`ui_block`만 스키마 다음에 `checkBlock`"을 `UiPart`에서 | `UiPart`가 `checkBlock`을 가져오면 첫 화면 묶음에 들어간다 | `Block` 컴포넌트 안에서 먼저 부르고 실패면 `UnknownPart`. 판정 결과는 같다 (G-A2) | G-A2 PR이 스펙 11.2 |

## 스펙 대비 확인 (셀프 리뷰)

1장 완료 조건
- 1 (날짜 고르기, `move_task`, `ui_result` 없음) → G-A2 Step 5, G-BE2 Step 1·7, G-A3 Step 1·7 · 2 (`ui_result` 되돌리기, 확인 칸 숨김, 셋 이상 `ui_period_list`) → G-A2 Step 6·7·9, G-BE2 Step 2, G-A3 · 3 (`ui_block` 숫자) → G-A1 Step 4, G-A2 Step 8, G-BE2 Step 5 · 4 (버튼 다섯, id만) → G-A1 Step 5, G-A2 Interfaces, G-BE1(스키마에 `ActionName` 없음)
- 5 (BE 거절, 같은 판정) → G-BE1 Step 1, G-A2 Step 2 · 6 (옛 앱 `UnknownPart`, 기존 props 그대로) → G-A2 Step 4, G-A1 Step 7 · 7 (`restored` 읽기 전용) → G-A2 Step 5~9 · 8 (180KB, CSP, 스크린샷) → 작업 방식, G-A1 Step 9, G-A2 Step 13, G-A3 Step 2~4 · 9 (금지어) → G-BE1 Step 1, G-A2 Step 11

스펙 절
- 2·3 → Global Constraints · 4.1~4.3 → Architecture, File Structure · 5.1 → Global Constraints, G-A1 Step 6 · 5.2~5.3 → G-A1 · 6.1 → G-A1 Step 7 · 6.2 → G-A2 Step 5, G-BE2 · 6.3 → G-A2 Step 6, G-BE2 Step 2 · 6.4 → G-A2 Step 7, G-BE2 Step 2·3 · 6.5 → G-A2 Step 5~8
- 7.1~7.2 → G-BE1, G-A2 Step 2·3·8 · 7.3 → G-BE2 Step 2 · 8 → G-A2 Interfaces·Step 10, G-BE2 Step 4 · 9.1~9.3 → G-BE2 Step 5 · 10.1·10.3·10.5 → G-BE1 · 10.2·10.4 → G-BE2 · 10.6 → G-BE1(공유 자료), G-BE2 Step 6
- 11.1 → File Structure · 11.2 → G-A2 Step 1·4 · 11.3 → Global Constraints, G-A1 Step 6, G-A2 Step 11 · 11.4 → G-A2 Step 9 · 11.5 → G-A2 Interfaces · 11.6 → 바꾸지 않음(G-A2가 `localParts`, `history.ts`, `UnknownPart`, `CatalogProvider`, `transport.ts`를 고치지 않는다) · 11.7 → G-A2 Step 12
- 12 → Global Constraints, G-A1 Step 6, G-BE1 Step 1, G-BE2 Step 1 · 13 → 각 티켓, G-A3 · 14 → 티켓 지도 · 부록 A → G-A1 Interfaces, G-A2 Step 11 · 부록 B → G-BE1, G-BE2
- 코디네이터 요청(SP3-4 티켓 15의 `xp`, 레벨 줄, 새 활동 종류, `grant_xp` 조각) → G-A0 (완료, PR #113)

# SP9c 퀵 칩을 대화 안 카드로 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 추가 칩은 입력창을 "한 줄 쓰기"로 바꾸고, 칩 메시지에는 BE가 결과 카드를 보장한다.

**Architecture:** 앱은 `POST /chat`에 `chip`을 싣는다. BE는 `Inbound.chip`을 메모리로 들고 다니며 두뇌 본문에 `## 버튼` 블록을 넣고, 정상 답 경로에서 빠진 카드를 하네스 조각 `h_chip`으로 붙인다. 메모 칩은 원문(`RunContext.chip_text`)으로 저장한다.

**Tech Stack:** Python 3.12 aiohttp + pydantic, pytest; Next.js static PWA, vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-sp9c-quick-chip-cards-design.md` (v1.2)

## Global Constraints

- 새 문구는 스펙 5장 그대로. 금지어(GLOSSARY `_쓰지 않음_`) 금지, 존댓말.
- 로그에 메시지 본문·메모 본문·도구 인자를 남기지 않는다(로그는 칩 키와 컴포넌트 이름만).
- 마이그레이션, 원문 형식, `/conversations/{id}/messages` 응답은 바꾸지 않는다.
- "오늘"은 논리적 날짜(04:00 경계).
- 앱 첫 로드 180KB 상한(`npm run size`), `check:csp`, `lint:copy`, `typecheck` 통과. BE `pytest -q` 전체 통과(`-n` 없이).
- 한 답의 화면 조각은 두뇌 조각 + 칩 카드 합쳐 2개까지.

## Review Focus

1. 두뇌가 이미 맞는 카드를 그렸을 때 하네스가 같은 카드를 또 붙이지 않는다(C1b 시험).
2. 두뇌 오류·상한·안전 모드·재생 경로에서 칩 카드가 붙지 않는다(C1b 시험).
3. 메모 칩에서 가린 값(`[가림]`)이나 8,000자에서 잘린 글이 저장되지 않는다(C1a 시험: 비밀번호 줄과 9,000자 글).
4. `chip`이 있으면 `/today …` 글이 명령으로 실행되지 않는다(C1a 시험).
5. 옛 BE(칩 모름, 400)에서도 칩 메시지가 보통 메시지로 간다(C2 시험).

---

### Task C1a: BE 요청·칩 알림·메모 원문

**Files:**
- Modify: `src/my_planner/api/models.py` (`ChatRequestBody`), `src/my_planner/api/chat.py`, `src/my_planner/harness/dispatcher.py` (`Inbound`, `## 메시지` 본문 조립), `src/my_planner/domain.py` (`RunContext`), `src/my_planner/tools/memos.py` (`create_memo`)
- Create: `src/my_planner/harness/prompts/chip_todo.md`, `chip_event.md`, `chip_memo.md`, `chip_today.md`, `chip_next.md` (스펙 4.3 문장 그대로)
- Test: `tests/api/test_chat_chip.py`, `tests/harness/test_chip_prompt.py`, `tests/tools/test_memos.py`

**Interfaces:**
- Produces: `ChipKey = Literal["todo", "event", "memo", "today", "next"]`(models.py), `ChatRequestBody.chip: ChipKey | None = None`; `Inbound.chip: str | None = None`; `RunContext.chip: str | None = None`, `RunContext.chip_text: str | None = None`; `prompts.load("chip_<키>.md")`.

- [ ] Step 1: 실패 시험 작성.
  - `chip: "x"` → 400 `invalid_request`; `chip: "todo"` + `checkin_id` → 400 `invalid_request`.
  - `chip: "todo"`, 글 `/today 회의` → 명령 갈래가 아니라 두뇌로 간다(가짜 두뇌가 불림).
  - `chip: "event"` 차례의 두뇌 프롬프트에 `## 버튼`과 `chip_event.md` 내용이 `## 메시지` 앞에 있다. 칩 없는 차례에는 `## 버튼`이 없다.
  - 메모 칩: 글 `비밀번호 1234abcd 적어둬` + 9,000자 꼬리 → 가짜 두뇌가 `create_memo`를 `body` 없이 부르면 저장된 메모 본문이 보낸 원문과 같다. `body="딴 글"`로 불러도 원문이 저장된다. 칩이 아닌 차례에서 `body` 없이 부르면 지금 거절 문구.
- [ ] Step 2: 시험 실패 확인 (`uv run pytest -q tests/api/test_chat_chip.py tests/harness/test_chip_prompt.py tests/tools/test_memos.py`).
- [ ] Step 3: 구현.
  - 모델 검증기로 `chip`+`checkin_id`를 거절한다(지금 400 경로로 떨어지게).
  - `chat.py`: `req.chip`이 있으면 `command_of`를 건너뛴다. `Inbound(chip=req.chip)`.
  - 디스패처: 앱 차례 `run_ctx`에 `chip`을 넣고, 메모 칩이면 `chip_text`에 그 `Inbound.text`(가리기·자르기 전)를 넣는다. 본문 `_join`에서 `## 메시지` 앞에 `f"## 버튼\n{prompts.load(...)}"`.
  - `create_memo`: `ctx.chip == "memo"`이고 `ctx.chip_text`가 있으면 그것을 `body`로 쓴다.
  - `resubmit_app_row`, 재시작 다시 넣기는 칩 없음(스펙 4.2 결정). 따로 코드 없음.
- [ ] Step 4: 시험 통과 + 전체 `uv run pytest -q`.
- [ ] Step 5: 커밋 `feat(be): chip on /chat, chip prompt block, memo chip saves the original text`.

### Task C1b: BE 카드 보장

**Files:**
- Modify: `src/my_planner/domain.py` (`RunContext.ui_drawn_names`), `src/my_planner/tools/mcp_adapter.py` (`call_tool`이 이름을 채움), `src/my_planner/harness/dispatcher.py` (`Outbound.chip_cards`, 정상 답 경로), `src/my_planner/harness/stream.py` (`harness_cards`)
- Create: `src/my_planner/harness/chip_cards.py`
- Test: `tests/harness/test_chip_cards.py`

**Interfaces:**
- Consumes: C1a의 `RunContext.chip`; `Tools.tasks.ui_result_items`, `ui_period_data`(core.py), `occurrence_item`, `ui_event_items`(events.py), `to_api_times`(timefmt.py), `memo_title`(repos/memos.py), `validate_props`(ui.py).
- Produces: `chip_cards(chip: str, ctx: RunContext, tools: Tools, now: datetime) -> list[tuple[str, dict, dict]]` (component, props, output). `Outbound.chip_cards: list[tuple[str, dict, dict]]`. `harness_cards`가 맨 뒤에 `("h_chip", component, props, output)`으로 붙인다.

- [ ] Step 1: 실패 시험 작성(`chip_cards` 단위 + 디스패처 스트림 통합 각 1개 이상).
  - `event`: 두뇌가 `create_event`만 → `ui_events` 1개, 그 일정 줄. 두뇌가 `ui_events`도 그림 → 칩 카드 없음. 두뇌 조각 2개 → 칩 카드 없음. 반복 일정 → 시작일 1줄.
  - `todo`: `add_task` 1개 → `ui_result`; 3개 → `ui_period_list`(첫 날짜, highlight 3개); 첫 날짜가 오늘+60일 → `ui_result` 앞 2개; `create_event`만 → `ui_events`; 아무것도 안 만듦 → 없음.
  - `memo`: `create_memo` → `ui_summary_card`(`title`=`memo_title`, 줄 앞 3개 / 한 줄 메모면 `["메모 탭에서 볼 수 있어요."]`).
  - `today`: 글만 → `ui_period_list(day=논리적 오늘)`; 01:30에 보내면 전날.
  - `next`: 일정 없음 → 없음; 내일 하루 종일 + 오늘 15:00 + 지난 09:00 → 15:00, 내일 하루 종일 순(지난 것 뺌).
  - 두뇌 오류(재시도 끝), `capped`, 재생(같은 `client_msg_id`) → 칩 카드 없음.
  - 붙인 카드 props가 `validate_props`를 통과하고, 실패하는 경우(일부러 깨진 입력)는 붙이지 않고 `chip_card_invalid` 로그.
- [ ] Step 2: 실패 확인.
- [ ] Step 3: 구현(스펙 4.4 표 그대로). 정상 답 경로(`result.status == "ok"`)에서만 `chip_cards`를 불러 `_reply_out`에 인자로 넘긴다. 남은 자리 = 2 − `ctx.ui_drawn`.
- [ ] Step 4: 시험 통과 + 전체 `uv run pytest -q`. 앱 타입 생성은 바뀌지 않는다(스키마 변경은 `ChatRequestBody.chip`뿐: `cd web/app && MP_SCHEMA_CMD="… -m my_planner schema" npm run gen:types`를 C1a 뒤 한 번 돌려 `types.gen.ts`를 같이 커밋).
- [ ] Step 5: 커밋 `feat(be): harness guarantees the chip's result card`.

### Task C2: 앱 한 줄 쓰기

**Files:**
- Modify: `web/app/src/chat/quickChips.ts` (`Chip.mode: "write" | "send"`), `web/app/src/chat/QuickChips.tsx`, `web/app/src/chat/ChatSheet.tsx`, `web/app/src/chat/transport.ts`(요청 본문 `chip`, 400 때 칩 없이 한 번 다시), `web/app/src/chat/MessageView.tsx`(머리표), `web/app/src/lib/copy.ts`(스펙 5장 문구), CSS 모듈
- Test: `web/app/src/chat/ChatSheet.test.tsx`, `QuickChips.test.tsx`, `quickChips.test.ts`, `transport.test.ts`

**Interfaces:**
- Consumes: C1a의 요청 칸 `chip`(types.gen `ChatRequestBody.chip`).
- Produces: 사용자 메시지 `metadata.chip`; `copy.chat.write = { todo, event, memo }`(placeholder), `copy.chat.chipLabel = { todo: "할 일 추가", event: "일정 추가", memo: "메모" }`, `copy.chat.closeWrite = "한 줄 쓰기 닫기"`.

- [ ] Step 1: 실패 시험 작성.
  - `일정 추가` 칩을 누르면 요청이 없고, 표시 `일정 추가`와 닫기 버튼이 뜨고, 칩 줄이 없고, 입력창 placeholder가 `예: 내일 오후 3시 치과`이며 포커스가 있다.
  - 그 상태에서 `내일 오후 3시 치과` 보내기 → 요청 본문 `chip: "event"`, 내 말풍선 위 머리표 `일정 추가`, 보낸 뒤 칩 줄이 돌아온다.
  - 닫기 버튼 → 칩 줄로, 쓰던 글은 남는다. 빈 입력창 Backspace → 닫힘. 새 대화·목록 열기 → 닫힘.
  - `오늘 정리해줘` → 바로 문장 전송 + `chip: "today"`. 체크인 칩 → `chip` 없음(`checkin_id`만).
  - 400 `invalid_request`가 칩 메시지에 오면 같은 `client_msg_id`로 `chip` 없이 한 번 다시 보내고, 칩 없는 메시지의 400은 다시 보내지 않는다.
  - 다시 연 대화(기록)에는 머리표가 없다.
- [ ] Step 2: 실패 확인(`cd web/app && npx vitest run src/chat`).
- [ ] Step 3: 구현.
- [ ] Step 4: `npm test`, `npm run test:tz`, `npm run typecheck`, `NEXT_PUBLIC_CONNECT_SRC=https://example.ts.net npm run build`, `npm run size`(→ `OK …KB ≤ 180KB`), `npm run check:csp`, `npm run lint:copy`.
- [ ] Step 5: 커밋 `feat(app): quick chips open a one-line write in the chat input`.

## 전달

- C1a+C1b → BE PR 하나, C2 → 앱 PR 하나(앱은 400 대체가 있어 순서 자유). 각 PR은 code-reviewer 리뷰 후 자체 병합.
- 병합 뒤 Dahun 확인: 노트북 BE 갱신 후 폰에서 칩 3개(할 일·일정·메모)와 `오늘 정리해줘`에 카드가 뜨는지, 스펙 5장 새 문구 확인.

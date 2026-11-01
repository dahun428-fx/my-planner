import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { readUIMessageStream, type UIMessage, type UIMessageChunk } from "ai";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { validateModel } from "../api/validate";
import { copy } from "../lib/copy";
import { events, gatedResponse, golden, serveChat, sse, sseResponse } from "../test/chat";
import todayJson from "../test/fixtures/today.json";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { ChatSheet } from "./ChatSheet";
import { loadParts } from "./localParts";
import { buildChatBody } from "./transport";
import { toViewParts } from "./parts";

// Spec 13장 "대화 계약", 1장 완료 조건 4: the BE's golden SSE files, read from the repo, through
// useChat + parts.ts to what the sheet shows.

// SP9 9.5: the sheet reads /today for its quick chips.
beforeEach(() => {
  server.use(http.get(`${BASE}/today`, () => HttpResponse.json(todayJson)));
});

afterEach(async () => {
  await clear();
});

const noop = () => {};

async function openSheet() {
  const user = userEvent.setup();
  renderWithProviders(<ChatSheet open onClose={noop} conversationId={null} />);
  const input = await screen.findByRole("textbox", { name: copy.chat.inputLabel });
  await waitFor(() => expect(input).toBeEnabled());
  return {
    user,
    send: async (text: string) => {
      await user.type(input, text);
      await user.click(screen.getByRole("button", { name: copy.chat.send }));
    },
  };
}

const addTask = golden("chat_add_task.sse");
const ADD_TASK_TEXT = "내일 치과를 추가할게요.";
const confirmation = (() => {
  const ev = events(addTask).find((e) => e.includes('"data-activity"'));
  const data = (JSON.parse(ev!.slice("data: ".length)) as { data: { confirmation?: string } }).data;
  return data.confirmation ?? null;
})();

// BE 09's golden: propose_tasks (brain, not drawn), a text, then the harness part h_draft_1
// (ui_todo_draft) whose output carries the TodoRefs behind its ids.
const proposeTasks = golden("chat_propose_tasks.sse");
const PROPOSE_TEXT = "이번 주에 이 둘을 해 보면 어때요?";
const proposeMessageId = (JSON.parse(events(proposeTasks)[0].slice("data: ".length)) as { messageId: string }).messageId;
const draftPart = (() => {
  const ev = events(proposeTasks).find((e) => e.includes('"toolCallId":"h_draft_1"') && e.includes('"tool-output-available"'));
  return (JSON.parse(ev!.slice("data: ".length)) as { output: { data: unknown } }).output.data;
})();

describe("chat contract", () => {
  it("add_task: text, status line, conversation id, confirmation line and toast undo", async () => {
    // Stop after `queued`, then after `thinking`, so the status line can be seen on its way.
    const first = gatedResponse(addTask, [2, 3]);
    const bodies = serveChat(first.response, () => sseResponse(golden("chat_replay.sse")));
    const { send } = await openSheet();
    await send("내일 치과 추가해 줘");

    expect(await screen.findByText(copy.chat.queued)).toBeInTheDocument();
    expect(screen.getByText("내일 치과 추가해 줘")).toBeInTheDocument();
    first.release();
    expect(await screen.findByLabelText(copy.chat.thinking)).toBeInTheDocument();
    expect(screen.queryByText(copy.chat.queued)).toBeNull();
    first.release();

    expect(await screen.findByText(ADD_TASK_TEXT)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText(copy.chat.thinking)).toBeNull());
    expect(screen.queryByText(copy.chat.queued)).toBeNull();
    // add_task itself is not drawn; the confirmation stands for it (R4b) as one line, and the
    // toast holds the undo (SP9 9.6).
    const undo = await screen.findByRole("button", { name: copy.chat.undo });
    const log = screen.getByRole("log");
    expect(within(log).queryByRole("button", { name: copy.chat.undo })).toBeNull();
    if (confirmation !== null) {
      const line = within(log).getByText(confirmation);
      expect(line.closest("[data-activity]")).not.toBeNull();
      expect(undo.closest("[role=status]")).toHaveTextContent(confirmation);
    } else {
      expect(within(log).getByText(copy.chat.changed)).toBeInTheDocument(); // before R4b: still one line
    }
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
    expect(bodies[0]).toMatchObject({ conversation_id: null, checkin_id: null });

    // The next message carries the conversation id from the `start` metadata.
    await send("고마워");
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].conversation_id).toBe(1);
  });

  it("propose_tasks: ui_todo_draft after the text, kept in localParts", async () => {
    serveChat(() => sseResponse(proposeTasks));
    const { send } = await openSheet();
    await send("이번 주 할 일 정리해 줘");
    const first = await screen.findByText("물 마시기");
    const second = screen.getByText("스트레칭");
    const before = screen.getByText(PROPOSE_TEXT);
    expect(before.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(copy.parts.draftHeading)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.parts.confirmCount(2) })).toBeInTheDocument();
    // propose_tasks is a brain tool: not drawn (the part stands for it), and nothing unknown.
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
    await waitFor(async () =>
      expect(await loadParts(proposeMessageId)).toEqual([
        { kind: "ui", toolCallId: "h_draft_1", name: "ui_todo_draft", props: { task_ids: [1, 2] }, data: draftPart },
      ]),
    );
  });

  it("daily_cap: one fixed text, no error", async () => {
    serveChat(() => sseResponse(golden("chat_daily_cap.sse")));
    const { send } = await openSheet();
    await send("오늘 뭐 할까");
    expect(await screen.findByText("오늘은 여기까지 생각을 아껴 둘게요. 명령(/today)은 계속 쓸 수 있어요.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.send })).toBeDisabled()); // empty input
    expect(screen.queryByText(copy.chat.notReceived)).toBeNull();
    expect(screen.queryByRole("button", { name: copy.chat.retry })).toBeNull();
    expect(screen.queryByText(copy.chat.queued)).toBeNull();
  });

  it("replay: one text part", async () => {
    serveChat(() => sseResponse(golden("chat_replay.sse")));
    const { send } = await openSheet();
    await send("내일 치과 추가해 줘");
    expect(await screen.findByText(ADD_TASK_TEXT)).toBeInTheDocument();
    const log = screen.getByRole("log");
    expect(within(log).getAllByText(ADD_TASK_TEXT)).toHaveLength(1);
  });

  it("add_task_streamed: one growing text per block id", async () => {
    // Stop after the first delta of t1: the block shows what has come, then grows in place.
    const gate = gatedResponse(golden("chat_add_task_streamed.sse"), [6]);
    serveChat(gate.response);
    const { send } = await openSheet();
    await send("내일 치과 추가해 줘");
    const partial = await screen.findByText("내일 치과를");
    gate.release();
    expect(await screen.findByText(ADD_TASK_TEXT)).toBe(partial);
    const log = screen.getByRole("log");
    expect(within(log).getAllByText(ADD_TASK_TEXT)).toHaveLength(1);
    expect(within(log).queryByText("내일 치과를")).toBeNull();
    expect(await screen.findByRole("button", { name: copy.chat.undo })).toBeInTheDocument();
  });

  it("retry_streamed: the earlier partial text stays and the new block follows", async () => {
    serveChat(() => sseResponse(golden("chat_retry_streamed.sse")));
    const { send } = await openSheet();
    await send("내일 치과 추가해 줘");
    const full = await screen.findByText(ADD_TASK_TEXT);
    const log = screen.getByRole("log");
    const partial = within(log).getByText("내일 치과를");
    expect(partial).not.toBe(full);
    expect(partial.compareDocumentPosition(full) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(log).getAllByText(ADD_TASK_TEXT)).toHaveLength(1);
    expect(within(log).getAllByText("내일 치과를")).toHaveLength(1);
    expect(screen.queryByText(copy.chat.notReceived)).toBeNull();
  });

  it("reconnect regenerates with same id", async () => {
    // The first answer breaks after its text started; the resend gets the stored answer (6.4.1).
    const cut = gatedResponse(addTask, [7], { cut: true });
    const bodies = serveChat(cut.response, () => sseResponse(golden("chat_replay.sse")));
    const { send } = await openSheet();
    await send("내일 치과 추가해 줘");
    await waitFor(() => expect(bodies).toHaveLength(1));
    cut.release();
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].client_msg_id).toBe(bodies[0].client_msg_id);
    expect((bodies[1].message as { id: string }).id).toBe((bodies[0].message as { id: string }).id);
    expect(await screen.findByText(ADD_TASK_TEXT)).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByRole("log")).getAllByText(ADD_TASK_TEXT)).toHaveLength(1));
    expect(screen.queryByText(copy.chat.notReceived)).toBeNull();
    expect(within(screen.getByRole("log")).getAllByText("내일 치과 추가해 줘")).toHaveLength(1);
  });

  it("a second cut shows the retry button, which sends the same id again", async () => {
    const cuts = [gatedResponse(addTask, [3], { cut: true }), gatedResponse(addTask, [3], { cut: true })];
    const bodies = serveChat(cuts[0].response, cuts[1].response, () => sseResponse(golden("chat_replay.sse")));
    const { user, send } = await openSheet();
    await send("내일 치과 추가해 줘");
    cuts[0].release();
    await waitFor(() => expect(bodies).toHaveLength(2));
    cuts[1].release();
    const retry = await screen.findByRole("button", { name: copy.chat.retry });
    expect(screen.getByText(copy.chat.notReceived)).toBeInTheDocument();
    expect(bodies).toHaveLength(2);
    await user.click(retry);
    expect(await screen.findByText(ADD_TASK_TEXT)).toBeInTheDocument();
    expect(bodies).toHaveLength(3);
    expect(new Set(bodies.map((b) => b.client_msg_id)).size).toBe(1);
    expect(screen.queryByRole("button", { name: copy.chat.retry })).toBeNull();
  });

  it("protocol error does not resend", async () => {
    const body = sse([
      { type: "start", messageId: "m-1-9", messageMetadata: { conversation_id: 1, channel: "app", kind: "chat", checkin_id: null } },
      { type: "error", errorText: "bad" },
      { type: "finish" },
      "[DONE]",
    ]);
    const bodies = serveChat(() => sseResponse(body));
    const { send } = await openSheet();
    await send("안녕");
    expect(await screen.findByText(copy.chat.notReceived)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 30));
    expect(bodies).toHaveLength(1);
    expect(screen.queryByRole("button", { name: copy.chat.retry })).toBeNull();
  });

  it("409 while the same message is still being answered offers 다시 받기 with the same id", async () => {
    const { HttpResponse } = await import("msw");
    const inFlight = () => HttpResponse.json({ error: { code: "conflict", message: "같은 메시지를 처리하고 있어요." } }, { status: 409 });
    const bodies = serveChat(inFlight, () => sseResponse(golden("chat_replay.sse")));
    const { user, send } = await openSheet();
    await send("내일 치과 추가해 줘");
    const retry = await screen.findByRole("button", { name: copy.chat.retry });
    expect(bodies).toHaveLength(1); // not sent again at once: the answer is still being made
    await user.click(retry);
    expect(await screen.findByText(ADD_TASK_TEXT)).toBeInTheDocument();
    expect(bodies).toHaveLength(2);
    expect(bodies[1].client_msg_id).toBe(bodies[0].client_msg_id);
  });

  it("a 4xx answer does not resend", async () => {
    const { HttpResponse } = await import("msw");
    const bodies = serveChat(() => HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 }));
    const { send } = await openSheet();
    await send("안녕");
    expect(await screen.findByText(copy.chat.notReceived)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 30));
    expect(bodies).toHaveLength(1);
  });
});

// SP6 13장 "앱 대화 계약" (G-A3): G-BE2's golden answers for the four new cards, read in place.
// The activity line ("✓ …") is the "확인 칸": it stays unless a drawn ui_result shows every
// activity it stands for (hideCoveredActivity). No hand-written SSE for these cards remains.
const activityLine = () => screen.getByRole("log").querySelector("[data-activity]");
const confirmationOf = (body: string) => {
  const ev = events(body).find((e) => e.includes('"data-activity"'));
  return (JSON.parse(ev!.slice("data: ".length)) as { data: { confirmation: string } }).data.confirmation;
};
const cards = () => screen.getByRole("log").querySelectorAll("section");

/** A golden answer as useChat's stream makes it, through the AI SDK's own reader. */
async function goldenMessage(name: string): Promise<UIMessage> {
  const chunks = events(golden(name))
    .map((e) => e.slice("data: ".length))
    .filter((d) => d !== "[DONE]")
    .map((d) => JSON.parse(d) as UIMessageChunk);
  const stream = new ReadableStream<UIMessageChunk>({
    start(c) {
      chunks.forEach((ch) => c.enqueue(ch));
      c.close();
    },
  });
  let last: UIMessage | undefined;
  for await (const m of readUIMessageStream({ stream, terminateOnError: true })) last = m;
  return last!;
}

describe("chat contract: SP6 cards (golden)", () => {
  it("date_choice: DateChoice draws, no ui_result, the activity line stays", async () => {
    const body = golden("chat_date_choice.sse");
    serveChat(() => sseResponse(body));
    const { send } = await openSheet();
    await send("치과 예약 추가해 줘");
    expect(await screen.findByText("치과 예약은 언제 할까요?")).toBeInTheDocument();
    const log = screen.getByRole("log");
    // add_task is a brain tool (not drawn); the card is the only part, its to-do's title under the question.
    expect(cards()).toHaveLength(1);
    const card = within(cards()[0] as HTMLElement);
    expect(card.getByText("치과 예약")).toBeInTheDocument();
    for (const day of ["10월 27일 (화)", "10월 28일 (수)", "10월 30일 (금)"]) {
      expect(card.getByRole("button", { name: new RegExp(`^${day.replace(/[()]/g, "\\$&")}`) })).toBeEnabled();
    }
    expect(card.getByRole("button", { name: "10월 27일 (화) 오후가 비어요" })).toBeInTheDocument();
    expect(card.getByRole("button", { name: copy.parts.otherDay })).toBeEnabled();
    expect(within(log).queryByText(copy.parts.changeChip.moved)).toBeNull();
    expect(within(log).queryByText(copy.parts.changeChip.added)).toBeNull();
    // The golden's confirmation: add_task now plans the to-do for today.
    expect(confirmationOf(body)).toBe("✓ 추가: 치과 예약 → 오늘");
    await waitFor(() => expect(activityLine()).toHaveTextContent("✓ 추가: 치과 예약 → 오늘"));
    expect(await screen.findByRole("button", { name: copy.chat.undo })).toBeInTheDocument(); // the toast's
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
  });

  it("result: Result draws and the activity line it covers is hidden", async () => {
    const body = golden("chat_result.sse");
    serveChat(() => sseResponse(body));
    const { send } = await openSheet();
    await send("장보기 화요일로 옮겨 줘");
    expect(await screen.findByText("화요일로 옮겼어요.")).toBeInTheDocument();
    const card = within(cards()[0] as HTMLElement);
    expect(cards()).toHaveLength(1);
    expect(card.getByText(copy.parts.changeChip.moved)).toBeInTheDocument();
    expect(card.getByText("꾸민 장보기")).toBeInTheDocument();
    expect(card.getByRole("img", { name: copy.parts.changeAria("10월 25일 (일)", "10월 27일 (화)") })).toBeInTheDocument();
    // Nothing to press on the card (SP9 9.6): the undo is the toast's, with the same confirmation.
    expect(card.queryByRole("button")).toBeNull();
    const undo = await screen.findByRole("button", { name: copy.chat.undo });
    expect(undo.closest("[role=status]")).toHaveTextContent(confirmationOf(body));
    expect(activityLine()).toBeNull();
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
  });

  it("period_list: PeriodList draws, three changed rows, the activity line stays", async () => {
    const body = golden("chat_period_list.sse");
    serveChat(() => sseResponse(body));
    const { send } = await openSheet();
    await send("다음 주로 나눠 옮겨 줘");
    expect(await screen.findByText("다음 주로 나눠 옮겼어요.")).toBeInTheDocument();
    expect(cards()).toHaveLength(1);
    const section = cards()[0] as HTMLElement;
    const card = within(section);
    expect(card.getByRole("heading", { name: copy.parts.nextWeek })).toBeInTheDocument();
    expect(card.getByText(copy.parts.dayHead(29, "목"))).toBeInTheDocument();
    expect(card.getByText(copy.parts.outsideHead.moved)).toBeInTheDocument();
    // The three moved to-dos carry the --hue bar (and its spoken words); the fourth row does not.
    expect(card.getAllByText(copy.parts.changedBySecretary)).toHaveLength(3);
    for (const title of ["꾸민 보고서 초안", "꾸민 화분 분갈이", "꾸민 산책"]) {
      expect(card.getByText(title).closest("li"), title).toHaveTextContent(copy.parts.changedBySecretary);
    }
    expect(card.getByText("꾸민 독서 모임").closest("li")).not.toHaveTextContent(copy.parts.changedBySecretary);
    // A ui_period_list does not cover the activities: the line stays, all three changes in it.
    await waitFor(() => expect(activityLine()).not.toBeNull());
    expect(activityLine()!.textContent).toBe(confirmationOf(body));
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
  });

  it("block: Block draws with its todo_rows row", async () => {
    serveChat(() => sseResponse(golden("chat_block.sse")));
    const { send } = await openSheet();
    await send("이번 주 운동 어땠지");
    expect(await screen.findByText("이번 주 운동이에요.")).toBeInTheDocument();
    expect(cards()).toHaveLength(1);
    const section = cards()[0] as HTMLElement;
    const card = within(section);
    expect(card.getByRole("heading", { name: "이번 주 운동" })).toBeInTheDocument();
    expect(card.getByText("3회")).toBeInTheDocument();
    expect(section.querySelector("progress")).toHaveAttribute("value", "3");
    expect(card.getByRole("checkbox", { name: copy.parts.checkLabel("꾸민 저녁 운동") })).toBeEnabled();
    expect(card.getByRole("button", { name: "운동 끝났어" })).toBeEnabled();
    expect(section.querySelector("strong")).toHaveTextContent("목요일");
    expect(activityLine()).toBeNull();
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
  });

  it("ui_rejected: only the part the BE accepted reaches the app", async () => {
    const body = golden("chat_ui_rejected.sse");
    expect(events(body).filter((e) => e.includes('"tool-input-available"'))).toHaveLength(1);
    serveChat(() => sseResponse(body));
    const { send } = await openSheet();
    await send("이번 주 운동 어땠지");
    expect(await screen.findByText("이번 주 운동이에요.")).toBeInTheDocument();
    expect(cards()).toHaveLength(1);
    expect(screen.getAllByRole("heading", { name: "이번 주 운동" })).toHaveLength(1);
    expect(screen.queryByText(copy.parts.unknown)).toBeNull();
    await waitFor(async () => expect((await loadParts("<id>"))?.map((p) => p.kind === "ui" && p.name)).toEqual(["ui_block"]));
  });

  it.each([
    ["chat_date_choice.sse", [1]],
    ["chat_result.sse", [2]],
    ["chat_period_list.sse", [5, 6, 7]],
    ["chat_gallery.sse", [4]],
  ])("activityIds read from %s", async (name, ids) => {
    const parts = toViewParts(await goldenMessage(name));
    const acts = parts.filter((p) => p.kind === "activity");
    expect(acts).toEqual([{ kind: "activity", confirmation: confirmationOf(golden(name)), undoIds: ids, activityIds: ids }]);
  });
});


// SP12 5.2: `POST /chat` names the partner; the field is the schema's (an enum of the two).
describe("ChatRequestBody agent (SP12)", () => {
  const msg = { id: "m1", role: "user" as const, parts: [{ type: "text" as const, text: "오늘 뭐 할까?" }], metadata: { chip: "mate_today" as const } };

  it("the mate's body matches the schema", () => {
    const body = buildChatBody([msg], { conversationId: null, checkinId: null, agent: "mate" });
    expect(body.agent).toBe("mate");
    expect(body.chip).toBe("mate_today");
    expect(validateModel("ChatRequestBody", body)).toBe(true);
  });

  it("the secretary's body carries no agent and still matches", () => {
    const body = buildChatBody([msg], { conversationId: null, checkinId: null, agent: "secretary" });
    expect(body).not.toHaveProperty("agent");
    expect(validateModel("ChatRequestBody", body)).toBe(true);
  });

  it("the schema takes only the two partners", () => {
    const base = { client_msg_id: "m1", message: { id: "m1", role: "user", parts: [{ type: "text", text: "x" }] } };
    expect(validateModel("ChatRequestBody", { ...base, agent: "secretary" })).toBe(true);
    expect(validateModel("ChatRequestBody", { ...base, agent: "mate" })).toBe(true);
    expect(validateModel("ChatRequestBody", { ...base, agent: "coach" })).toBe(false);
  });
});

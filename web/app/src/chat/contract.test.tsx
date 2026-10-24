import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../lib/copy";
import { events, gatedResponse, golden, serveChat, sse, sseResponse } from "../test/chat";
import { renderWithProviders } from "../test/render";
import { ChatSheet } from "./ChatSheet";
import { loadParts } from "./localParts";

// Spec 13장 "대화 계약", 1장 완료 조건 4: the BE's golden SSE files, read from the repo, through
// useChat + parts.ts to what the sheet shows.

afterEach(async () => {
  await clear();
});

const noop = () => {};

async function openSheet() {
  const user = userEvent.setup();
  renderWithProviders(<ChatSheet open onClose={noop} conversationId={null} />, { catalog: true });
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
  it("add_task: text, status line, conversation id, confirmation and undo", async () => {
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
    // add_task itself is not drawn; the confirmation stands for it (R4b), with undo.
    const undo = await screen.findByRole("button", { name: copy.chat.undo });
    if (confirmation !== null) {
      const box = screen.getByText(confirmation);
      expect(box.closest("[data-activity]")).toContainElement(undo);
    } else {
      expect(screen.queryByText(/✓/)).toBeNull(); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
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

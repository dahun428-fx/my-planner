import "fake-indexeddb/auto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import type { AppProps } from "next/app";
import { RouterContext } from "next/dist/shared/lib/router-context.shared-runtime";
import { afterEach, describe, expect, it, vi } from "vitest";
import { saveConn } from "../lib/connection";
import { copy } from "../lib/copy";
import { formatKst } from "../lib/time";
import App from "../pages/_app";
import { Activity } from "../screens/Activity";
import { Today } from "../screens/Today";
import { Todos } from "../screens/Todos";
import weekJson from "../test/fixtures/week.json";
import { gatedResponse, golden, type HistoryItem, serveChat, serveHistory, sse, sseResponse } from "../test/chat";
import todayJson from "../test/fixtures/today.json";
import healthJson from "../test/fixtures/health.json";
import catalogJson from "../test/fixtures/catalog.json";
import { useChatSheet } from "./sheetContext";
import { healthAnswers } from "../test/handlers";
import { mockRouter, renderWithProviders, TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { ChatSheet } from "./ChatSheet";
import { chatSheetChunk } from "./loadChatSheet";
import { saveParts } from "./localParts";
import type { ViewPart } from "./parts";

afterEach(async () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  await clear();
});

const draftTodo = { id: 7, title: "장보기", status: "draft", areas: [], planned_for: "2026-10-25", scheduled_at: null, parent_id: null, note: "", priority: null, completed_at: null };
const draftPart: ViewPart = { kind: "ui", toolCallId: "h_1", name: "ui_todo_draft", props: { task_ids: [7] }, data: { todos: [draftTodo] as never } };

// A draft card kept on the device for the saved BE (as the sheet does when an answer finishes).
async function keepDraft() {
  saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
  await saveParts("m-5-1", [draftPart], TEST_BE_URL);
}

const start = (messageId: string, conversationId: number) => ({
  type: "start",
  messageId,
  messageMetadata: { conversation_id: conversationId, channel: "app", kind: "chat", checkin_id: null },
});
const textAnswer = (messageId: string, conversationId: number, text: string, extra: object[] = []) =>
  sse([
    start(messageId, conversationId),
    { type: "start-step" },
    { type: "text-start", id: "t1" },
    { type: "text-delta", id: "t1", delta: text },
    { type: "text-end", id: "t1" },
    ...extra,
    { type: "finish-step" },
    { type: "finish", messageMetadata: { conversation_id: conversationId, channel: "app", kind: "chat" } },
    "[DONE]",
  ]);

const history = (conversationId: number, items: HistoryItem[], extra: Parameters<typeof serveHistory>[0] = {}) =>
  serveHistory({ conversations: [{ id: conversationId, last_message_at: items[items.length - 1]?.at ?? "2026-10-24T00:00:00Z" }], messages: { [conversationId]: items }, ...extra });

async function ready() {
  const input = await screen.findByRole("textbox", { name: copy.chat.inputLabel });
  await waitFor(() => expect(input).toBeEnabled());
  return input;
}

async function sendText(user: ReturnType<typeof userEvent.setup>, text: string) {
  const input = await ready();
  await user.type(input, text);
  await user.click(screen.getByRole("button", { name: copy.chat.send }));
}

describe("ChatSheet", () => {
  it("restores last conversation with local parts", async () => {
    await keepDraft();
    const seen = history(5, [
      { id: "u-5-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "이번 주 정리해 줘" },
      { id: "m-5-1", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "골라 봤어요" },
      { id: "l-5-2", at: "2026-10-24T01:01:00Z", speaker: "secretary", text: "다른 줄이에요" },
    ]);
    const bodies = serveChat(() => sseResponse(golden("chat_replay.sse")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("골라 봤어요")).toBeInTheDocument();
    expect(screen.getByText("이번 주 정리해 줘")).toBeInTheDocument();
    expect(await screen.findByText("장보기")).toBeInTheDocument();
    expect(screen.getByText("다른 줄이에요")).toBeInTheDocument();
    // The part sits with the message it came with.
    const own = screen.getByText("골라 봤어요").closest("[data-message]") as HTMLElement;
    expect(within(own).getByText("장보기")).toBeInTheDocument();
    expect(seen.messages).toEqual([5]);
    await sendText(user, "고마워");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].conversation_id).toBe(5);
  });

  it("a restored draft card does not write: its rows may have changed since it was kept", async () => {
    await keepDraft();
    history(5, [{ id: "m-5-1", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "골라 봤어요" }]);
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("장보기")).toBeInTheDocument();
    await ready();
    expect(screen.getByRole("checkbox", { name: copy.parts.checkLabel("장보기") })).toBeDisabled();
    expect(screen.queryByRole("button", { name: copy.parts.dropChecked })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.parts.confirmCount(1) })).toBeNull();
  });

  it("restores text only from a BE without message ids (before R4d)", async () => {
    await keepDraft();
    history(5, [
      { at: "2026-10-24T01:00:00Z", speaker: "user", text: "이번 주 정리해 줘" },
      { at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "골라 봤어요" },
    ]);
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("골라 봤어요")).toBeInTheDocument();
    await ready();
    expect(screen.queryByText("장보기")).toBeNull();
  });

  it("opens given conversation id", async () => {
    const seen = serveHistory({ messages: { 8: [{ id: "m-8-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "체크인 대화예요" }] } });
    const bodies = serveChat(() => sseResponse(textAnswer("m-8-2", 8, "네")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={8} checkinId={341} />);
    expect(await screen.findByText("체크인 대화예요")).toBeInTheDocument();
    expect(seen.conversations).toBe(0);
    await sendText(user, "3점이요");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ conversation_id: 8, checkin_id: 341 });
  });

  it("opens an empty conversation for null", async () => {
    const seen = serveHistory({ conversations: [{ id: 5, last_message_at: "2026-10-24T01:00:00Z" }] });
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await ready();
    expect(seen.conversations).toBe(0);
    expect(seen.messages).toEqual([]);
    expect(within(screen.getByRole("log")).queryAllByText(/./)).toHaveLength(0);
  });

  it("time divider rules", async () => {
    history(5, [
      { id: "u-5-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "하나" },
      { id: "m-5-1", at: "2026-10-24T01:09:00Z", speaker: "secretary", text: "둘" },
      { id: "u-5-2", at: "2026-10-24T01:20:00Z", speaker: "user", text: "셋" },
    ]);
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("셋")).toBeInTheDocument();
    const at = (iso: string) => formatKst(iso, "HH:mm");
    expect(screen.getByText(at("2026-10-24T01:00:00Z"))).toBeInTheDocument(); // the conversation starts
    expect(screen.queryByText(at("2026-10-24T01:09:00Z"))).toBeNull(); // 9 minutes later
    expect(screen.getByText(at("2026-10-24T01:20:00Z"))).toBeInTheDocument(); // 11 minutes later
  });

  it("drag down closes", async () => {
    serveHistory();
    const onClose = vi.fn();
    renderWithProviders(<ChatSheet open onClose={onClose} conversationId={null} />);
    await ready();
    const handle = document.querySelector("[data-sheet-handle]") as HTMLElement;
    const panel = screen.getByRole("dialog");
    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100, pointerType: "touch" });
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: 200, pointerType: "touch" });
    expect(panel.style.transform).toBe("translateY(100px)");
    fireEvent.pointerUp(handle, { pointerId: 1, clientY: 200, pointerType: "touch" });
    expect(onClose).not.toHaveBeenCalled();
    expect(panel.style.transform).toBe("");
    fireEvent.pointerDown(handle, { pointerId: 2, clientY: 100, pointerType: "touch" });
    fireEvent.pointerMove(handle, { pointerId: 2, clientY: 90, pointerType: "touch" });
    expect(panel.style.transform).toBe("translateY(0px)"); // never above where it sits
    fireEvent.pointerMove(handle, { pointerId: 2, clientY: 230, pointerType: "touch" });
    fireEvent.pointerUp(handle, { pointerId: 2, clientY: 230, pointerType: "touch" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes with an exit animation unless motion is reduced", async () => {
    serveHistory();
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }));
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await ready();
    rerender(<ChatSheet open={false} onClose={() => {}} conversationId={null} />);
    const dialog = screen.getByRole("dialog", { hidden: true });
    expect(dialog.className).toContain("closing");
    fireEvent.animationEnd(dialog);
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();

    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
    rerender(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await ready();
    rerender(<ChatSheet open={false} onClose={() => {}} conversationId={null} />);
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
  });

  it("elsewhere notice max 3", async () => {
    const seen = history(
      5,
      [{ id: "m-5-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "좋아요" }],
      {
        activity: [
          { id: 1, at: "2026-10-24T00:30:00Z", channel: "telegram", summary: "앞선 일" },
          { id: 2, at: "2026-10-24T02:00:00Z", channel: "telegram", summary: "하나" },
          { id: 3, at: "2026-10-24T02:10:00Z", channel: "app", summary: "앱에서 한 일" },
          { id: 4, at: "2026-10-24T02:20:00Z", channel: "telegram", summary: "둘" },
          { id: 5, at: "2026-10-24T02:30:00Z", channel: "scheduler", summary: "셋" },
          { id: 6, at: "2026-10-24T02:40:00Z", channel: "telegram", summary: "넷" },
        ],
      },
    );
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText(copy.chat.elsewhere("넷"))).toBeInTheDocument();
    expect(screen.getByText(copy.chat.elsewhere("셋"))).toBeInTheDocument();
    expect(screen.getByText(copy.chat.elsewhere("둘"))).toBeInTheDocument();
    expect(screen.queryByText(copy.chat.elsewhere("하나"))).toBeNull();
    expect(screen.queryByText(copy.chat.elsewhere("앱에서 한 일"))).toBeNull();
    expect(screen.queryByText(copy.chat.elsewhere("앞선 일"))).toBeNull();
    expect(seen.activitySince).toEqual(["2026-10-24T01:00:00Z"]);
    expect(seen.activityOrder).toEqual(["desc"]);
    // Newest three, shown oldest first.
    const shown = screen.getAllByText(/^다른 곳에서 바뀐 것: /).map((e) => e.textContent);
    expect(shown).toEqual([copy.chat.elsewhere("둘"), copy.chat.elsewhere("셋"), copy.chat.elsewhere("넷")]);
  });

  it("elsewhere lines stay right after the history, before what is said now", async () => {
    history(5, [{ id: "m-5-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "좋아요" }], {
      activity: [{ id: 2, at: "2026-10-24T02:00:00Z", channel: "telegram", summary: "하나" }],
    });
    serveChat(() => sseResponse(textAnswer("m-5-2", 5, "네, 그럴게요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const line = await screen.findByText(copy.chat.elsewhere("하나"));
    await sendText(user, "고마워");
    const reply = await screen.findByText("네, 그럴게요");
    const after = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(after(screen.getByText("좋아요"), line)).toBe(true);
    expect(after(line, screen.getByText("고마워"))).toBe(true);
    expect(after(line, reply)).toBe(true);
  });

  it("a history that cannot be read says so and tries again", async () => {
    let fail = true;
    serveHistory({ conversations: [{ id: 5, last_message_at: "2026-10-24T01:00:00Z" }], messages: { 5: [{ id: "m-5-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "좋아요" }] } });
    server.use(
      http.get(`${BASE}/conversations`, () => (fail ? HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) : undefined)),
    );
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const retry = await screen.findByRole("button", { name: copy.errors.retry });
    expect(screen.getByText(copy.errors.block("internal"))).toBeInTheDocument();
    fail = false;
    await user.click(retry);
    expect(await screen.findByText("좋아요")).toBeInTheDocument();
    expect(screen.queryByText(copy.errors.block("internal"))).toBeNull();
  });

  it("a reply without a conversation id keeps the one in hand", async () => {
    // A command answer with no open app conversation: `conversation_id: null`, no x-conversation-id.
    history(5, [{ id: "m-5-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "좋아요" }]);
    const command = sse([
      { type: "start", messageMetadata: { conversation_id: null, channel: "app", kind: "chat", checkin_id: null } },
      { type: "start-step" },
      { type: "text-start", id: "t1" },
      { type: "text-delta", id: "t1", delta: "오늘 할 일은 셋이에요." },
      { type: "text-end", id: "t1" },
      { type: "finish-step" },
      { type: "finish", messageMetadata: { conversation_id: null, channel: "app", kind: "chat" } },
      "[DONE]",
    ]);
    const headers = { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" };
    const bodies = serveChat(() => sseResponse(command, headers), () => sseResponse(golden("chat_replay.sse")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("좋아요");
    await sendText(user, "/today");
    expect(await screen.findByText("오늘 할 일은 셋이에요.")).toBeInTheDocument();
    expect(screen.queryByText(copy.chat.newConversation)).toBeNull();
    await sendText(user, "고마워");
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].conversation_id).toBe(5);
  });

  it("new conversation divider when id changes", async () => {
    history(5, [{ id: "m-5-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "좋아요" }]);
    const bodies = serveChat(() => sseResponse(textAnswer("m-6-1", 6, "새로 시작해요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("좋아요");
    expect(screen.queryByText(copy.chat.newConversation)).toBeNull();
    await sendText(user, "다른 얘기");
    expect(await screen.findByText("새로 시작해요")).toBeInTheDocument();
    const divider = screen.getByText(copy.chat.newConversation);
    // The line goes before the exchange that opened the new conversation.
    expect(divider.compareDocumentPosition(screen.getByText("다른 얘기")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByText(copy.chat.newConversation)).toHaveLength(1);
    await sendText(user, "이어서");
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].conversation_id).toBe(6);
  });

  it("choice sends label", async () => {
    serveHistory();
    const bodies = serveChat(
      () =>
        sseResponse(
          textAnswer("m-1-1", 1, "어느 쪽부터 할까요?", [
            { type: "tool-input-available", toolCallId: "tc_1", toolName: "ui_choice", input: { question: "무엇부터 할까요?", options: [{ id: "a", label: "운동" }, { id: "b", label: "독서" }] } },
            { type: "tool-output-available", toolCallId: "tc_1", output: { ok: true, data: {} } },
          ]),
        ),
      () => sseResponse(textAnswer("m-1-2", 1, "운동부터 해요")),
    );
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await sendText(user, "뭐부터 할까");
    await user.click(await screen.findByRole("button", { name: "운동" }));
    expect(await screen.findByText("운동부터 해요")).toBeInTheDocument();
    expect(bodies).toHaveLength(2);
    const message = bodies[1].message as { id: string; role: string; parts: { type: string; text: string }[] };
    expect(message.role).toBe("user");
    expect(message.parts).toEqual([{ type: "text", text: "운동" }]);
    expect(bodies[1].client_msg_id).toBe(message.id);
    expect(message.id).not.toBe((bodies[0].message as { id: string }).id);
  });

  it("send disabled while streaming", async () => {
    serveHistory();
    const gate = gatedResponse(golden("chat_add_task.sse"), [2]);
    const bodies = serveChat(gate.response);
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await sendText(user, "내일 치과 추가해 줘");
    const input = screen.getByRole("textbox", { name: copy.chat.inputLabel });
    await user.type(input, "하나 더");
    const send = screen.getByRole("button", { name: copy.chat.send });
    expect(send).toBeDisabled();
    fireEvent.submit(send.closest("form") as HTMLFormElement); // Enter while streaming
    expect(bodies).toHaveLength(1);
    gate.release();
    await waitFor(() => expect(send).toBeEnabled());
    expect(bodies).toHaveLength(1);
  });

  it("double tap on send goes once", async () => {
    serveHistory();
    const bodies = serveChat(() => sseResponse(golden("chat_replay.sse")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    const input = await ready();
    await user.type(input, "안녕");
    const send = screen.getByRole("button", { name: copy.chat.send });
    fireEvent.click(send);
    fireEvent.click(send);
    await screen.findByText("내일 치과를 추가할게요.");
    expect(bodies).toHaveLength(1);
  });

  it("offline shows last view read-only", async () => {
    history(5, [{ id: "m-5-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "좋아요" }]);
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("좋아요");
    await ready();
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    server.use(healthAnswers.unreachable(), http.get(`${BASE}/conversations`, () => HttpResponse.error()));
    rerender(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText(copy.offline.chatLater)).toBeInTheDocument();
    expect(screen.getByText("좋아요")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.chat.send })).toBeDisabled();
  });

  it("undo in the confirmation box", async () => {
    serveHistory();
    serveChat(() => sseResponse(golden("chat_add_task.sse")));
    const undos: unknown[] = [];
    server.use(
      http.post(`${BASE}/activity/:id/undo`, async ({ params, request }) => {
        undos.push({ id: params.id, body: await request.json() });
        return HttpResponse.json({ status: "undone", confirmation: "↩︎ 되돌렸어요: 치과" });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await sendText(user, "내일 치과 추가해 줘");
    const undo = await screen.findByRole("button", { name: copy.chat.undo });
    fireEvent.click(undo);
    fireEvent.click(undo);
    expect(await screen.findByText(copy.chat.undone)).toBeInTheDocument();
    expect(screen.getByText("↩︎ 되돌렸어요: 치과")).toBeInTheDocument(); // toast
    expect(undos).toHaveLength(1);
    expect(undos[0]).toMatchObject({ id: "1" });
    expect(screen.queryByRole("button", { name: copy.chat.undo })).toBeNull();
  });

  it("undo that is blocked or fails says so", async () => {
    serveHistory();
    serveChat(() => sseResponse(golden("chat_add_task.sse")));
    let answer = () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) as Response;
    server.use(http.post(`${BASE}/activity/:id/undo`, () => answer()));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await sendText(user, "내일 치과 추가해 줘");
    await user.click(await screen.findByRole("button", { name: copy.chat.undo }));
    expect(await screen.findByText(copy.actions.undoFailed)).toBeInTheDocument();
    answer = () => HttpResponse.json({ error: { code: "superseded", message: "x" } }, { status: 409 });
    await user.click(screen.getByRole("button", { name: copy.chat.undo }));
    expect(await screen.findByText(copy.activity.undoBlocked.superseded)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.chat.undo })).toBeNull();
  });

  it("confirmation shows once: grey box while streaming, plain text after reopening", async () => {
    // Ruling with the BE thread: /messages keeps the confirmation line in the secretary text, and
    // localParts never keeps data-activity, so a reopened sheet shows it once, as text.
    const seen = serveHistory();
    serveChat(() => sseResponse(golden("chat_add_task.sse")));
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await sendText(user, "내일 치과 추가해 줘");
    const box = await screen.findByText("✓ 추가: 치과 → 내일"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(box.closest("[data-activity]")).not.toBeNull();
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    history(1, [
      { id: "u-1-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "내일 치과 추가해 줘" },
      { id: "<id>", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "내일 치과를 추가할게요.\n✓ 추가: 치과 → 내일" }, // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    ]);
    rerender(<ChatSheet open onClose={() => {}} />);
    await waitFor(() => expect(document.querySelector("[data-activity]")).toBeNull());
    expect(screen.getAllByText(/✓ 추가: 치과 → 내일/)).toHaveLength(1); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(seen.conversations).toBe(1);
  });
});

describe("ChatSheet in the app", () => {
  function mountApp(Component: React.ComponentType = Today, route = "/") {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const hits = { today: 0, week: 0, activity: 0 };
    server.use(
      http.get(`${BASE}/today`, () => {
        hits.today += 1;
        return HttpResponse.json(todayJson);
      }),
      http.get(`${BASE}/week`, () => {
        hits.week += 1;
        return HttpResponse.json(weekJson);
      }),
      http.get(`${BASE}/drafts`, () => HttpResponse.json({ items: [] })),
      http.get(`${BASE}/priorities`, () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 })),
      http.get(`${BASE}/checkins`, () => HttpResponse.json({ items: [] })),
    );
    serveHistory();
    // serveHistory answers /activity for the "elsewhere" lines; the Activity screen reads it too.
    server.use(
      http.get(`${BASE}/activity`, () => {
        hits.activity += 1;
        return HttpResponse.json({ items: [], next_before: null, next_since: null });
      }),
    );
    const router = mockRouter(route);
    render(
      <RouterContext.Provider value={router}>
        <App {...({ Component, pageProps: {}, router } as unknown as AppProps)} />
      </RouterContext.Provider>,
    );
    return hits;
  }

  async function openFromLauncher(user: ReturnType<typeof userEvent.setup>) {
    const launcher = await screen.findByRole("button", { name: copy.chat.launcher });
    await waitFor(() => expect(launcher).toBeEnabled());
    await user.click(launcher);
    await screen.findByRole("dialog");
    await ready();
    return launcher;
  }

  it("a chat chunk that fails to load leaves the screen, says so, and loads on the next tap", async () => {
    const load = vi.spyOn(chatSheetChunk, "load").mockRejectedValueOnce(new Error("chunk 404"));
    mountApp();
    const user = userEvent.setup();
    const launcher = await screen.findByRole("button", { name: copy.chat.launcher });
    await waitFor(() => expect(launcher).toBeEnabled());
    await user.click(launcher);
    expect(await screen.findByText(copy.chat.openFailed)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("운동 30분")).toBeInTheDocument();
    await user.click(launcher);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("todos: the launcher opens the sheet and closing reads the lists again", async () => {
    const hits = mountApp(Todos, "/todos/");
    const user = userEvent.setup();
    await openFromLauncher(user);
    const before = hits.week;
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: copy.chat.close }));
    await waitFor(() => expect(hits.week).toBe(before + 1));
  });

  it("activity: the launcher opens the sheet and closing reads the log again", async () => {
    const hits = mountApp(Activity, "/activity/");
    const user = userEvent.setup();
    await openFromLauncher(user);
    const before = hits.activity;
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: copy.chat.close }));
    await waitFor(() => expect(hits.activity).toBe(before + 1));
  });

  it("focus returns to launcher on close", async () => {
    mountApp();
    const user = userEvent.setup();
    const launcher = await screen.findByRole("button", { name: copy.chat.launcher });
    await waitFor(() => expect(launcher).toBeEnabled());
    await user.click(launcher);
    const dialog = await screen.findByRole("dialog");
    await ready();
    await user.click(within(dialog).getByRole("button", { name: copy.chat.close }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(launcher).toHaveFocus();
  });

  it("closing refreshes today", async () => {
    const hits = mountApp();
    const user = userEvent.setup();
    const launcher = await screen.findByRole("button", { name: copy.chat.launcher });
    await waitFor(() => expect(launcher).toBeEnabled());
    await user.click(launcher);
    await ready();
    const before = hits.today;
    await user.keyboard("{Escape}");
    await waitFor(() => expect(hits.today).toBe(before + 1));
  });

  it("another BE address starts a fresh sheet: no old lines, no old conversation id", async () => {
    const OTHER = "https://other.example.ts.net";
    const OTHER_API = `${OTHER}/api/v1`;
    const Page = () => {
      const chat = useChatSheet();
      return (
        <button type="button" onClick={() => chat.open()}>
          open-sheet
        </button>
      );
    };
    mountApp(Page, "/");
    serveChat(() => sseResponse(textAnswer("m-5-1", 5, "first BE answer")));
    const otherChat: Record<string, unknown>[] = [];
    server.use(
      http.get(`${OTHER_API}/health`, () => HttpResponse.json(healthJson)),
      http.get(`${OTHER_API}/ui/catalog`, () => HttpResponse.json(catalogJson)),
      // The new BE's history cannot be read: nothing of the old one may stand in for it.
      http.get(`${OTHER_API}/conversations`, () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 })),
      http.get(`${OTHER_API}/activity`, () => HttpResponse.json({ items: [], next_before: null, next_since: null })),
      http.post(`${OTHER_API}/chat`, async ({ request }) => {
        otherChat.push((await request.json()) as Record<string, unknown>);
        return sseResponse(textAnswer("m-9-1", 9, "second BE answer"));
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "open-sheet" }));
    await sendText(user, "hello");
    expect(await screen.findByText("first BE answer")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    act(() => saveConn({ beUrl: OTHER, token: TEST_TOKEN }));
    await user.click(screen.getByRole("button", { name: "open-sheet" }));
    await sendText(user, "hello again");
    expect(await screen.findByText("second BE answer")).toBeInTheDocument();
    expect(screen.queryByText("first BE answer")).toBeNull();
    expect(otherChat).toHaveLength(1);
    expect(otherChat[0].conversation_id).toBeNull();
  });
});

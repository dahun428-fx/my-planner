import "fake-indexeddb/auto";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import type { AppProps } from "next/app";
import { RouterContext } from "next/dist/shared/lib/router-context.shared-runtime";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveConn } from "../lib/connection";
import { copy } from "../lib/copy";
import { onTodayRefresh } from "../lib/push";
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

// SP9 9.5: the sheet reads /today for its quick chips (the fixture's check-ins are long past: no front chip).
beforeEach(() => {
  server.use(http.get(`${BASE}/today`, () => HttpResponse.json(todayJson)));
});

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

  it("a finished answer tells the screens to read again, the sheet still open", async () => {
    serveHistory({ conversations: [] });
    serveChat(() => sseResponse(golden("chat_add_task.sse")));
    const changed = vi.fn();
    const off = onTodayRefresh(changed);
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await ready();
    await sendText(user, "치과 예약 추가해 줘");
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    off();
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

  it("an open button moves the app there and closes the sheet", async () => {
    serveHistory();
    const period = { week: "2026-W43" };
    const days = ["월", "화", "수", "목", "금", "토", "일"].map((weekday, i) => ({ date: `2026-10-${19 + i}`, weekday, is_today: i === 5, todos: [] }));
    serveChat(() =>
      sseResponse(
        textAnswer("m-1-1", 1, "이번 주예요.", [
          { type: "tool-input-available", toolCallId: "tc_1", toolName: "ui_period_list", input: period },
          { type: "tool-output-available", toolCallId: "tc_1", output: { ok: true, data: { today: "2026-10-24", start: "2026-10-19", end: "2026-10-25", days, outside: [] } } },
        ]),
      ),
    );
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { router } = renderWithProviders(<ChatSheet open onClose={onClose} conversationId={null} />);
    await sendText(user, "이번 주 보여 줘");
    await user.click(await screen.findByRole("button", { name: copy.parts.openTodos }));
    expect(router.push).toHaveBeenCalledWith("/todos/?tab=week");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a ui_events row opens the schedule tab on that day and closes the sheet (SP9 9.8)", async () => {
    serveHistory();
    const item = { event_id: 4, date: "2026-10-28", start: "2026-10-28T05:00:00Z", end: null, all_day: false, title: "치과", area: null, remind_min: 10, repeat: "none", origin: "user" };
    serveChat(() =>
      sseResponse(
        textAnswer("m-1-1", 1, "수요일 일정이에요.", [
          { type: "tool-input-available", toolCallId: "tc_1", toolName: "ui_events", input: { items: [item] } },
          { type: "tool-output-available", toolCallId: "tc_1", output: { ok: true, data: {} } },
        ]),
      ),
    );
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { router } = renderWithProviders(<ChatSheet open onClose={onClose} conversationId={null} />);
    await sendText(user, "수요일 일정");
    await user.click(await screen.findByRole("button", { name: /치과/ }));
    expect(router.push).toHaveBeenCalledWith("/schedule/?date=2026-10-28");
    expect(onClose).toHaveBeenCalledTimes(1);
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

  it("a change is one line; its undo is on the toast (SP9 9.6)", async () => {
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
    const line = await within(screen.getByRole("log")).findByText("✓ 추가: 치과 → 내일"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(line.closest("[data-activity]")).not.toBeNull();
    expect(within(screen.getByRole("log")).queryByRole("button", { name: copy.chat.undo })).toBeNull();
    const toast = screen.getAllByRole("status").find((s) => s.textContent?.includes("✓ 추가: 치과 → 내일"))!; // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    const undo = within(toast).getByRole("button", { name: copy.chat.undo });
    fireEvent.click(undo);
    fireEvent.click(undo);
    expect(await screen.findByText("↩︎ 되돌렸어요: 치과")).toBeInTheDocument(); // toast
    expect(undos).toHaveLength(1);
    expect(undos[0]).toMatchObject({ id: "1" });
    expect(screen.queryByRole("button", { name: copy.chat.undo })).toBeNull();
  });

  it("toast undo that is blocked or fails says so", async () => {
    serveHistory();
    serveChat(() => sseResponse(golden("chat_add_task.sse")));
    server.use(http.post(`${BASE}/activity/:id/undo`, () => HttpResponse.json({ error: { code: "superseded", message: "x" } }, { status: 409 })));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await sendText(user, "내일 치과 추가해 줘");
    await user.click(await screen.findByRole("button", { name: copy.chat.undo }));
    expect(await screen.findByText(copy.activity.undoBlocked.superseded)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.chat.undo })).toBeNull();
  });

  it("confirmation shows once: one line while streaming, plain text after reopening", async () => {
    // Ruling with the BE thread: /messages keeps the confirmation line in the secretary text, and
    // localParts never keeps data-activity, so a reopened sheet shows it once, as text.
    const seen = serveHistory();
    serveChat(() => sseResponse(golden("chat_add_task.sse")));
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await sendText(user, "내일 치과 추가해 줘");
    const box = await within(screen.getByRole("log")).findByText("✓ 추가: 치과 → 내일"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(box.closest("[data-activity]")).not.toBeNull();
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    history(1, [
      { id: "u-1-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "내일 치과 추가해 줘" },
      { id: "<id>", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "내일 치과를 추가할게요.\n✓ 추가: 치과 → 내일" }, // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    ]);
    rerender(<ChatSheet open onClose={() => {}} />);
    await waitFor(() => expect(document.querySelector("[data-activity]")).toBeNull());
    expect(within(screen.getByRole("log")).getAllByText(/✓ 추가: 치과 → 내일/)).toHaveLength(1); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
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
    // The screen's read and the sheet's own (its quick chips, SP9 9.5) are both in before counting.
    await waitFor(() => expect(hits.today).toBeGreaterThanOrEqual(2));
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
      http.get(`${OTHER_API}/today`, () => HttpResponse.json(todayJson)), // the quick chips (SP9 9.5)
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

// DESIGN.md 입력창: a textarea that grows from one row to two (the rows attribute, never style=),
// Enter sends (not while a Korean syllable is being composed, not with Shift), and the outline is
// the strong one only while sending is possible.
describe("ChatSheet composer", () => {
  it("is a textarea of one row that grows to two", async () => {
    history(5, []);
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await ready();
    expect(input.tagName).toBe("TEXTAREA");
    expect(input).toHaveAttribute("rows", "1");
    await user.type(input, "첫 줄{Shift>}{Enter}{/Shift}둘째 줄");
    expect(input).toHaveValue("첫 줄\n둘째 줄");
    expect(input).toHaveAttribute("rows", "2");
    await user.type(input, "{Shift>}{Enter}{/Shift}셋째 줄");
    expect(input).toHaveAttribute("rows", "2");
    await user.clear(input);
    expect(input).toHaveAttribute("rows", "1");
    expect(input).not.toHaveAttribute("style");
  });

  it("Enter sends; Shift+Enter and Enter while composing do not", async () => {
    history(5, []);
    const bodies = serveChat(() => sseResponse(textAnswer("m-1", 5, "네")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await ready();
    await user.type(input, "안녕");
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(bodies).toHaveLength(0);
    await user.keyboard("{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(await screen.findByText("네")).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("marks the field ready only while sending is possible", async () => {
    history(5, []);
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await ready();
    expect(input).not.toHaveAttribute("data-ready");
    await user.type(input, "   ");
    expect(input).not.toHaveAttribute("data-ready");
    await user.type(input, "할 일");
    expect(input).toHaveAttribute("data-ready");
    expect(screen.getByRole("button", { name: copy.chat.send })).toBeEnabled();
  });
});

// SP9 9.5: the list button in the head opens the conversation list inside the sheet. A conversation
// opened from it is read with /messages, and while it is shown every message carries
// resume_conversation_id (7.3). "새 대화" (the list's button or the head icon) closes it on the BE
// and starts an empty chat. Closing the sheet forgets the pick.
describe("ChatSheet conversation list (SP9 9.5)", () => {
  const LIST = [
    { id: 5, kind: "chat", channel: "app", run_id: null, opened_at: "2026-10-24T01:00:00Z", last_message_at: "2026-10-24T01:01:00Z", closed_at: null, title: "지금 대화", summary: null },
    { id: 3, kind: "chat", channel: "app", run_id: null, opened_at: "2026-10-20T01:00:00Z", last_message_at: "2026-10-20T01:05:00Z", closed_at: "2026-10-20T01:35:00Z", title: "책 고르기", summary: "사피엔스로 정했어요." },
  ];

  /** The latest conversation (limit=3, the sheet's first read), the list (any other limit), /messages, /conversations/new and DELETE. */
  function serveConversations() {
    const seen = { newPosts: 0, deleted: [] as number[] };
    serveHistory({
      messages: {
        5: [{ id: "m-5-1", at: "2026-10-24T01:01:00Z", speaker: "secretary", text: "지금 대화의 말" }],
        3: [
          { id: "u-3-1", at: "2026-10-20T01:00:00Z", speaker: "user", text: "읽을 책 골라 줘" },
          { id: "m-3-1", at: "2026-10-20T01:05:00Z", speaker: "secretary", text: "사피엔스 어때요" },
        ],
      },
    });
    server.use(
      http.get(`${BASE}/conversations`, () => HttpResponse.json({ items: LIST, next_before: null })),
      http.post(`${BASE}/conversations/new`, () => {
        seen.newPosts += 1;
        return HttpResponse.json({ closed: [5] });
      }),
      http.delete(`${BASE}/conversations/:id`, ({ params }) => {
        seen.deleted.push(Number(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    return seen;
  }

  async function openFromList(user: ReturnType<typeof userEvent.setup>, title: string) {
    await user.click(screen.getByRole("button", { name: copy.chat.pastConversations }));
    await user.click((await screen.findByText(title)).closest("button") as HTMLElement);
  }

  it("a conversation opened from the list is read, and every message then carries resume_conversation_id", async () => {
    serveConversations();
    const bodies = serveChat(
      () => sseResponse(textAnswer("m-3-2", 3, "이어서 말해요")),
      () => sseResponse(textAnswer("m-3-3", 3, "또 이어서요")),
    );
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("지금 대화의 말")).toBeInTheDocument();
    await openFromList(user, "책 고르기");
    expect(await screen.findByText("사피엔스 어때요")).toBeInTheDocument();
    expect(screen.queryByText("지금 대화의 말")).toBeNull();
    await sendText(user, "그 책 몇 쪽이야?");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ conversation_id: 3, resume_conversation_id: 3 });
    expect(await screen.findByText("이어서 말해요")).toBeInTheDocument();
    await sendText(user, "고마워");
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ resume_conversation_id: 3 });
  });

  it("새 대화 in the head closes the conversation on the BE and starts an empty one: no resume after it", async () => {
    const seen = serveConversations();
    const bodies = serveChat(() => sseResponse(textAnswer("m-9-1", 9, "새로 시작해요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await openFromList(user, "책 고르기");
    await screen.findByText("사피엔스 어때요");
    await user.click(screen.getByRole("button", { name: copy.chat.newConversation }));
    await waitFor(() => expect(seen.newPosts).toBe(1));
    await waitFor(() => expect(screen.queryByText("사피엔스 어때요")).toBeNull());
    await sendText(user, "안녕");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].conversation_id).toBeNull();
    expect(bodies[0]).not.toHaveProperty("resume_conversation_id");
  });

  it("새 대화 at the top of the list does the same and goes back to the chat", async () => {
    const seen = serveConversations();
    const bodies = serveChat(() => sseResponse(textAnswer("m-9-1", 9, "새로 시작해요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await user.click(screen.getByRole("button", { name: copy.chat.pastConversations }));
    await screen.findByText("책 고르기");
    await user.click(screen.getByRole("button", { name: copy.chat.newConversation }));
    await waitFor(() => expect(seen.newPosts).toBe(1));
    expect(await screen.findByRole("textbox", { name: copy.chat.inputLabel })).toBeInTheDocument();
    expect(screen.queryByText("지금 대화의 말")).toBeNull();
    await sendText(user, "안녕");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ conversation_id: null });
    expect(bodies[0]).not.toHaveProperty("resume_conversation_id");
  });

  it("closing the sheet forgets the pick", async () => {
    serveConversations();
    const bodies = serveChat(() => sseResponse(textAnswer("m-5-2", 5, "네")));
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await openFromList(user, "책 고르기");
    await screen.findByText("사피엔스 어때요");
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    rerender(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("지금 대화의 말")).toBeInTheDocument();
    await sendText(user, "다시 왔어요");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ conversation_id: 5 });
    expect(bodies[0]).not.toHaveProperty("resume_conversation_id");
  });

  // Review round 1, SHOULD 1: 새 대화 then a close and a reopen without sending stays an empty new chat.
  it("새 대화, close, reopen without sending: still an empty chat, and the next message opens a new conversation", async () => {
    const seen = serveConversations();
    const bodies = serveChat(() => sseResponse(textAnswer("m-9-1", 9, "새로 시작해요")));
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await user.click(screen.getByRole("button", { name: copy.chat.newConversation }));
    await waitFor(() => expect(seen.newPosts).toBe(1));
    await waitFor(() => expect(screen.queryByText("지금 대화의 말")).toBeNull());
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    rerender(<ChatSheet open onClose={() => {}} />);
    await ready();
    expect(screen.queryByText("지금 대화의 말")).toBeNull();
    await sendText(user, "안녕");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].conversation_id).toBeNull();
    expect(await screen.findByText("새로 시작해요")).toBeInTheDocument();
    // Once something was said, a reopen shows the latest conversation again.
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    rerender(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("지금 대화의 말")).toBeInTheDocument();
  });

  it("a conversation said after 새 대화 (another device) still shows on reopen", async () => {
    serveConversations();
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await user.click(screen.getByRole("button", { name: copy.chat.newConversation }));
    await waitFor(() => expect(screen.queryByText("지금 대화의 말")).toBeNull());
    const later = new Date(Date.now() + 60_000).toISOString();
    server.use(
      http.get(`${BASE}/conversations`, () =>
        HttpResponse.json({ items: [{ id: 5, kind: "chat", channel: "app", run_id: null, opened_at: later, last_message_at: later, closed_at: null }] }),
      ),
    );
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    rerender(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("지금 대화의 말")).toBeInTheDocument();
  });

  // Review round 1, SHOULD 2: back from the list, the conversation is at its end again.
  it("‹ 비서 from the list scrolls the conversation to the bottom", async () => {
    serveConversations();
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(900);
    const set: number[] = [];
    vi.spyOn(Element.prototype, "scrollTop", "set").mockImplementation(function (this: Element, v: number) {
      if (this.getAttribute("role") === "log") set.push(v);
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await user.click(screen.getByRole("button", { name: copy.chat.pastConversations }));
    await screen.findByText("책 고르기");
    set.length = 0;
    await user.click(screen.getByRole("button", { name: copy.chat.backToChat }));
    await screen.findByText("지금 대화의 말");
    expect(set).toContain(900);
  });

  // Review round 1, NIT: the pressed button goes away, focus lands somewhere sensible in the sheet.
  it("focus stays in the sheet: the list button after opening a row, the input after 새 대화", async () => {
    serveConversations();
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await openFromList(user, "책 고르기");
    await screen.findByText("사피엔스 어때요");
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.pastConversations })).toHaveFocus());
    await user.click(screen.getByRole("button", { name: copy.chat.pastConversations }));
    await screen.findByText("책 고르기");
    await user.click(screen.getByRole("button", { name: copy.chat.newConversation }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toHaveFocus());
  });

  // Review round 1, NIT: going back to a conversation already on screen (after a check-in chip) is not "새 대화".
  it("no second 새 대화 divider when the talk returns to the picked conversation", async () => {
    server.use(
      http.get(`${BASE}/today`, () =>
        HttpResponse.json({ ...todayJson, checkins: [{ ...todayJson.checkins[1], sent_at: new Date(Date.now() - 60_000).toISOString(), reply_until: new Date(Date.now() + 3_600_000).toISOString() }] }),
      ),
    );
    serveConversations();
    serveChat(
      () => sseResponse(textAnswer("m-8-1", 8, "오늘 어땠어요?")),
      () => sseResponse(textAnswer("m-3-2", 3, "책 얘기 이어가요")),
    );
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await openFromList(user, "책 고르기");
    await screen.findByText("사피엔스 어때요");
    const chip = await screen.findByRole("button", { name: "체크인 하기" });
    await waitFor(() => expect(chip).toBeEnabled());
    await user.click(chip);
    await screen.findByText("오늘 어땠어요?");
    await sendText(user, "책 얘기 계속");
    await screen.findByText("책 얘기 이어가요");
    const log = screen.getByRole("log");
    expect(within(log).getAllByText(copy.chat.newConversation)).toHaveLength(1);
  });

  it("deleting the conversation on screen empties the chat", async () => {
    const seen = serveConversations();
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await screen.findByText("지금 대화의 말");
    await user.click(screen.getByRole("button", { name: copy.chat.pastConversations }));
    await screen.findByText("책 고르기");
    await user.click(screen.getByRole("button", { name: copy.today.moreActions("지금 대화") }));
    await user.click(screen.getByRole("button", { name: copy.chat.delete }));
    const ask = await screen.findByText(copy.chat.deleteAsk);
    await user.click(within(ask.closest("[role=dialog]") as HTMLElement).getByRole("button", { name: copy.chat.delete }));
    await waitFor(() => expect(seen.deleted).toEqual([5]));
    await user.click(screen.getByRole("button", { name: copy.chat.backToChat }));
    await ready();
    expect(screen.queryByText("지금 대화의 말")).toBeNull();
  });
});

// SP9 9.5: the quick chip row above the input. A press sends the chip's sentence as my message;
// the check-in chip goes to its run (checkin_id) and never with resume_conversation_id.
describe("ChatSheet quick chips (SP9 9.5)", () => {
  const openRun = {
    ...todayJson.checkins[1],
    sent_at: new Date(Date.now() - 60_000).toISOString(),
    reply_until: new Date(Date.now() + 3_600_000).toISOString(),
  };
  const serveToday = (checkins: unknown[] = []) => server.use(http.get(`${BASE}/today`, () => HttpResponse.json({ ...todayJson, checkins })));

  it("the fixed four above the input; 오늘 정리해줘 sends its sentence as my bubble, with chip today", async () => {
    history(5, []);
    serveToday();
    const bodies = serveChat(() => sseResponse(textAnswer("m-5-1", 5, "오늘은 두 가지예요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await ready();
    const row = screen.getByRole("group", { name: copy.chat.chipsLabel });
    expect(within(row).getAllByRole("button").map((b) => b.textContent)).toEqual(["할 일 추가", "일정 추가", "메모하기", "오늘 정리해줘"]);
    // The row sits right above the input.
    expect(row.compareDocumentPosition(screen.getByRole("textbox", { name: copy.chat.inputLabel })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(within(row).getByRole("button", { name: "오늘 정리해줘" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ chip: "today", checkin_id: null });
    expect((bodies[0].message as { parts: { text: string }[] }).parts[0].text).toBe("오늘 정리해줘");
    const mine = within(screen.getByRole("log")).getByText("오늘 정리해줘");
    expect(mine.closest("[data-message]")).toBeInTheDocument();
    expect(await screen.findByText("오늘은 두 가지예요")).toBeInTheDocument();
    // Only the add chips get a label above the bubble.
    expect((mine.closest("[data-message]") as HTMLElement).querySelectorAll("p")).toHaveLength(1);
  });

  it("test_checkin_chip_sends_checkin_id_not_resume: the check-in chip goes to its run even while a picked conversation is shown", async () => {
    serveToday([openRun]);
    serveHistory({ messages: { 3: [{ id: "m-3-1", at: "2026-10-20T01:05:00Z", speaker: "secretary", text: "사피엔스 어때요" }] } });
    server.use(
      http.get(`${BASE}/conversations`, () =>
        HttpResponse.json({ items: [{ id: 3, kind: "chat", channel: "app", run_id: null, opened_at: "2026-10-20T01:00:00Z", last_message_at: "2026-10-20T01:05:00Z", closed_at: "2026-10-20T01:35:00Z", title: "책 고르기", summary: null }], next_before: null }),
      ),
    );
    const bodies = serveChat(
      () => sseResponse(textAnswer("m-8-1", 8, "오늘 어땠어요?")),
      () => sseResponse(textAnswer("m-3-2", 3, "네")),
    );
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await ready();
    await user.click(screen.getByRole("button", { name: copy.chat.pastConversations }));
    await user.click((await screen.findByText("책 고르기")).closest("button") as HTMLElement);
    await screen.findByText("사피엔스 어때요");
    const chip = await screen.findByRole("button", { name: "체크인 하기" });
    await waitFor(() => expect(chip).toBeEnabled());
    await user.click(chip);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ checkin_id: 341 });
    expect(bodies[0]).not.toHaveProperty("resume_conversation_id");
    expect(bodies[0]).not.toHaveProperty("chip");
    expect((bodies[0].message as { parts: { text: string }[] }).parts[0].text).toBe("체크인 할게요");
    await screen.findByText("오늘 어땠어요?");
    // The next plain message goes back to the picked conversation.
    await sendText(user, "책 얘기 계속");
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ checkin_id: null, resume_conversation_id: 3 });
  });

  it("read-only: the chips are dimmed offline and while an answer is coming", async () => {
    history(5, []);
    serveToday();
    const gate = gatedResponse(textAnswer("m-5-1", 5, "네"), [1]);
    serveChat(gate.response);
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await ready();
    const chips = () => within(screen.getByRole("group", { name: copy.chat.chipsLabel })).getAllByRole("button");
    expect(chips().every((b) => !(b as HTMLButtonElement).disabled)).toBe(true);
    await user.click(chips()[3]);
    await waitFor(() => expect(chips().every((b) => (b as HTMLButtonElement).disabled)).toBe(true));
    gate.release();
    await screen.findByText("네");
    await waitFor(() => expect(chips().every((b) => !(b as HTMLButtonElement).disabled)).toBe(true));
  });

  it("offline: every chip is disabled", async () => {
    history(5, [{ id: "m-5-1", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "지난 말" }]);
    renderWithProviders(<ChatSheet open onClose={() => {}} />, { conn: "offline" });
    const row = await screen.findByRole("group", { name: copy.chat.chipsLabel });
    expect(within(row).getAllByRole("button").every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  });

  it("the check-in screen's reply box has no chip row", async () => {
    serveHistory({ messages: { 8: [{ id: "m-8-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "체크인 대화예요" }] } });
    renderWithProviders(<ChatSheet open embedded onClose={() => {}} conversationId={8} checkinId={341} />);
    await screen.findByText("체크인 대화예요");
    expect(screen.queryByRole("group", { name: copy.chat.chipsLabel })).toBeNull();
  });
});

// SP9c 3: the add chips (할 일 추가, 일정 추가, 메모하기) open a one-line write in the input instead of sending.
describe("ChatSheet one-line write (SP9c)", () => {
  const row = () => screen.queryByRole("group", { name: copy.chat.chipsLabel });
  const closeWrite = () => screen.queryByRole("button", { name: copy.chat.closeWrite });
  async function openWrite(user: ReturnType<typeof userEvent.setup>, label: string) {
    const input = await ready();
    await user.click(within(row() as HTMLElement).getByRole("button", { name: label }));
    return input;
  }

  it("일정 추가: no message goes; the indicator, the example and the focus; the sent line carries chip event and a label", async () => {
    history(5, []);
    const bodies = serveChat(() => sseResponse(textAnswer("m-5-1", 5, "일정에 넣었어요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await openWrite(user, "일정 추가");
    expect(bodies).toHaveLength(0);
    expect(row()).toBeNull();
    expect(closeWrite()).toBeInTheDocument();
    expect(screen.getByText("일정 추가")).toBeInTheDocument();
    expect(input).toHaveAttribute("placeholder", "예: 내일 오후 3시 치과");
    expect(input).toHaveFocus();
    await user.type(input, "내일 오후 3시 치과");
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ chip: "event", checkin_id: null });
    expect((bodies[0].message as { parts: { text: string }[] }).parts[0].text).toBe("내일 오후 3시 치과");
    // My bubble is the text as typed, with a small label above it.
    const bubble = within(screen.getByRole("log")).getByText("내일 오후 3시 치과");
    const mine = bubble.closest("[data-message]") as HTMLElement;
    expect(within(mine).getByText("일정 추가")).toBeInTheDocument();
    expect(within(mine).getByText("일정 추가").compareDocumentPosition(bubble) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The row comes back, the input loses the example.
    expect(row()).toBeInTheDocument();
    expect(closeWrite()).toBeNull();
    expect(input).not.toHaveAttribute("placeholder");
    expect(await screen.findByText("일정에 넣었어요")).toBeInTheDocument();
  });

  it("each add chip has its own example, and the memo label is 메모", async () => {
    history(5, []);
    const bodies = serveChat(() => sseResponse(textAnswer("m-5-1", 5, "남겼어요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await openWrite(user, "할 일 추가");
    expect(input).toHaveAttribute("placeholder", "예: 금요일까지 보고서 초안");
    await user.click(closeWrite() as HTMLElement);
    await openWrite(user, "메모하기");
    expect(input).toHaveAttribute("placeholder", "떠오른 걸 그대로 적어요");
    // A memo can be several lines (Shift+Enter); the first is its title.
    await user.type(input, "책 제목{Shift>}{Enter}{/Shift}사피엔스");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ chip: "memo" });
    const mine = within(screen.getByRole("log")).getByText(/사피엔스/).closest("[data-message]") as HTMLElement;
    expect(within(mine).getByText("메모")).toBeInTheDocument();
  });

  it("the close button goes back to the row and keeps the text; Backspace in an empty input closes too", async () => {
    history(5, []);
    const bodies = serveChat(() => sseResponse(textAnswer("m-5-1", 5, "네")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await openWrite(user, "할 일 추가");
    await user.type(input, "보고서");
    await user.click(closeWrite() as HTMLElement);
    expect(row()).toBeInTheDocument();
    expect(input).toHaveValue("보고서");
    expect(input).not.toHaveAttribute("placeholder");
    await openWrite(user, "할 일 추가");
    // Backspace with text only deletes; in the empty input it ends the write.
    await user.type(input, "{Backspace}{Backspace}{Backspace}");
    expect(input).toHaveValue("");
    expect(closeWrite()).toBeInTheDocument();
    await user.type(input, "{Backspace}");
    expect(closeWrite()).toBeNull();
    expect(row()).toBeInTheDocument();
    // A message after the write ended is a plain one.
    await sendText(user, "안녕");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).not.toHaveProperty("chip");
  });

  it("새 대화, the list and closing the sheet each end the write", async () => {
    history(5, []);
    server.use(
      http.post(`${BASE}/conversations/new`, () => HttpResponse.json({ closed: [5] })),
      http.get(`${BASE}/conversations`, () => HttpResponse.json({ items: [], next_before: null })),
    );
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await openWrite(user, "일정 추가");
    await user.click(screen.getByRole("button", { name: copy.chat.newConversation }));
    await waitFor(() => expect(closeWrite()).toBeNull());
    expect(row()).toBeInTheDocument();
    await openWrite(user, "일정 추가");
    await user.click(screen.getByRole("button", { name: copy.chat.pastConversations }));
    await user.click(screen.getByRole("button", { name: copy.chat.backToChat }));
    await ready();
    expect(closeWrite()).toBeNull();
    await openWrite(user, "일정 추가");
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    rerender(<ChatSheet open onClose={() => {}} />);
    await ready();
    expect(closeWrite()).toBeNull();
    expect(row()).toBeInTheDocument();
  });

  // Spec 4.1: a BE from before the chips refuses `chip` (400 invalid_request); the line goes again
  // without it, under the same client_msg_id, and is answered as a plain message.
  it("an old BE: the chip line goes once more without chip and is answered", async () => {
    history(5, []);
    const bodies = serveChat(
      () => HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 }),
      () => sseResponse(textAnswer("m-5-1", 5, "추가했어요")),
    );
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await openWrite(user, "할 일 추가");
    await user.type(input, "금요일까지 보고서 초안{Enter}");
    expect(await screen.findByText("추가했어요")).toBeInTheDocument();
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toMatchObject({ chip: "todo" });
    expect(bodies[1]).not.toHaveProperty("chip");
    expect(bodies[1].client_msg_id).toBe(bodies[0].client_msg_id);
    expect(screen.queryByText(copy.chat.notReceived)).toBeNull();
  });

  it("a plain message refused with 400 is not sent again", async () => {
    history(5, []);
    const bodies = serveChat(() => HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 }));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await sendText(user, "안녕");
    expect(await screen.findByText(copy.chat.notReceived)).toBeInTheDocument();
    expect(bodies).toHaveLength(1);
  });

  it("a reopened conversation (the BE's lines) has no label", async () => {
    const items: HistoryItem[] = [];
    history(5, items);
    serveChat(() => sseResponse(textAnswer("m-5-1", 5, "일정에 넣었어요")));
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />);
    const input = await openWrite(user, "일정 추가");
    await user.type(input, "내일 오후 3시 치과{Enter}");
    await screen.findByText("일정에 넣었어요");
    expect(within(screen.getByRole("log")).getByText("일정 추가")).toBeInTheDocument();
    items.push(
      { id: "u-5-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "내일 오후 3시 치과" },
      { id: "m-5-1", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "일정에 넣었어요" },
    );
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    rerender(<ChatSheet open onClose={() => {}} />);
    await ready();
    await waitFor(() => expect(within(screen.getByRole("log")).getByText("내일 오후 3시 치과").closest("[data-message]")).toHaveAttribute("data-message", "u-5-1"));
    expect(within(screen.getByRole("log")).queryByText("일정 추가")).toBeNull();
  });
});

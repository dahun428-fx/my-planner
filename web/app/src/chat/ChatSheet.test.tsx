import "fake-indexeddb/auto";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { Today } from "../screens/Today";
import { gatedResponse, golden, type HistoryItem, serveChat, serveHistory, sse, sseResponse } from "../test/chat";
import todayJson from "../test/fixtures/today.json";
import { healthAnswers } from "../test/handlers";
import { mockRouter, renderWithProviders, TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { ChatSheet } from "./ChatSheet";
import { saveParts } from "./localParts";
import type { ViewPart } from "./parts";

afterEach(async () => {
  vi.unstubAllGlobals();
  await clear();
});

const draftTodo = { id: 7, title: "장보기", status: "draft", areas: [], planned_for: "2026-10-25", scheduled_at: null, parent_id: null, note: "", priority: null, completed_at: null };
const draftPart: ViewPart = { kind: "ui", toolCallId: "h_1", name: "ui_todo_draft", props: { task_ids: [7] }, data: { todos: [draftTodo] as never } };

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
    await saveParts("m-5-1", [draftPart]);
    const seen = history(5, [
      { id: "u-5-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "이번 주 정리해 줘" },
      { id: "m-5-1", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "골라 봤어요" },
      { id: "l-5-2", at: "2026-10-24T01:01:00Z", speaker: "secretary", text: "다른 줄이에요" },
    ]);
    const bodies = serveChat(() => sseResponse(golden("chat_replay.sse")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />, { catalog: true });
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

  it("restores text only from a BE without message ids (before R4d)", async () => {
    await saveParts("m-5-1", [draftPart]);
    history(5, [
      { at: "2026-10-24T01:00:00Z", speaker: "user", text: "이번 주 정리해 줘" },
      { at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "골라 봤어요" },
    ]);
    renderWithProviders(<ChatSheet open onClose={() => {}} />, { catalog: true });
    expect(await screen.findByText("골라 봤어요")).toBeInTheDocument();
    await ready();
    expect(screen.queryByText("장보기")).toBeNull();
  });

  it("opens given conversation id", async () => {
    const seen = serveHistory({ messages: { 8: [{ id: "m-8-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "체크인 대화예요" }] } });
    const bodies = serveChat(() => sseResponse(textAnswer("m-8-2", 8, "네")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={8} checkinId={341} />, { catalog: true });
    expect(await screen.findByText("체크인 대화예요")).toBeInTheDocument();
    expect(seen.conversations).toBe(0);
    await sendText(user, "3점이요");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ conversation_id: 8, checkin_id: 341 });
  });

  it("opens an empty conversation for null", async () => {
    const seen = serveHistory({ conversations: [{ id: 5, last_message_at: "2026-10-24T01:00:00Z" }] });
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { catalog: true });
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
    renderWithProviders(<ChatSheet open onClose={() => {}} />, { catalog: true });
    expect(await screen.findByText("셋")).toBeInTheDocument();
    const at = (iso: string) => formatKst(iso, "HH:mm");
    expect(screen.getByText(at("2026-10-24T01:00:00Z"))).toBeInTheDocument(); // the conversation starts
    expect(screen.queryByText(at("2026-10-24T01:09:00Z"))).toBeNull(); // 9 minutes later
    expect(screen.getByText(at("2026-10-24T01:20:00Z"))).toBeInTheDocument(); // 11 minutes later
  });

  it("drag down closes", async () => {
    serveHistory();
    const onClose = vi.fn();
    renderWithProviders(<ChatSheet open onClose={onClose} conversationId={null} />, { catalog: true });
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
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { catalog: true });
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
    renderWithProviders(<ChatSheet open onClose={() => {}} />, { catalog: true });
    expect(await screen.findByText(copy.chat.elsewhere("넷"))).toBeInTheDocument();
    expect(screen.getByText(copy.chat.elsewhere("셋"))).toBeInTheDocument();
    expect(screen.getByText(copy.chat.elsewhere("둘"))).toBeInTheDocument();
    expect(screen.queryByText(copy.chat.elsewhere("하나"))).toBeNull();
    expect(screen.queryByText(copy.chat.elsewhere("앱에서 한 일"))).toBeNull();
    expect(screen.queryByText(copy.chat.elsewhere("앞선 일"))).toBeNull();
    expect(seen.activitySince).toEqual(["2026-10-24T01:00:00Z"]);
  });

  it("new conversation divider when id changes", async () => {
    history(5, [{ id: "m-5-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "좋아요" }]);
    const bodies = serveChat(() => sseResponse(textAnswer("m-6-1", 6, "새로 시작해요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />, { catalog: true });
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
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { catalog: true });
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
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { catalog: true });
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
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { catalog: true });
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
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />, { catalog: true });
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
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { catalog: true });
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
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { catalog: true });
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
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} />, { catalog: true });
    await sendText(user, "내일 치과 추가해 줘");
    const box = await screen.findByText("✓ 추가: 치과 → 내일");
    expect(box.closest("[data-activity]")).not.toBeNull();
    rerender(<ChatSheet open={false} onClose={() => {}} />);
    history(1, [
      { id: "u-1-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "내일 치과 추가해 줘" },
      { id: "<id>", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "내일 치과를 추가할게요.\n✓ 추가: 치과 → 내일" },
    ]);
    rerender(<ChatSheet open onClose={() => {}} />);
    await waitFor(() => expect(document.querySelector("[data-activity]")).toBeNull());
    expect(screen.getAllByText(/✓ 추가: 치과 → 내일/)).toHaveLength(1);
    expect(seen.conversations).toBe(1);
  });
});

describe("ChatSheet in the app", () => {
  function mountApp() {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const hits = { today: 0 };
    server.use(
      http.get(`${BASE}/today`, () => {
        hits.today += 1;
        return HttpResponse.json(todayJson);
      }),
    );
    serveHistory();
    const router = mockRouter("/");
    render(
      <RouterContext.Provider value={router}>
        <App {...({ Component: Today, pageProps: {}, router } as unknown as AppProps)} />
      </RouterContext.Provider>,
    );
    return hits;
  }

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
});

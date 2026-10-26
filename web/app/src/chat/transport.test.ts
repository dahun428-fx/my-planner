import type { UIMessage } from "ai";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { globalConfig } from "zod/v4/core";
import { BASE, server } from "../test/server";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { buildChatBody, makeTransport } from "./transport";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const user = (id: string, text: string): UIMessage => ({ id, role: "user", parts: [{ type: "text", text }] });
const assistant = (id: string, text: string): UIMessage => ({ id, role: "assistant", parts: [{ type: "text", text }] });

describe("buildChatBody", () => {
  it("sends only last user message", () => {
    const last = user(crypto.randomUUID(), "내일 치과 추가해 줘");
    const body = buildChatBody([user(crypto.randomUUID(), "안녕"), assistant("m-1-1", "네"), last], { conversationId: 4, checkinId: null });
    expect(Object.keys(body).sort()).toEqual(["checkin_id", "client_msg_id", "conversation_id", "message"]);
    expect(body.message).toEqual(last);
    expect(body.message.id).toBe(last.id);
    expect(body.conversation_id).toBe(4);
  });

  it("client_msg_id equals message id and is uuid v4", () => {
    const id = crypto.randomUUID();
    const body = buildChatBody([user(id, "안녕")], { conversationId: null, checkinId: null });
    expect(body.client_msg_id).toBe(id);
    expect(body.client_msg_id).toMatch(UUID_V4);
  });

  it("includes checkin id", () => {
    const body = buildChatBody([user(crypto.randomUUID(), "3점이요")], { conversationId: null, checkinId: 341 });
    expect(body.checkin_id).toBe(341);
    expect(body.conversation_id).toBeNull();
  });

  // SP9 9.5 / 7.3: while a conversation picked from the list is on screen, every message carries it.
  it("carries resume_conversation_id on every message while a picked conversation is shown", () => {
    const ctx = { conversationId: 4, checkinId: null, resumeConversationId: 4 };
    const first = user(crypto.randomUUID(), "이어서 할게요");
    const second = user(crypto.randomUUID(), "그리고 하나 더");
    expect(buildChatBody([first], ctx).resume_conversation_id).toBe(4);
    expect(buildChatBody([first, assistant("m-4-1", "네"), second], { ...ctx, conversationId: 9 }).resume_conversation_id).toBe(4);
  });

  it("no resume_conversation_id after 새 대화 (nothing picked)", () => {
    const body = buildChatBody([user(crypto.randomUUID(), "안녕")], { conversationId: null, checkinId: null, resumeConversationId: null });
    expect(Object.keys(body)).not.toContain("resume_conversation_id");
  });

  // Review Focus 5: a message sent from the check-in chip goes to that run (checkin_id) and never
  // carries the picked conversation, so the two never come together from the app.
  it("test_checkin_chip_sends_checkin_id_not_resume", () => {
    const chipMsg: UIMessage = { ...user(crypto.randomUUID(), "체크인 할게요"), metadata: { at: "2026-10-27T13:00:00Z", checkin_id: 341 } };
    const body = buildChatBody([chipMsg], { conversationId: 4, checkinId: null, resumeConversationId: 4 });
    expect(body.checkin_id).toBe(341);
    expect(Object.keys(body)).not.toContain("resume_conversation_id");
    // The next plain message goes back to the picked conversation.
    const next = buildChatBody([chipMsg, assistant("m-1-1", "네"), user(crypto.randomUUID(), "고마워")], { conversationId: 4, checkinId: null, resumeConversationId: 4 });
    expect(next).toMatchObject({ checkin_id: null, resume_conversation_id: 4 });
  });

  it("the check-in screen's box (a checkin id for the whole sheet) never carries resume either", () => {
    const body = buildChatBody([user(crypto.randomUUID(), "3점이요")], { conversationId: 8, checkinId: 341, resumeConversationId: 4 });
    expect(body.checkin_id).toBe(341);
    expect(Object.keys(body)).not.toContain("resume_conversation_id");
  });

  // SP9c 4.1: a chip message carries `chip` (from its metadata); any other message has no such key.
  it("carries the message's chip, and no chip key otherwise", () => {
    const chipMsg: UIMessage = { ...user(crypto.randomUUID(), "내일 오후 3시 치과"), metadata: { at: "2026-10-27T13:00:00Z", chip: "event" } };
    expect(buildChatBody([chipMsg], { conversationId: 4, checkinId: null })).toMatchObject({ chip: "event", checkin_id: null });
    const next = buildChatBody([chipMsg, assistant("m-1-1", "네"), user(crypto.randomUUID(), "고마워")], { conversationId: 4, checkinId: null });
    expect(Object.keys(next)).not.toContain("chip");
  });

  it("picks the last user message even when a reply follows it (regenerate)", () => {
    const last = user(crypto.randomUUID(), "다시");
    const body = buildChatBody([last, assistant("m-1-2", "")], { conversationId: 1, checkinId: null });
    expect(body.client_msg_id).toBe(last.id);
  });
});

describe("makeTransport", () => {
  it("turns zod's compiled checks off before the SDK parses anything (CSP, no eval probe)", () => {
    expect(globalConfig.jitless).toBe(true);
  });

  it("posts the body to the BE chat path with the token", async () => {
    const seen: { auth: string | null; body: unknown }[] = [];
    server.use(
      http.post(`${BASE}/chat`, async ({ request }) => {
        seen.push({ auth: request.headers.get("authorization"), body: await request.json() });
        return new HttpResponse('data: {"type":"start"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n', {
          headers: { "content-type": "text/event-stream" },
        });
      }),
    );
    const t = makeTransport(() => ({ beUrl: TEST_BE_URL, token: TEST_TOKEN }), () => ({ conversationId: 2, checkinId: null }));
    const msg = user(crypto.randomUUID(), "안녕");
    const stream = await t.sendMessages({
      chatId: "c",
      messages: [msg],
      abortSignal: undefined,
      trigger: "submit-message",
      messageId: undefined,
    });
    const reader = stream.getReader();
    const types: string[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      types.push(value.type);
    }
    expect(types).toEqual(["start", "finish"]);
    expect(seen).toEqual([{ auth: `Bearer ${TEST_TOKEN}`, body: { client_msg_id: msg.id, conversation_id: 2, checkin_id: null, message: msg } }]);
  });

  // SP9c 4.1: a BE from before the chips refuses the unknown `chip` key (400 invalid_request). The chip
  // message then goes once more, the same client_msg_id, without it: a plain message there.
  describe("a BE that does not know chip", () => {
    const ok = () => new HttpResponse('data: {"type":"start"}\n\ndata: {"type":"finish"}\n\ndata: [DONE]\n\n', { headers: { "content-type": "text/event-stream" } });
    const refuse = (code: string) => HttpResponse.json({ error: { code, message: "x" } }, { status: 400 });
    function serve(answer: (body: Record<string, unknown>) => Response) {
      const seen: Record<string, unknown>[] = [];
      server.use(
        http.post(`${BASE}/chat`, async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          seen.push(body);
          return answer(body);
        }),
      );
      return seen;
    }
    const send = (msg: UIMessage) =>
      makeTransport(() => ({ beUrl: TEST_BE_URL, token: TEST_TOKEN }), () => ({ conversationId: null, checkinId: null })).sendMessages({
        chatId: "c",
        messages: [msg],
        abortSignal: undefined,
        trigger: "submit-message",
        messageId: undefined,
      });
    const chipMsg = (): UIMessage => ({ ...user(crypto.randomUUID(), "내일 오후 3시 치과"), metadata: { chip: "event" } });

    it("a chip message refused with 400 invalid_request goes once more without chip, same client_msg_id", async () => {
      const seen = serve((body) => ("chip" in body ? refuse("invalid_request") : ok()));
      const msg = chipMsg();
      const stream = await send(msg);
      const reader = stream.getReader();
      while (!(await reader.read()).done);
      expect(seen).toHaveLength(2);
      expect(seen[0]).toMatchObject({ client_msg_id: msg.id, chip: "event" });
      expect(seen[1]).toMatchObject({ client_msg_id: msg.id });
      expect(seen[1]).not.toHaveProperty("chip");
    });

    it("only once: a second 400 is the answer", async () => {
      const seen = serve(() => refuse("invalid_request"));
      await expect(send(chipMsg())).rejects.toThrow();
      expect(seen).toHaveLength(2);
    });

    it("a message without chip is never sent again on a 400", async () => {
      const seen = serve(() => refuse("invalid_request"));
      await expect(send(user(crypto.randomUUID(), "안녕"))).rejects.toThrow();
      expect(seen).toHaveLength(1);
    });

    it("another 400 code on a chip message is not sent again", async () => {
      const seen = serve(() => refuse("validation_failed"));
      await expect(send(chipMsg())).rejects.toThrow();
      expect(seen).toHaveLength(1);
    });
  });

  it("errors a stream that ends before finish", async () => {
    server.use(
      http.post(`${BASE}/chat`, () =>
        new HttpResponse('data: {"type":"start"}\n\n', { headers: { "content-type": "text/event-stream" } }),
      ),
    );
    const t = makeTransport(() => ({ beUrl: TEST_BE_URL, token: TEST_TOKEN }), () => ({ conversationId: null, checkinId: null }));
    const stream = await t.sendMessages({
      chatId: "c",
      messages: [user(crypto.randomUUID(), "안녕")],
      abortSignal: undefined,
      trigger: "submit-message",
      messageId: undefined,
    });
    const reader = stream.getReader();
    await reader.read();
    await expect(reader.read()).rejects.toMatchObject({ name: "StreamCutError" });
  });
});

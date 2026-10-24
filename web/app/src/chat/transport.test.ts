import type { UIMessage } from "ai";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
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

  it("picks the last user message even when a reply follows it (regenerate)", () => {
    const last = user(crypto.randomUUID(), "다시");
    const body = buildChatBody([last, assistant("m-1-2", "")], { conversationId: 1, checkinId: null });
    expect(body.client_msg_id).toBe(last.id);
  });
});

describe("makeTransport", () => {
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

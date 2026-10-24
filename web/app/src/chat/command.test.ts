import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { saveConn } from "../lib/connection";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { sendCommand } from "./command";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function sse(chunks: string[], cut = false) {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      chunks.forEach((x) => c.enqueue(enc.encode(`data: ${x}\n\n`)));
      if (cut) c.error(new TypeError("network"));
      else c.close();
    },
  });
}

const REPLY = ['{"type":"start"}', '{"type":"text-start","id":"t"}', '{"type":"text-delta","id":"t","delta":"fake reply"}', '{"type":"text-end","id":"t"}', '{"type":"finish"}', "[DONE]"];

describe("sendCommand", () => {
  it("pause sends command with new id and drains stream", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const bodies: Record<string, unknown>[] = [];
    let auth: string | null = null;
    let drained = false;
    server.use(
      http.post(`${BASE}/chat`, async ({ request }) => {
        auth = request.headers.get("authorization");
        bodies.push((await request.json()) as Record<string, unknown>);
        const body = sse(REPLY).pipeThrough(
          new TransformStream({
            flush() {
              drained = true;
            },
          }),
        );
        return new HttpResponse(body, { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    await expect(sendCommand("/pause 3")).resolves.toEqual({ ok: true });
    await expect(sendCommand("/pause 3")).resolves.toEqual({ ok: true });
    expect(drained).toBe(true);
    expect(auth).toBe(`Bearer ${TEST_TOKEN}`);
    expect(bodies).toHaveLength(2);
    const [a, b] = bodies;
    expect(a.client_msg_id).toMatch(UUID);
    expect(b.client_msg_id).toMatch(UUID);
    expect(a.client_msg_id).not.toBe(b.client_msg_id);
    expect(a).toEqual({
      client_msg_id: a.client_msg_id,
      conversation_id: null,
      checkin_id: null,
      message: { id: a.client_msg_id, role: "user", parts: [{ type: "text", text: "/pause 3" }] },
    });
  });

  it("not ok when the BE refuses or cannot be reached", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    server.use(http.post(`${BASE}/chat`, () => HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 })));
    await expect(sendCommand("/unpause")).resolves.toEqual({ ok: false });
    server.use(http.post(`${BASE}/chat`, () => HttpResponse.error()));
    await expect(sendCommand("/unpause")).resolves.toEqual({ ok: false });
  });

  it("not ok when the stream is cut", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    server.use(http.post(`${BASE}/chat`, () => new HttpResponse(sse(REPLY.slice(0, 2), true), { headers: { "Content-Type": "text/event-stream" } })));
    await expect(sendCommand("/unpause")).resolves.toEqual({ ok: false });
  });

  it("not ok without a connection", async () => {
    await expect(sendCommand("/unpause")).resolves.toEqual({ ok: false });
  });
});

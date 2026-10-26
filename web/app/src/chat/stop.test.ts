import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { saveConn } from "../lib/connection";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { stopOnBe } from "./stop";

function serveStop(...states: string[]) {
  const seen: { body: unknown; auth: string | null }[] = [];
  server.use(
    http.post(`${BASE}/chat/stop`, async ({ request }) => {
      seen.push({ body: await request.json(), auth: request.headers.get("Authorization") });
      return HttpResponse.json({ state: states[Math.min(seen.length - 1, states.length - 1)] });
    }),
  );
  return seen;
}

describe("stopOnBe", () => {
  it("sends the client_msg_id with the token and returns the state", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const seen = serveStop("stopped");
    expect(await stopOnBe("cm-1", async () => {})).toBe("stopped");
    expect(seen).toEqual([{ body: { client_msg_id: "cm-1" }, auth: `Bearer ${TEST_TOKEN}` }]);
  });

  it("unknown (the message may not have reached the BE yet) is asked once more", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    const seen = serveStop("unknown", "stopped");
    const pauses: number[] = [];
    expect(await stopOnBe("cm-2", async (ms) => void pauses.push(ms))).toBe("stopped");
    expect(seen).toHaveLength(2);
    expect(pauses).toHaveLength(1);
    const again = serveStop("unknown");
    expect(await stopOnBe("cm-3", async () => {})).toBe("unknown");
    expect(again).toHaveLength(2);
  });

  it("a 404 (a BE before the route) or no network is null, never thrown", async () => {
    saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
    server.use(http.post(`${BASE}/chat/stop`, () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 })));
    expect(await stopOnBe("cm-4", async () => {})).toBeNull();
    server.use(http.post(`${BASE}/chat/stop`, () => HttpResponse.error()));
    expect(await stopOnBe("cm-5", async () => {})).toBeNull();
  });
});

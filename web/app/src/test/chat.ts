import { readFileSync } from "node:fs";
import { join } from "node:path";
import { http, HttpResponse } from "msw";
import { BASE, server } from "./server";

// The BE's golden SSE answers (BE ticket 06), read from the repo, never copied into the app (spec F4).
const GOLDEN_DIR = join(__dirname, "../../../../tests/fixtures/app_golden");

export const golden = (name: string): string => readFileSync(join(GOLDEN_DIR, name), "utf8");
export const goldenHeaders = (): Record<string, string> => JSON.parse(golden("headers.json")) as Record<string, string>;

/** The SSE events of a body (`data: …` blocks), without the blank lines. */
export const events = (body: string): string[] => body.split("\n\n").filter((e) => e.trim() !== "");
export const sse = (chunks: (object | "[DONE]")[]): string =>
  chunks.map((c) => `data: ${c === "[DONE]" ? c : JSON.stringify(c)}\n\n`).join("");

export function sseResponse(body: string, headers: Record<string, string> = goldenHeaders()): Response {
  return new HttpResponse(body, { status: 200, headers });
}

/**
 * A response that stops after the events up to each gate until `release()` is called; with
 * `cut: true` the body breaks (a network error) where the last gate would release.
 */
export function gatedResponse(body: string, gateAfter: number[], opts: { cut?: boolean } = {}) {
  const evs = events(body).map((e) => `${e}\n\n`);
  const enc = new TextEncoder();
  const waiters: (() => void)[] = [];
  let released = 0;
  const release = () => {
    released += 1;
    waiters.splice(0).forEach((w) => w());
  };
  const until = (n: number) =>
    new Promise<void>((resolve) => {
      const check = () => (released >= n ? resolve() : void waiters.push(check));
      check();
    });
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let at = 0;
      for (let g = 0; g < gateAfter.length; g++) {
        for (; at < gateAfter[g]; at++) controller.enqueue(enc.encode(evs[at]));
        await until(g + 1);
      }
      if (opts.cut) {
        controller.error(new TypeError("network connection was lost"));
        return;
      }
      for (; at < evs.length; at++) controller.enqueue(enc.encode(evs[at]));
      controller.close();
    },
  });
  return { response: () => new HttpResponse(stream, { status: 200, headers: goldenHeaders() }), release };
}

/** Answers POST /chat with the next answer in line (the last one repeats) and keeps every body. */
export function serveChat(...answers: (() => Response | Promise<Response>)[]) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/chat`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      const answer = answers[Math.min(bodies.length - 1, answers.length - 1)];
      return answer();
    }),
  );
  return bodies;
}

export type HistoryItem = { id?: string; at: string; speaker: "user" | "secretary"; text: string; photos?: { id: number; width: number; height: number }[] };

/** GET /conversations (newest first) and GET /conversations/{id}/messages, and GET /activity. */
export function serveHistory(opts: {
  conversations?: { id: number; last_message_at: string }[];
  messages?: Record<number, HistoryItem[]>;
  activity?: { id: number; at: string; channel: "app" | "telegram" | "scheduler"; summary: string }[];
} = {}) {
  const seen = { conversations: 0, messages: [] as number[], activitySince: [] as string[], activityOrder: [] as string[] };
  server.use(
    http.get(`${BASE}/conversations`, ({ request }) => {
      seen.conversations += 1;
      const q = new URL(request.url).searchParams;
      if (q.get("channel") !== "app" || q.get("limit") !== "3") return HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 });
      return HttpResponse.json({
        items: (opts.conversations ?? []).map((c) => ({
          id: c.id,
          kind: "chat",
          channel: "app",
          run_id: null,
          opened_at: c.last_message_at,
          last_message_at: c.last_message_at,
          closed_at: null,
        })),
      });
    }),
    http.get(`${BASE}/conversations/:id/messages`, ({ params }) => {
      const id = Number(params.id);
      seen.messages.push(id);
      const items = opts.messages?.[id];
      if (!items) return HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 });
      return HttpResponse.json({ items: items.map((m) => ({ ...m, tools: [], channel: "app" })) });
    }),
    http.get(`${BASE}/activity`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      const since = q.get("since") ?? "";
      seen.activitySince.push(since);
      seen.activityOrder.push(q.get("order") ?? "asc");
      const items = (opts.activity ?? [])
        .filter((a) => a.at > since)
        .sort((a, b) => (q.get("order") === "desc" ? (a.at < b.at ? 1 : -1) : a.at < b.at ? -1 : 1))
        .map((a) => ({ ...a, actor: "user", kind: "complete_task", risk: "low", undo_id: null, undone_at: null }));
      return HttpResponse.json({ items, next_before: null, next_since: null });
    }),
  );
  return seen;
}

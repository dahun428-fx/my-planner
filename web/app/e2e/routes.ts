import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, Route } from "@playwright/test";

// The fixture BE for the Playwright runs (A10): the same tailnet name the unit tests use, served
// with page.route. It is https and inside the build's connect-src (https://*.example.ts.net), so
// the app has no test-only branch.
export const APP_ORIGIN = "http://127.0.0.1:4173";
export const BE_URL = "https://gp76.example.ts.net";
export const TOKEN = "test-token-not-real";

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(here, "../src/test/fixtures");
const GOLDEN = join(here, "../../../tests/fixtures/app_golden");

const fixture = (name: string): unknown => JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), "utf8"));
export const golden = (name: string): string => readFileSync(join(GOLDEN, name), "utf8");

const CORS = {
  "Access-Control-Allow-Origin": APP_ORIGIN,
  "Access-Control-Allow-Headers": "authorization, content-type",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
  "Access-Control-Expose-Headers": "x-conversation-id, x-vercel-ai-ui-message-stream",
};

/** A 200-character todo title: rows must wrap, never scroll sideways (spec 9장). */
export const LONG_TITLE = "아주 긴 할 일 제목 ".repeat(20).slice(0, 200);

type Todo = Record<string, unknown>;
type TodayEntry = { group: string; todo: Todo };

function today(): Record<string, unknown> {
  const t = fixture("today-cards") as { todos: TodayEntry[] };
  const long = { ...t.todos[2].todo, id: 99, title: LONG_TITLE };
  return { ...t, todos: [...t.todos.slice(0, 3), { group: "open", todo: long }, ...t.todos.slice(3)] };
}

function week(): Record<string, unknown> {
  const w = fixture("week") as { days: { is_today: boolean; todos: Todo[] }[] };
  const long = { ...(today().todos as TodayEntry[])[3].todo };
  return { ...w, days: w.days.map((d) => (d.is_today ? { ...d, todos: [...d.todos, long] } : d)) };
}

export type MockOptions = {
  /** Golden SSE bodies for POST /chat, in turn (the last repeats). */
  chat?: string[];
};

/** Answers every BE call from the fixtures; returns the POST /chat bodies it saw. */
export async function mockBe(page: Page, opts: MockOptions = {}) {
  const chat = opts.chat ?? ["chat_propose_tasks.sse"];
  const sseHeaders = JSON.parse(golden("headers.json")) as Record<string, string>;
  const chatBodies: unknown[] = [];

  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });

  await page.route(`${BE_URL}/api/v1/**`, async (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const q = url.searchParams;
    const get = req.method() === "GET";

    if (get && path === "/health") return json(route, fixture("health"));
    if (get && path === "/ui/catalog") return json(route, fixture("catalog"));
    if (get && path === "/today") return json(route, today());
    if (get && path === "/week") return json(route, week());
    if (get && path === "/drafts") return json(route, fixture("drafts"));
    if (get && path === "/priorities") return json(route, fixture(`priorities-${q.get("cadence") ?? "month"}`));
    if (get && path === "/checkins") return json(route, fixture("checkins-today"));
    if (get && path === "/checkins/341") return json(route, fixture("checkin-341"));
    if (get && path === "/checkins/340") return json(route, fixture("checkin-340-brief"));
    if (get && path === "/activity") {
      if (q.has("since")) return json(route, { items: [], next_before: null, next_since: null });
      return json(route, fixture(q.has("before") ? "activity-desc-2" : "activity-desc-1"));
    }
    if (get && path === "/conversations") return json(route, { items: [] });
    if (get && path === "/settings/notify") return json(route, fixture("notify"));
    if (get && path === "/push/vapid-public-key") return json(route, { public_key: "BFixtureKeyNotReal" });
    if (req.method() === "POST" && path === "/chat") {
      chatBodies.push(req.postDataJSON());
      const name = chat[Math.min(chatBodies.length - 1, chat.length - 1)];
      return route.fulfill({ status: 200, headers: { ...CORS, ...sseHeaders }, body: golden(name) });
    }
    return json(route, { error: { code: "not_found", message: `no fixture for ${req.method()} ${path}` } }, 404);
  });
  return { chatBodies };
}

/** The BE stops answering (network error), as when the laptop sleeps (spec 5.5.4). */
export async function beUnreachable(page: Page) {
  await page.unroute(`${BE_URL}/api/v1/**`);
  await page.route(`${BE_URL}/api/v1/**`, (route) => route.abort("internetdisconnected"));
}

/** A saved connection on the device, before any page script runs. */
export async function seedConn(page: Page) {
  await page.addInitScript(
    ([url, token]) => {
      localStorage.setItem("mp.beUrl", url);
      localStorage.setItem("mp.token", token);
    },
    [BE_URL, TOKEN] as const,
  );
}

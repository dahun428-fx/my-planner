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

/** `GET /moments` (SP8 6.5): the status fixture's moments, and with `include_hidden` the one it counts as hidden. */
function momentsList(includeHidden: boolean): Record<string, unknown> {
  const { moments } = fixture("status") as { moments: Record<string, unknown>[] };
  const hidden = { id: 50, date: "2026-10-22", text: "조용히 숨긴 순간이에요", area: "learning", sources: ["task"], hidden: true };
  return { from: "2026-10-12", to: "2026-10-25", items: includeHidden ? [...moments, hidden] : moments };
}

/** A 200-character todo title: rows must wrap, never scroll sideways (spec 9장). */
export const LONG_TITLE = "아주 긴 할 일 제목 ".repeat(20).slice(0, 200);

type Todo = Record<string, unknown>;
type TodayEntry = { group: string; todo: Todo };

function today(): Record<string, unknown> {
  const t = fixture("today-cards") as { todos: TodayEntry[] };
  const long = { ...t.todos[2].todo, id: 99, title: LONG_TITLE };
  return { ...t, todos: [...t.todos.slice(0, 3), { group: "open", todo: long }, ...t.todos.slice(3)], habits: HABITS };
}

/** SP7 6.1: a daily, a weekly under its target and one that met it (the three meta lines). */
const HABITS = [
  { id: 1, title: "물 마시기", area: "health", kind: "daily", target_per_week: null, status: "active", checked: true, week_count: 4 },
  { id: 2, title: "운동", area: "health", kind: "weekly", target_per_week: 3, status: "active", checked: false, week_count: 2 },
  { id: 3, title: "독서", area: "learning", kind: "weekly", target_per_week: 2, status: "active", checked: true, week_count: 2 },
];

/** SP7 6.2: the habits screen reads every status at once; one paused, one archived. */
const ALL_HABITS = [
  ...HABITS,
  { id: 4, title: "아주 긴 습관 제목도 줄을 넘겨 접혀야 해요 아주 긴 습관 제목", area: "career", kind: "weekly", target_per_week: 5, status: "active", checked: false, week_count: 1 },
  { id: 5, title: "명상", area: "quality_of_life", kind: "daily", target_per_week: null, status: "paused", checked: false, week_count: 0 },
  { id: 6, title: "피아노", area: "learning", kind: "weekly", target_per_week: 2, status: "archived", checked: false, week_count: 0 },
];

/** GET /habits/{id}?weeks=4 for 10/24: checked days only, weeks with checks only (5.5). */
function habitHistory(id: number): Record<string, unknown> | null {
  const habit = ALL_HABITS.find((h) => h.id === id);
  if (!habit) return null;
  return {
    habit,
    from: "2026-09-28",
    to: "2026-10-24",
    checked_dates: ["2026-09-29", "2026-10-01", "2026-10-06", "2026-10-13", "2026-10-15", "2026-10-21", "2026-10-22"],
    weeks: [
      { week: "2026-W40", count: 2 },
      { week: "2026-W41", count: 1 },
      { week: "2026-W42", count: 2 },
      { week: "2026-W43", count: 2 },
    ],
  };
}

/** The evening check-in with its habit card (SP7 6.3: after the confirm card). */
function checkin341(): Record<string, unknown> {
  const c = fixture("checkin-341") as { cards: unknown[] };
  const habit = { toolCallId: "h_habit_1", component: "ui_habit_check", props: { date: "2026-10-24" }, data: { habits: HABITS } };
  return { ...c, cards: [...c.cards, habit] };
}

function week(): Record<string, unknown> {
  const w = fixture("week") as { days: { is_today: boolean; todos: Todo[] }[] };
  const long = { ...(today().todos as TodayEntry[])[3].todo };
  return { ...w, days: w.days.map((d) => (d.is_today ? { ...d, todos: [...d.todos, long] } : d)) };
}

/** SP12 11.3: the workout screen's plan, the same one the mate's `ui_block` card in workout-mate.spec shows. */
export const WORKOUT_PLAN_TITLE = "주 2번 집 운동";
const WORKOUT = {
  plan: {
    id: 4,
    title: WORKOUT_PLAN_TITLE,
    note: null,
    created_at: "2026-10-24T01:00:00Z",
    sessions: [
      {
        id: 1,
        position: 1,
        label: "하체",
        weekdays: [0, 3],
        items: [
          { name: "고블릿 스쿼트", sets: 3, reps: "8-10", weight_kg: 16, minutes: null, note: "무릎 안 아픈 깊이까지" },
          { name: "런지", sets: 3, reps: "10", weight_kg: null, minutes: null, note: null },
        ],
      },
      { id: 2, position: 2, label: "상체", weekdays: [1, 4], items: [{ name: "푸시업", sets: 3, reps: "최대", weight_kg: null, minutes: null, note: null }] },
    ],
  },
  logs: [
    {
      id: 11,
      date: "2026-10-23",
      title: "하체",
      effort: 3,
      note: null,
      session_id: 1,
      items: [{ name: "스쿼트", sets: 5, reps: 5, weight_kg: 60, minutes: null, distance_km: null }],
    },
  ],
  notes: [
    { id: 21, kind: "equipment", text: "집에 덤벨 20kg까지", updated_at: "2026-10-23T01:00:00Z" },
    { id: 22, kind: "injury", text: "왼쪽 무릎이 가끔 아파요", updated_at: "2026-10-23T01:00:00Z" },
  ],
};

/** The mate's answer: a plan card (`ui_block`) and a line of text, as the BE streams it (spec 6장). */
export function matePlanSse(): string {
  const ev = (o: unknown) => `data: ${JSON.stringify(o)}\n\n`;
  const input = {
    title: WORKOUT_PLAN_TITLE,
    children: [
      { type: "bullets", items: ["하체 · 월·목 · 운동 2개", "상체 · 화·금 · 운동 1개"] },
      { type: "text", md: "무릎이 아프면 깊이는 편한 만큼만 해요." },
    ],
  };
  return [
    ev({ type: "start", messageId: "m-mate", messageMetadata: { conversation_id: 1, channel: "app", kind: "chat", checkin_id: null } }),
    ev({ type: "start-step" }),
    ev({ type: "tool-input-available", toolCallId: "tc_mate_1", toolName: "ui_block", input }),
    ev({ type: "tool-output-available", toolCallId: "tc_mate_1", output: { ok: true, data: { today: "2026-10-24", todos: [] } } }),
    ev({ type: "text-start", id: "t1" }),
    ev({ type: "text-delta", id: "t1", delta: "이렇게 짜 봤어요." }),
    ev({ type: "text-end", id: "t1" }),
    ev({ type: "finish-step" }),
    ev({ type: "finish", messageMetadata: { conversation_id: 1, channel: "app", kind: "chat" } }),
    "data: [DONE]\n\n",
  ].join("");
}

export type MockOptions = {
  /** The BE has the workout mate: /health lists the `mate` feature (SP12 11.3). */
  mate?: boolean;
  /** SSE bodies for POST /chat, in turn (the last repeats): a golden's file name, or `{ body }`. */
  chat?: (string | { body: string })[];
  /** POST /chat gets no answer at all (an answer that is slow to come): for the stop button. */
  chatHangs?: boolean;
  /** SP13 10장: /status as an app device gets it, with `standing` and `innate` (default: the dashboard shape). */
  standing?: boolean;
};

/** An answer in Markdown, streamed in small pieces: emphasis, a list, a table, a code block, a link. */
export const MARKDOWN_ANSWER = [
  "## 이번 주 정리\n",
  "**치과**는 *내일* 가요. ~~헬스장~~은 다음 주로.\n\n",
  "- [x] 장보기\n- [ ] 보고서 초안\n\n",
  "1. 오전: `메일 정리`\n2. 오후: 회의\n\n",
  "> 쉬는 시간도 챙겨요.\n\n",
  "| 요일 | 할 일 | 메모 |\n|:-:|:--|--:|\n| 월 | 보고서 초안 쓰기 | 오전 집중 시간에 끝내기 |\n| 화 | 치과 | 오후 3시, 늦지 않게 출발 |\n\n",
  "```\nconst week = [\"월\", \"화\", \"수\", \"목\", \"금\"].map((d) => d + \"요일\");\n```\n\n",
  "자세한 건 [달력](https://example.com/calendar)에서 봐요. <img src=x onerror=alert(1)>",
].join("");

export function markdownSse(text = MARKDOWN_ANSWER): string {
  const ev = (o: unknown) => `data: ${JSON.stringify(o)}\n\n`;
  const pieces = text.match(/[\s\S]{1,12}/g) ?? [];
  return [
    ev({ type: "start", messageId: "m-md", messageMetadata: { conversation_id: 1, channel: "app", kind: "chat", checkin_id: null } }),
    ev({ type: "start-step" }),
    ev({ type: "text-start", id: "t1" }),
    ...pieces.map((delta) => ev({ type: "text-delta", id: "t1", delta })),
    ev({ type: "text-end", id: "t1" }),
    ev({ type: "finish-step" }),
    ev({ type: "finish", messageMetadata: { conversation_id: 1, channel: "app", kind: "chat" } }),
    "data: [DONE]\n\n",
  ].join("");
}

/** The chat sheet's conversation list (SP9 9.5): today, yesterday, a check-in, an old one with a 200-character title. */
const CONVERSATIONS = [
  { id: 12, kind: "chat", channel: "app", run_id: null, opened_at: "2026-10-24T05:00:00Z", last_message_at: "2026-10-24T05:10:00Z", closed_at: null, title: "치과 예약", summary: "내일 14:00 치과를 일정에 넣었어요. 알림은 30분 전이에요." },
  { id: 11, kind: "run", channel: "app", run_id: 339, opened_at: "2026-10-23T12:00:00Z", last_message_at: "2026-10-23T12:20:00Z", closed_at: "2026-10-23T19:00:00Z", title: "저녁 돌아보기", summary: "컨디션 3, 운동은 내일로 옮겼어요." },
  { id: 7, kind: "chat", channel: "app", run_id: null, opened_at: "2026-10-02T01:00:00Z", last_message_at: "2026-10-02T01:30:00Z", closed_at: "2026-10-02T02:00:00Z", title: LONG_TITLE, summary: LONG_TITLE },
];

/** Answers every BE call from the fixtures; returns the POST /chat bodies it saw. */
export async function mockBe(page: Page, opts: MockOptions = {}) {
  const chat = opts.chat ?? ["chat_propose_tasks.sse"];
  const sseHeaders = JSON.parse(golden("headers.json")) as Record<string, string>;
  const chatBodies: unknown[] = [];
  const stopBodies: unknown[] = [];

  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });

  await page.route(`${BE_URL}/api/v1/**`, async (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const q = url.searchParams;
    const get = req.method() === "GET";

    if (get && path === "/health") return json(route, opts.mate ? { ...(fixture("health") as object), features: ["mate"] } : fixture("health"));
    if (get && path === "/workout") return json(route, WORKOUT);
    if (get && path === "/ui/catalog") return json(route, fixture("catalog"));
    if (get && path === "/today") return json(route, today());
    if (get && path === "/status") return json(route, fixture(opts.standing ? "status-standing" : "status"));
    if (get && path === "/standing") return json(route, fixture("standing")); // SP13 10.3
    if (get && path === "/standing/measures") return json(route, fixture("standing-measures"));
    if (get && path === "/moments") return json(route, momentsList(q.get("include_hidden") === "true"));
    if (get && path === "/week") return json(route, week());
    if (get && path === "/drafts") return json(route, fixture("drafts"));
    if (get && path === "/priorities") return json(route, fixture(`priorities-${q.get("cadence") ?? "month"}`));
    if (get && path === "/checkins") return json(route, fixture("checkins-today"));
    if (get && path === "/checkins/341") return json(route, checkin341());
    if (get && path === "/checkins/340") return json(route, fixture("checkin-340-brief"));
    if (get && path === "/activity") {
      if (q.has("since")) return json(route, { items: [], next_before: null, next_since: null });
      return json(route, fixture(q.has("before") ? "activity-desc-2" : "activity-desc-1"));
    }
    if (get && path === "/habits") return json(route, { date: "2026-10-24", week: "2026-W43", items: ALL_HABITS });
    const habitPath = /^\/habits\/(\d+)$/.exec(path);
    if (get && habitPath) {
      const h = habitHistory(Number(habitPath[1]));
      if (h) return json(route, h);
    }
    // The sheet's first read (limit=3) finds nothing; the list screen (SP9 9.5) finds CONVERSATIONS.
    if (get && path === "/conversations") return json(route, { items: q.get("limit") === "3" ? [] : CONVERSATIONS, next_before: null });
    if (get && path === "/memos") return json(route, { items: [], next_before: null });
    if (get && path === "/events") return json(route, { start: q.get("start"), end: q.get("end"), items: [] }); // SP9 9.2
    if (get && path === "/settings/notify") return json(route, fixture("notify"));
    if (get && path === "/settings/digests") return json(route, fixture("digest-settings")); // SP9b 5장
    if (get && path === "/push/vapid-public-key") return json(route, { public_key: "BFixtureKeyNotReal" });
    if (req.method() === "POST" && path === "/chat/stop") {
      stopBodies.push(req.postDataJSON());
      return json(route, { state: "stopped" });
    }
    if (req.method() === "POST" && path === "/chat") {
      chatBodies.push(req.postDataJSON());
      if (opts.chatHangs) return new Promise<void>(() => {}); // never answered; the page aborts it
      const next = chat[Math.min(chatBodies.length - 1, chat.length - 1)];
      return route.fulfill({ status: 200, headers: { ...CORS, ...sseHeaders }, body: typeof next === "string" ? golden(next) : next.body });
    }
    return json(route, { error: { code: "not_found", message: `no fixture for ${req.method()} ${path}` } }, 404);
  });
  return { chatBodies, stopBodies };
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

import "fake-indexeddb/auto";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Today as TodayData } from "../api/types.gen";
import { copy } from "../lib/copy";
import { registerServiceWorker } from "../lib/push";
import { loadSnap } from "../lib/snapshot";
import { installPush } from "../test/push";
import { formatKst } from "../lib/time";
import health from "../test/fixtures/health.json";
import degraded from "../test/fixtures/health-degraded.json";
import todayJson from "../test/fixtures/today.json";
import emptyJson from "../test/fixtures/today-empty.json";
import { makeHabit } from "../test/parts";
import { renderWithProviders, seedSnap, TEST_BE_URL } from "../test/render";
import { BASE, server } from "../test/server";
import { Today } from "./Today";

const today = todayJson as TodayData;
const empty = emptyJson as TodayData;

afterEach(async () => {
  vi.useRealTimers();
  await clear();
});

function serve(data: TodayData = today) {
  const hits = { today: 0 };
  server.use(
    http.get(`${BASE}/today`, () => {
      hits.today += 1;
      return HttpResponse.json(data);
    }),
  );
  return hits;
}

function actions(answer: (body: Record<string, unknown>) => Response | Promise<Response>) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      bodies.push(body);
      return answer(body);
    }),
  );
  return bodies;
}

const applied = (confirmation = "✓ 처리했어요") => // taste-skill-ignore: BE confirmation prefix (R4b), not UI
  HttpResponse.json({ status: "applied", activity_id: 900, undo_id: 900, result: {}, confirmation });

const habits = [
  makeHabit(1, "물 마시기", { week_count: 4, checked: true }),
  makeHabit(2, "운동", { kind: "weekly", target_per_week: 3, week_count: 2 }),
];
const withHabits: TodayData = { ...today, habits };

const before = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("Today", () => {
  it("reads again when a push arrives while open", async () => {
    const env = installPush();
    try {
      await registerServiceWorker(() => {});
      const hits = serve();
      renderWithProviders(<Today />);
      await screen.findByText(copy.today.checkinLine(copy.loops.evening_checkin));
      const before = hits.today;
      env.emit({ refresh: "today" }); // what sw.js posts to open windows on a push
      await waitFor(() => expect(hits.today).toBe(before + 1));
    } finally {
      env.restore();
    }
  });

  it("renders blocks in order", async () => {
    // The BE sends a done row first; it still goes to the end of the list.
    const [a, b, c, d] = today.todos;
    serve({ ...today, todos: [d, a, b, c] });
    renderWithProviders(<Today />);
    const line = await screen.findByText(copy.today.checkinLine(copy.loops.evening_checkin));
    expect(line.closest("a")).toHaveAttribute("href", "/checkin/?id=341");
    const title = screen.getByRole("heading", { level: 1, name: copy.today.title });
    expect(screen.getByText(/10월 24일 토/)).toBeInTheDocument();
    const brief = screen.getByText(/좋은 아침이에요/);
    const condition = screen.getByRole("heading", { name: copy.today.condition });
    const todos = screen.getByRole("heading", { name: copy.today.todosHeading(3) });
    expect(before(title, line)).toBe(true);
    expect(before(line, brief)).toBe(true);
    expect(before(brief, condition)).toBe(true);
    // The brief block is headed by its loop name and the time it was sent (5.5.1: text, sent_at).
    const briefHeading = screen.getByRole("heading", { name: `${copy.loops.morning_brief} 10:00` });
    expect(before(briefHeading, brief)).toBe(true);
    // The two ends of the condition scale are named (5 is the good end).
    expect(screen.getByText(copy.parts.scoreLow)).toBeInTheDocument();
    expect(screen.getByText(copy.parts.scoreHigh)).toBeInTheDocument();
    expect(before(condition, todos)).toBe(true);
    const rows = [a, b, c, d].map((t) => screen.getByText(t.todo.title));
    rows.forEach((r, i) => {
      expect(before(todos, r)).toBe(true);
      if (i > 0) expect(before(rows[i - 1], r)).toBe(true);
    });
    expect(screen.getByText(copy.today.completedAt(formatKst("2026-10-24T00:40:00Z", "HH:mm")))).toBeInTheDocument();
    expect(screen.getByText(copy.status.connected)).toBeInTheDocument();
  });

  it("hides brief when null", async () => {
    serve({ ...today, brief: null });
    renderWithProviders(<Today />);
    await screen.findByText("운동 30분");
    expect(screen.queryByText(/좋은 아침이에요/)).toBeNull();
  });

  it("brief longer than 3 lines folds with more", async () => {
    const text = ["하나", "둘", "셋", "넷", "다섯"].join("\n");
    serve({ ...today, brief: { ...today.brief!, text } });
    renderWithProviders(<Today />);
    const more = await screen.findByRole("button", { name: copy.today.morePlain });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(more);
    expect(screen.getByRole("button", { name: copy.today.lessPlain })).toHaveAttribute("aria-expanded", "true");
  });

  it("the brief is Markdown", async () => {
    serve({ ...today, brief: { ...today.brief!, text: "좋은 아침이에요. **운동**부터 해요." } });
    renderWithProviders(<Today />);
    expect(await screen.findByText("운동", { selector: "strong" })).toBeInTheDocument();
  });

  it("empty todos copy", async () => {
    serve(empty);
    renderWithProviders(<Today />);
    expect(await screen.findByText(copy.today.noTodos)).toBeInTheDocument();
  });

  it("condition pill records", async () => {
    serve();
    const bodies = actions(() => applied());
    renderWithProviders(<Today />);
    await userEvent.setup().click(await screen.findByRole("button", { name: copy.today.conditionScore(3) }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "record_condition", args: { date: "2026-10-24", score: 3 } });
  });

  it("live data before /health answers takes writes (no read-only flicker); the launcher waits", async () => {
    serve();
    server.use(http.get(`${BASE}/health`, () => new Promise<Response>(() => {})));
    renderWithProviders(<Today />);
    const pill = await screen.findByRole("button", { name: copy.today.conditionScore(3) });
    expect(pill).toBeEnabled();
    expect(screen.queryByText(copy.offline.writeLater)).toBeNull();
    expect(screen.getByRole("checkbox", { name: copy.today.checkLabel("운동 30분") })).toBeEnabled();
    expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeDisabled();
  });

  it("a conflict on the condition says it failed and reads again", async () => {
    const hits = serve();
    actions(() => HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 }));
    renderWithProviders(<Today />);
    const pill = await screen.findByRole("button", { name: copy.today.conditionScore(3) });
    await waitFor(() => expect(pill).toBeEnabled());
    const read = hits.today;
    await userEvent.setup().click(pill);
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    await waitFor(() => expect(hits.today).toBe(read + 1));
  });

  it("writes and the launcher go off together when the BE stops taking writes", async () => {
    serve();
    actions(() => HttpResponse.json({ error: { code: "too_many_auth_failures", message: "x" } }, { status: 429 }));
    renderWithProviders(<Today />);
    const pill = await screen.findByRole("button", { name: copy.today.conditionScore(3) });
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeEnabled());
    expect(pill).toBeEnabled();
    await userEvent.setup().click(pill);
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeDisabled());
    expect(screen.getByRole("button", { name: copy.today.conditionScore(3) })).toBeDisabled();
    expect(screen.queryByRole("checkbox", { name: copy.today.checkLabel("운동 30분") })).toBeNull(); // a read-only row has no check
  });

  it("existing condition is filled and can be changed", async () => {
    serve({ ...today, condition: { date: "2026-10-24", score: 4, note: null } });
    renderWithProviders(<Today />);
    const change = await screen.findByRole("button", { name: copy.today.change });
    expect(screen.getByText(copy.today.conditionScore(4))).toBeInTheDocument();
    await userEvent.setup().click(change);
    expect(screen.getByRole("button", { name: copy.today.conditionScore(2) })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.today.conditionScore(4) })).toHaveAttribute("aria-pressed", "true");
  });

  it("check is optimistic and reverts on error", async () => {
    serve();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const bodies = actions(async () => {
      await gate;
      return HttpResponse.json({ error: { code: "boom", message: "x" } }, { status: 500 });
    });
    renderWithProviders(<Today />);
    const box = await screen.findByRole("checkbox", { name: copy.today.checkLabel("장보기") });
    await userEvent.setup().click(box);
    const checked = screen.getByRole("checkbox", { name: copy.today.doneLabel("장보기") });
    expect(checked).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "complete_task", args: { id: 13 } });
    release();
    expect(await screen.findByRole("checkbox", { name: copy.today.checkLabel("장보기") })).toHaveAttribute("aria-checked", "false");
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
  });

  it("checking a done row reopens it", async () => {
    serve();
    const bodies = actions(() => applied());
    renderWithProviders(<Today />);
    await userEvent.setup().click(await screen.findByRole("checkbox", { name: copy.today.doneLabel("빨래 널기") }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "reopen_task", args: { id: 15 } });
  });

  it("tomorrow uses logical date", async () => {
    serve();
    // 01:30 KST on the 25th: the device calendar says the 25th, the BE's logical day is still the 24th.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-25T01:30:00+09:00"));
    const bodies = actions(() => applied());
    renderWithProviders(<Today />);
    const row = await screen.findByText("운동 30분");
    fireEvent.contextMenu(row);
    fireEvent.click(await screen.findByRole("button", { name: copy.todos.tomorrow }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "move_task", args: { id: 12, planned_for: "2026-10-25" } });
  });

  it("a conflict on tomorrow says it failed", async () => {
    serve();
    actions(() => HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 }));
    renderWithProviders(<Today />);
    fireEvent.contextMenu(await screen.findByText("운동 30분"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
  });

  it("tomorrow on scheduled todo opens confirm sheet", async () => {
    // SP6 8 (BE-2): moving a to-do that has a time asks first; "바꾸기" sends again with the token.
    const SUMMARY = "날짜를 옮겨요: 운동 30분 → 10월 25일 (일)";
    serve();
    const bodies = actions((b) => (b.confirm_token ? applied() : HttpResponse.json({ status: "needs_confirm", confirm_token: "ct-9", summary: SUMMARY, expires_at: "2026-10-24T09:00:00Z" })));
    renderWithProviders(<Today />);
    const user = userEvent.setup();
    fireEvent.contextMenu(await screen.findByText("운동 30분"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText(SUMMARY)).toBeInTheDocument();
    expect(screen.queryByText(copy.actions.failed)).toBeNull();
    await user.click(within(sheet).getByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "move_task", args: { id: 12, planned_for: "2026-10-25" }, confirm_token: "ct-9" });
    expect(bodies[1].client_msg_id).not.toBe(bodies[0].client_msg_id);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    // "그대로 두기" sends nothing more.
    fireEvent.contextMenu(screen.getByText("운동 30분"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    const again = await screen.findByRole("dialog");
    await waitFor(() => expect(within(again).getByText(SUMMARY)).toBeInTheDocument());
    await user.click(within(again).getByRole("button", { name: copy.todos.keep }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(bodies).toHaveLength(3);
  });

  it("drop needs confirm opens sheet", async () => {
    serve();
    const bodies = actions((b) =>
      b.confirm_token
        ? applied()
        : HttpResponse.json({ status: "needs_confirm", confirm_token: "ct-1", summary: "이번 주 우선순위예요. 빼면 순서가 바뀌어요.", expires_at: "2026-10-24T09:00:00Z" }),
    );
    renderWithProviders(<Today />);
    fireEvent.contextMenu(await screen.findByText("운동 30분"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.drop }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText("이번 주 우선순위예요. 빼면 순서가 바뀌어요.")).toBeInTheDocument();
    await userEvent.setup().click(within(sheet).getByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "drop_task", args: { id: 12 }, confirm_token: "ct-1" });
    expect(bodies[1].client_msg_id).not.toBe(bodies[0].client_msg_id);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("drop confirm that expired says so", async () => {
    serve();
    actions((b) =>
      b.confirm_token
        ? HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 })
        : HttpResponse.json({ status: "needs_confirm", confirm_token: "ct-1", summary: "확인해 주세요.", expires_at: "2026-10-24T09:00:00Z" }),
    );
    renderWithProviders(<Today />);
    fireEvent.contextMenu(await screen.findByText("운동 30분"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.drop }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.setup().click(within(sheet).getByRole("button", { name: copy.todos.change }));
    expect(await screen.findByText(copy.todos.confirmExpired)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keep closes the confirm sheet without sending", async () => {
    serve();
    const bodies = actions(() =>
      HttpResponse.json({ status: "needs_confirm", confirm_token: "ct-1", summary: "확인해 주세요.", expires_at: "2026-10-24T09:00:00Z" }),
    );
    renderWithProviders(<Today />);
    fireEvent.contextMenu(await screen.findByText("운동 30분"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.drop }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.setup().click(within(sheet).getByRole("button", { name: copy.todos.keep }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(bodies).toHaveLength(1);
  });

  it("refetches after write", async () => {
    const hits = serve();
    actions(() => applied());
    renderWithProviders(<Today />);
    const box = await screen.findByRole("checkbox", { name: copy.today.checkLabel("장보기") });
    // The first load is followed by one more when the saved connection reaches the polling hook.
    await waitFor(() => expect(hits.today).toBe(2));
    await userEvent.setup().click(box);
    await waitFor(() => expect(hits.today).toBe(3));
  });

  it("keeps the check when the refresh after an applied write fails", async () => {
    let failing = false;
    server.use(
      http.get(`${BASE}/today`, () =>
        failing ? HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) : HttpResponse.json(today),
      ),
    );
    const bodies = actions(() => applied());
    renderWithProviders(<Today />);
    const box = await screen.findByRole("checkbox", { name: copy.today.checkLabel("장보기") });
    failing = true;
    await userEvent.setup().click(box);
    await waitFor(() => expect(bodies).toHaveLength(1));
    await screen.findByText("✓ 처리했어요"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("checkbox", { name: copy.today.doneLabel("장보기") })).toHaveAttribute("aria-checked", "true");
  });

  it("keyboard user opens the row menu and moves a todo to tomorrow", async () => {
    serve();
    const bodies = actions(() => applied());
    renderWithProviders(<Today />);
    const more = await screen.findByRole("button", { name: copy.today.moreActions("운동 30분") });
    expect(screen.queryByRole("button", { name: copy.today.moreActions("빨래 널기") })).toBeNull();
    const user = userEvent.setup();
    more.focus();
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: copy.todos.tomorrow }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "move_task", args: { id: 12, planned_for: "2026-10-25" } });
  });

  it("saves snapshot on success", async () => {
    serve();
    renderWithProviders(<Today />);
    await screen.findByText("운동 30분");
    await waitFor(async () => expect(await loadSnap("today", TEST_BE_URL)).not.toBeNull());
    expect((await loadSnap<TodayData>("today", TEST_BE_URL))?.data.date).toBe("2026-10-24");
  });

  it("degraded line under title", async () => {
    serve();
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json(degraded)));
    renderWithProviders(<Today />);
    expect(await screen.findByText(copy.status.limited("18:30"))).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: copy.today.checkLabel("장보기") })).toBeEnabled();
  });

  it("block error retries only that block", async () => {
    let n = 0;
    let failing = true;
    server.use(
      http.get(`${BASE}/today`, () => {
        n += 1;
        return failing ? HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) : HttpResponse.json(today);
      }),
    );
    let healthHits = 0;
    server.use(
      http.get(`${BASE}/health`, () => {
        healthHits += 1;
        return HttpResponse.json(health);
      }),
    );
    renderWithProviders(<Today />);
    expect(await screen.findByText(copy.errors.block("internal"))).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: copy.today.title })).toBeInTheDocument();
    const healthBefore = healthHits;
    const todayBefore = n;
    failing = false;
    await userEvent.setup().click(screen.getByRole("button", { name: copy.errors.retry }));
    expect(await screen.findByText("운동 30분")).toBeInTheDocument();
    expect(n).toBe(todayBefore + 1);
    expect(healthHits).toBe(healthBefore);
  });
});

async function seed(data: TodayData | null) {
  if (data) await seedSnap("today", data);
  server.use(http.get(`${BASE}/today`, () => HttpResponse.error()));
}

describe("Today habits (SP7 6.1)", () => {
  it("habit_block_between_condition_and_todos", async () => {
    const hits = serve(withHabits);
    const bodies = actions((b) =>
      HttpResponse.json({
        status: "applied",
        activity_id: 920,
        undo_id: 920,
        result: { habit: { ...habits[1], checked: true, week_count: 3 }, date: today.date, already: false },
        confirmation: "✓ 습관: 운동", // taste-skill-ignore: BE confirmation (appendix A), not UI
      }),
    );
    renderWithProviders(<Today />);
    const habitsHeading = await screen.findByRole("heading", { name: "습관" });
    const condition = screen.getByRole("heading", { name: copy.today.condition });
    const todos = screen.getByRole("heading", { name: copy.today.todosHeading(3) });
    expect(before(condition, habitsHeading)).toBe(true);
    expect(before(habitsHeading, todos)).toBe(true);
    expect(screen.getByRole("link", { name: "관리" })).toHaveAttribute("href", "/habits/");
    const water = screen.getByRole("checkbox", { name: copy.parts.checkLabel("물 마시기") });
    expect(before(habitsHeading, water)).toBe(true);
    expect(before(water, todos)).toBe(true);
    expect(water).toBeChecked();
    expect(screen.getByText("이번 주 4번")).toBeInTheDocument();
    expect(screen.getByText("이번 주 2번 · 목표 3번")).toBeInTheDocument();

    await waitFor(() => expect(hits.today).toBe(2));
    await userEvent.click(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동") }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    // The day is /today.date (the BE's logical day), never the device calendar.
    expect(bodies[0]).toMatchObject({ action: "check_habit", args: { id: 2, date: today.date } });
    await waitFor(() => expect(hits.today).toBe(3));
    expect(await screen.findByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
  });

  it("empty_habits_shows_add_row", async () => {
    serve(today); // habits: []
    renderWithProviders(<Today />);
    const add = await screen.findByRole("link", { name: "습관 추가하기" });
    expect(add).toHaveAttribute("href", "/habits/");
    expect(screen.queryByRole("heading", { name: "습관" })).toBeNull();
    expect(screen.queryByRole("link", { name: "관리" })).toBeNull();
    const condition = screen.getByRole("heading", { name: copy.today.condition });
    const todos = screen.getByRole("heading", { name: copy.today.todosHeading(3) });
    expect(before(condition, add)).toBe(true);
    expect(before(add, todos)).toBe(true);
  });

  it("a snapshot saved before habits (no field) still draws, with the add row", async () => {
    const { habits: _gone, ...old } = today;
    await seed(old as TodayData);
    renderWithProviders(<Today />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(screen.getByText("운동 30분")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "습관 추가하기" })).toBeInTheDocument();
  });

  it("offline_snapshot_habits_read_only", async () => {
    await seed(withHabits);
    const bodies = actions(() => applied());
    renderWithProviders(<Today />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "습관" })).toBeInTheDocument();
    const boxes = [copy.parts.checkLabel("물 마시기"), copy.parts.checkLabel("운동")].map((name) => screen.getByRole("checkbox", { name }));
    for (const b of boxes) expect(b).toBeDisabled();
    expect(boxes[0]).toBeChecked();
    await userEvent.click(boxes[1]);
    expect(bodies).toHaveLength(0);
    expect(screen.getByText("이번 주 2번 · 목표 3번")).toBeInTheDocument();
  });
});

describe("Today offline and refused", () => {
  it("offline with snapshot is read-only", async () => {
    await seed(today);
    const saved = (await loadSnap("today", TEST_BE_URL))!.savedAt;
    renderWithProviders(<Today />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(screen.getByText(copy.offline.snapshotAt(formatKst(saved, "HH:mm")))).toBeInTheDocument();
    expect(screen.getByText("운동 30분")).toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: copy.today.moreActions("운동 30분") })).toBeNull();
    for (const n of [1, 2, 3, 4, 5]) expect(screen.getByRole("button", { name: copy.today.conditionScore(n) })).toBeDisabled();
    expect(screen.getAllByText(copy.offline.writeLater).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: copy.offline.chatLater })).toBeDisabled();
    fireEvent.contextMenu(screen.getByText("운동 30분"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offline without snapshot", async () => {
    await seed(null);
    renderWithProviders(<Today />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.noSnapshot)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.offline.chatLater })).toBeDisabled();
  });

  it("catch-up line before brief", async () => {
    await seed({ ...today, brief: null });
    renderWithProviders(<Today />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.catchUp)).toBeInTheDocument();
  });

  it("does not show a snapshot of another BE", async () => {
    await seedSnap("today", today, "https://other.example.ts.net");
    server.use(http.get(`${BASE}/today`, () => HttpResponse.error()));
    renderWithProviders(<Today />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.noSnapshot)).toBeInTheDocument();
    expect(screen.queryByText("운동 30분")).toBeNull();
  });

  it("401 state", async () => {
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 })));
    renderWithProviders(<Today />, { conn: "unauthorized" });
    const text = await screen.findByText(copy.status.unauthorized, { selector: "p" });
    expect(within(text.closest("section") as HTMLElement).getByRole("link", { name: copy.errors.goSettings })).toHaveAttribute("href", "/settings/");
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.chat.launcher })).toHaveAccessibleDescription(copy.chat.launcherBlocked.unauthorized);
  });

  it("503 state", async () => {
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json({ error: { code: "safe_mode", message: "x" } }, { status: 503 })));
    renderWithProviders(<Today />, { conn: "safe_mode" });
    expect(await screen.findByText(copy.status.safeMode, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeDisabled();
    expect(screen.getByText(copy.chat.launcherBlocked.safe_mode)).toBeInTheDocument();
  });

  it("429 state", async () => {
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json({ error: { code: "too_many_auth_failures", message: "x" } }, { status: 429 })));
    renderWithProviders(<Today />);
    expect(await screen.findByText(copy.status.tooMany, { selector: "p" })).toBeInTheDocument();
  });
});

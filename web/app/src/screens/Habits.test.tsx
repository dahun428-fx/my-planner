import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Habit, HabitHistory } from "../api/types.gen";
import { copy } from "../lib/copy";
import { makeHabit, serveActions } from "../test/parts";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { Habits } from "./Habits";

const DATE = "2026-10-24";

const water = makeHabit(1, "물 마시기", { week_count: 4, checked: true });
const run = makeHabit(2, "운동", { kind: "weekly", target_per_week: 3, week_count: 2 });
const read = makeHabit(3, "독서", { status: "paused", area: "learning" });
const piano = makeHabit(4, "피아노", { status: "archived", area: "quality_of_life" });

/** GET /habits; returns the query string of every read. */
function serveList(items: () => Habit[]) {
  const reads: string[] = [];
  server.use(
    http.get(`${BASE}/habits`, ({ request }) => {
      reads.push(new URL(request.url).searchParams.toString());
      return HttpResponse.json({ date: DATE, week: "2026-W43", items: items() });
    }),
  );
  return reads;
}

/** GET /habits/{id}; returns the path and query of every read. */
function serveHistory(checked: () => string[] = () => ["2026-10-22", "2026-10-24", "2026-10-13"]) {
  const reads: string[] = [];
  server.use(
    http.get(`${BASE}/habits/:id`, ({ params, request }) => {
      reads.push(`${String(params.id)}?${new URL(request.url).searchParams.toString()}`);
      const habit = [water, run, read, piano].find((h) => h.id === Number(params.id))!;
      const body: HabitHistory = {
        habit,
        from: "2026-09-28",
        to: DATE,
        checked_dates: checked(),
        weeks: [
          { week: "2026-W43", count: 2 },
          { week: "2026-W42", count: 1 },
        ],
      };
      return HttpResponse.json(body);
    }),
  );
  return reads;
}

describe("Habits", () => {
  it("sections_active_paused_archived_collapsed", async () => {
    const reads = serveList(() => [water, run, read, piano]);
    renderWithProviders(<Habits />, { route: "/habits/" });
    expect(screen.getByRole("heading", { level: 1, name: copy.habits.heading })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "‹ 더보기" })).toHaveAttribute("href", "/more/");
    expect(await screen.findByRole("heading", { name: copy.habits.active })).toBeInTheDocument();
    expect(new Set(reads)).toEqual(new Set(["status=all"]));
    // active rows with their meta
    expect(screen.getByRole("button", { name: /물 마시기/ })).toHaveTextContent(copy.habits.week(4));
    expect(screen.getByRole("button", { name: /운동/ })).toHaveTextContent(copy.habits.weekOfTarget(2, 3));
    // paused: a row with "다시 시작"
    expect(screen.getByRole("heading", { name: copy.habits.paused })).toBeInTheDocument();
    expect(screen.getByText("독서")).toBeInTheDocument();
    // archived: collapsed until opened
    const toggle = screen.getByRole("button", { name: copy.habits.archived });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("피아노")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: copy.habits.resumeLabel("독서") })).toHaveLength(1);
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("피아노")).toBeInTheDocument();
    // the add button is a 44px circle in the title row
    expect(screen.getByRole("button", { name: copy.habits.add })).toBeEnabled();
  });

  it("paused and archived sections only when there are some", async () => {
    serveList(() => [water]);
    renderWithProviders(<Habits />, { route: "/habits/" });
    expect(await screen.findByRole("heading", { name: copy.habits.active })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.habits.paused })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.habits.archived })).not.toBeInTheDocument();
  });

  it("empty_state_copy", async () => {
    serveList(() => []);
    renderWithProviders(<Habits />, { route: "/habits/" });
    expect(await screen.findByText(copy.habits.empty)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.habits.paused })).not.toBeInTheDocument();
  });

  it("resume_from_archived", async () => {
    let items = [water, piano];
    const reads = serveList(() => items);
    const bodies = serveActions(() => {
      items = [water, { ...piano, status: "active" }];
      return HttpResponse.json({ status: "applied", activity_id: 5, undo_id: 5, result: {}, confirmation: "✓ 습관 다시 시작: 피아노" });
    });
    renderWithProviders(<Habits />, { route: "/habits/" });
    await userEvent.click(await screen.findByRole("button", { name: copy.habits.archived }));
    await userEvent.click(screen.getByRole("button", { name: copy.habits.resumeLabel("피아노") }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "set_habit_status", args: { id: 4, status: "active" } });
    await waitFor(() => expect(reads.length).toBeGreaterThanOrEqual(2));
    expect(await screen.findByText("✓ 습관 다시 시작: 피아노")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: copy.habits.archived })).not.toBeInTheDocument());
  });

  it("detail sheet: area, cadence, the grid, week lines and buttons", async () => {
    serveList(() => [water, run]);
    const reads = serveHistory();
    renderWithProviders(<Habits />, { route: "/habits/" });
    await userEvent.click(await screen.findByRole("button", { name: /운동/ }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByRole("heading", { name: "운동" })).toBeInTheDocument();
    expect(within(sheet).getByText(copy.habits.detailMeta(copy.areas.health, copy.habits.weeklyN(3)))).toBeInTheDocument();
    await waitFor(() => expect(sheet.querySelectorAll("[data-date]")).toHaveLength(28));
    expect(reads).toEqual(["2?weeks=4"]);
    expect(sheet.querySelectorAll("[data-dot]")).toHaveLength(3);
    expect(within(sheet).getByText("이번 주 2번")).toBeInTheDocument();
    expect(within(sheet).getByText("지난주 1번")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: copy.habits.edit })).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: copy.habits.pause })).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: copy.habits.archive })).toBeInTheDocument();
  });

  it("a grid cell checks and unchecks that day, then reads again", async () => {
    let checked = ["2026-10-22"];
    serveList(() => [water]);
    const reads = serveHistory(() => checked);
    const bodies = serveActions((b) => {
      const date = (b.args as { date: string }).date;
      checked = b.action === "check_habit" ? [...checked, date] : checked.filter((d) => d !== date);
      return HttpResponse.json({ status: "applied", activity_id: 7, undo_id: 7, result: { habit: water, date, already: false }, confirmation: "✓ 습관: 물 마시기" });
    });
    renderWithProviders(<Habits />, { route: "/habits/" });
    await userEvent.click(await screen.findByRole("button", { name: /물 마시기/ }));
    const sheet = await screen.findByRole("dialog");
    const cell = await within(sheet).findByRole("button", { name: copy.dateParts.monthDay(10, 23) });
    expect(cell).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(cell);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "check_habit", args: { id: 1, date: "2026-10-23" } });
    await waitFor(() => expect(within(sheet).getByRole("button", { name: copy.dateParts.monthDay(10, 23) })).toHaveAttribute("aria-pressed", "true"));
    expect(reads.length).toBeGreaterThanOrEqual(2);
    await userEvent.click(within(sheet).getByRole("button", { name: copy.dateParts.monthDay(10, 22) }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "uncheck_habit", args: { id: 1, date: "2026-10-22" } });
  });

  it("pause applies at once", async () => {
    serveList(() => [run]);
    serveHistory();
    const bodies = serveActions();
    renderWithProviders(<Habits />, { route: "/habits/" });
    await userEvent.click(await screen.findByRole("button", { name: /운동/ }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.click(within(sheet).getByRole("button", { name: copy.habits.pause }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "set_habit_status", args: { id: 2, status: "paused" } });
  });

  it("archive_needs_confirm_sheet", async () => {
    serveList(() => [run]);
    serveHistory();
    const summary = "운동 습관을 그만둘까요? 기록은 남아요.";
    const bodies = serveActions((b) =>
      b.confirm_token
        ? HttpResponse.json({ status: "applied", activity_id: 9, result: {}, confirmation: "✓ 습관 그만두기: 운동" })
        : HttpResponse.json({ status: "needs_confirm", confirm_token: "tok-1", summary, expires_at: "2026-10-24T10:00:00Z" }),
    );
    renderWithProviders(<Habits />, { route: "/habits/" });
    await userEvent.click(await screen.findByRole("button", { name: /운동/ }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.click(within(sheet).getByRole("button", { name: copy.habits.archive }));
    expect(await screen.findByText(summary)).toBeInTheDocument();
    expect(bodies[0]).toMatchObject({ action: "set_habit_status", args: { id: 2, status: "archived" }, confirm_token: null });
    await userEvent.click(screen.getByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "set_habit_status", args: { id: 2, status: "archived" }, confirm_token: "tok-1" });
    expect(bodies[1].client_msg_id).not.toBe(bodies[0].client_msg_id);
    expect(await screen.findByText("✓ 습관 그만두기: 운동")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(summary)).not.toBeInTheDocument());
  });

  it("keeping the habit sends nothing more", async () => {
    serveList(() => [run]);
    serveHistory();
    const summary = "운동 습관을 그만둘까요? 기록은 남아요.";
    const bodies = serveActions(() => HttpResponse.json({ status: "needs_confirm", confirm_token: "tok-1", summary, expires_at: "" }));
    renderWithProviders(<Habits />, { route: "/habits/" });
    await userEvent.click(await screen.findByRole("button", { name: /운동/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.habits.archive }));
    await userEvent.click(await screen.findByRole("button", { name: copy.todos.keep }));
    await waitFor(() => expect(screen.queryByText(summary)).not.toBeInTheDocument());
    expect(bodies).toHaveLength(1);
  });

  it("고치기 opens the edit sheet for that habit", async () => {
    serveList(() => [run]);
    serveHistory();
    renderWithProviders(<Habits />, { route: "/habits/" });
    await userEvent.click(await screen.findByRole("button", { name: /운동/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.habits.edit }));
    expect(await screen.findByRole("heading", { name: copy.habits.editTitle })).toBeInTheDocument();
    expect(screen.getByLabelText(copy.habits.titleLabel)).toHaveValue("운동");
  });

  it("the add button opens the add sheet", async () => {
    serveList(() => []);
    renderWithProviders(<Habits />, { route: "/habits/" });
    await screen.findByText(copy.habits.empty);
    await userEvent.click(screen.getByRole("button", { name: copy.habits.add }));
    expect(await screen.findByRole("heading", { level: 2, name: copy.habits.add })).toBeInTheDocument();
  });

  it("offline: rows stay, nothing can be pressed", async () => {
    serveList(() => [water, read]);
    renderWithProviders(<Habits />, { route: "/habits/", conn: "offline" });
    expect(await screen.findByText("물 마시기")).toBeInTheDocument();
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.habits.add })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.habits.resumeLabel("독서") })).toBeDisabled();
  });
});

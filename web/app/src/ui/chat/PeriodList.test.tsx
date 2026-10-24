import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import type { DayTodos, PartData, PartTodo } from "../types";
import { PeriodList } from "./PeriodList";

// SP6 6.4. Today is 2026-10-24 (Sat): this week is 2026-W43 (10/19~10/25), next week W44 (10/26~11/1).
const TODAY = "2026-10-24";
const todo = (id: number, title: string, over: Partial<PartTodo> = {}): PartTodo => ({ id, title, status: "open", planned_for: TODAY, scheduled_at: null, ...over });
const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
function week(start: string, todos: Record<string, PartTodo[]> = {}, today = TODAY): DayTodos[] {
  const [y, m, d] = start.split("-").map(Number);
  return WEEKDAYS.map((weekday, i) => {
    const date = new Date(Date.UTC(y, m - 1, d + i)).toISOString().slice(0, 10);
    return { date, weekday, is_today: date === today, todos: todos[date] ?? [] };
  });
}
const dayData = (date: string, todos: PartTodo[]): PartData => ({ today: TODAY, start: date, end: date, days: [{ date, weekday: "토", is_today: date === TODAY, todos }], outside: [] });
const title = () => screen.getByRole("heading", { level: 3 }).textContent;
const card = () => within(document.querySelector("section")!);

afterEach(() => {
  vi.useRealTimers();
});

describe("PeriodList", () => {
  it("titles from data.today", () => {
    // The device calendar says late November: the titles still follow data.today.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-30T03:00:00Z"));
    const cases: [object, string][] = [
      [{ day: "2026-10-24" }, "오늘"],
      [{ day: "2026-10-25" }, "내일"],
      [{ day: "2026-10-23" }, "어제"],
      [{ day: "2026-10-27" }, "10월 27일 (화)"],
      [{ week: "2026-W43" }, "이번 주"],
      [{ week: "2026-W44" }, "다음 주"],
      [{ week: "2026-W42" }, "지난주"],
      [{ week: "2026-W46" }, "11월 9일 ~ 11월 15일"],
    ];
    for (const [props, want] of cases) {
      const { unmount } = renderWithProviders(<PeriodList props={props} data={{ today: TODAY, days: [], outside: [] }} ctx={makeCtx()} />);
      expect(title()).toBe(want);
      unmount();
    }
  });

  it("week groups and empty days", () => {
    const days = week("2026-10-19", { "2026-10-24": [todo(1, "운동")], "2026-10-21": [todo(2, "장보기", { planned_for: "2026-10-21" })] });
    renderWithProviders(<PeriodList props={{ week: "2026-W43" }} data={{ today: TODAY, start: "2026-10-19", end: "2026-10-25", days, outside: [] }} ctx={makeCtx()} />);
    expect(screen.getByText("21일 수")).toBeInTheDocument();
    expect(screen.getByText("24일 토 · 오늘")).toBeInTheDocument();
    expect(screen.getByText("화 · 없음")).toBeInTheDocument();
    expect(screen.getByText("일 · 없음")).toBeInTheDocument();
    expect(screen.queryByText("24일 토")).toBeNull();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);

    const next = week("2026-10-26", { "2026-10-26": [todo(3, "치과", { planned_for: "2026-10-26" })] });
    renderWithProviders(<PeriodList props={{ week: "2026-W44" }} data={{ today: TODAY, start: "2026-10-26", end: "2026-11-01", days: next, outside: [] }} ctx={makeCtx()} />);
    expect(screen.getByText("26일 월")).toBeInTheDocument();
  });

  it("folds over eight rows", async () => {
    const many = Array.from({ length: 11 }, (_, i) => todo(i + 1, `일 ${i + 1}`));
    renderWithProviders(<PeriodList props={{ day: TODAY }} data={dayData(TODAY, many)} ctx={makeCtx()} />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(8);
    await userEvent.click(screen.getByRole("button", { name: copy.parts.more(3) }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(11);
  });

  it("highlight rows", () => {
    renderWithProviders(<PeriodList props={{ day: TODAY, highlight_task_ids: [2] }} data={dayData(TODAY, [todo(1, "운동"), todo(2, "장보기")])} ctx={makeCtx()} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).not.toHaveClass("highlight");
    expect(rows[1]).toHaveClass("highlight");
    expect(within(rows[1]).getByText(copy.parts.changedBySecretary)).toBeInTheDocument();
    expect(within(rows[0]).queryByText(copy.parts.changedBySecretary)).toBeNull();
  });

  it("outside groups", () => {
    const outside = [
      { reason: "moved" as const, todo: todo(5, "치과", { planned_for: "2026-11-03" }) },
      { reason: "dropped" as const, todo: todo(6, "정리", { status: "dropped" }) },
    ];
    renderWithProviders(<PeriodList props={{ day: TODAY, highlight_task_ids: [5, 6] }} data={{ ...dayData(TODAY, [todo(1, "운동")]), outside }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.outsideHead.moved)).toBeInTheDocument();
    expect(screen.getByText("11월 3일 (화)")).toBeInTheDocument();
    expect(screen.getByText(copy.parts.outsideHead.dropped)).toBeInTheDocument();
    expect(screen.getByText("정리")).toHaveClass("struck");
    expect(screen.queryByRole("checkbox", { name: copy.parts.checkLabel("정리") })).toBeNull();
    expect(screen.queryByText(copy.parts.outsideHead.noDate)).toBeNull();
    // Outside rows are not in data.days: nothing there completes (8장).
    expect(screen.queryByRole("checkbox", { name: copy.parts.checkLabel("치과") })).toBeNull();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });

  it("no date group", () => {
    const outside = [{ reason: "no_date" as const, todo: todo(7, "편지", { planned_for: null }) }];
    renderWithProviders(<PeriodList props={{ day: TODAY, highlight_task_ids: [7] }} data={{ ...dayData(TODAY, []), outside }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.outsideHead.noDate)).toBeInTheDocument();
    expect(screen.getByText("편지")).toBeInTheDocument();
  });

  it("open buttons by period", async () => {
    const onOpen = vi.fn();
    const { unmount } = renderWithProviders(<PeriodList props={{ day: TODAY }} data={dayData(TODAY, [todo(1, "운동")])} ctx={makeCtx({ onOpen })} />);
    await userEvent.click(screen.getByRole("button", { name: copy.parts.openTodos }));
    expect(onOpen).toHaveBeenLastCalledWith("todos_day");
    expect(screen.queryByRole("button", { name: copy.parts.openActivity })).toBeNull();
    unmount();

    const days = week("2026-10-19");
    const r = renderWithProviders(<PeriodList props={{ week: "2026-W43", highlight_task_ids: [1] }} data={{ today: TODAY, days, outside: [] }} ctx={makeCtx({ onOpen })} />);
    await userEvent.click(screen.getByRole("button", { name: copy.parts.openTodos }));
    expect(onOpen).toHaveBeenLastCalledWith("todos_week");
    await userEvent.click(screen.getByRole("button", { name: copy.parts.openActivity }));
    expect(onOpen).toHaveBeenLastCalledWith("activity");
    r.unmount();

    renderWithProviders(<PeriodList props={{ week: "2026-W44" }} data={{ today: TODAY, days: week("2026-10-26"), outside: [] }} ctx={makeCtx({ onOpen })} />);
    expect(card().queryByRole("button")).toBeNull();
  });

  it("check completes", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<PeriodList props={{ day: TODAY }} data={dayData(TODAY, [todo(1, "운동"), todo(2, "장보기", { status: "done" })])} ctx={ctx} />);
    expect(screen.getByRole("checkbox", { name: copy.parts.checkLabel("장보기") })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동") }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "complete_task", args: { id: 1 } });
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동") })).toBeChecked();
  });

  it("no undo here", () => {
    renderWithProviders(<PeriodList props={{ day: TODAY, highlight_task_ids: [1] }} data={dayData(TODAY, [todo(1, "운동")])} ctx={makeCtx({ onOpen: vi.fn() })} />);
    expect(screen.queryByRole("button", { name: copy.chat.undo })).toBeNull();
  });

  it("read only keeps open", async () => {
    const onOpen = vi.fn();
    renderWithProviders(<PeriodList props={{ day: TODAY }} data={dayData(TODAY, [todo(1, "운동")])} ctx={makeCtx({ readOnly: true, onOpen })} />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText(copy.offline.writeLater)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: copy.parts.openTodos }));
    expect(onOpen).toHaveBeenCalledWith("todos_day");
  });

  it("restored keeps open", async () => {
    const onOpen = vi.fn();
    renderWithProviders(<PeriodList props={{ day: TODAY }} data={dayData(TODAY, [todo(1, "운동")])} ctx={makeCtx({ restored: true, onOpen })} />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.queryByText(copy.offline.writeLater)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: copy.parts.openTodos }));
    expect(onOpen).toHaveBeenCalledWith("todos_day");
  });

  it("no data", () => {
    renderWithProviders(<PeriodList props={{ week: "2026-W44" }} ctx={makeCtx()} />);
    expect(title()).toBe("10월 26일 ~ 11월 1일");
    expect(screen.getByText(copy.parts.periodFailed)).toBeInTheDocument();
  });

  it("no onOpen no open buttons", () => {
    renderWithProviders(<PeriodList props={{ day: TODAY, highlight_task_ids: [1] }} data={dayData(TODAY, [todo(1, "운동")])} ctx={makeCtx()} />);
    expect(card().queryByRole("button")).toBeNull();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { gridFrom, HabitGrid, isoWeekMonday, weekLines } from "./HabitGrid";

const TODAY = "2026-10-24"; // a Saturday

const cells = (c: HTMLElement) => [...c.querySelectorAll<HTMLElement>("[data-date]")];
const cellOf = (c: HTMLElement, date: string) => c.querySelector<HTMLElement>(`[data-date="${date}"]`)!;
const dotsIn = (el: HTMLElement) => el.querySelectorAll("[data-dot]").length;

function grid(checkedDates: string[] = [], onToggle = vi.fn()) {
  const { container } = render(<HabitGrid from={gridFrom(TODAY)} today={TODAY} checkedDates={checkedDates} onToggle={onToggle} />);
  return { container, onToggle };
}

describe("HabitGrid", () => {
  it("starts_monday_three_weeks_ago", () => {
    expect(gridFrom(TODAY)).toBe("2026-09-28");
    expect(gridFrom("2026-10-26")).toBe("2026-10-05"); // a Monday is the first day of its own week
    expect(gridFrom("2026-10-25")).toBe("2026-09-28"); // Sunday still belongs to the Monday before
    const { container } = grid();
    const all = cells(container);
    expect(all).toHaveLength(28);
    expect(all[0].dataset.date).toBe("2026-09-28");
    expect(all[27].dataset.date).toBe("2026-10-25"); // this week's Sunday
    // a grey date number in every cell
    for (const c of all) expect(c.textContent).toBe(String(Number(c.dataset.date!.slice(8))));
    expect(all[0].textContent).toBe("28");
    expect(all[3].textContent).toBe("1"); // 2026-10-01
  });

  it("only_checked_days_have_dots", () => {
    const { container } = grid(["2026-10-22", "2026-10-01"]);
    expect(container.querySelectorAll("[data-dot]")).toHaveLength(2);
    expect(dotsIn(cellOf(container, "2026-10-22"))).toBe(1);
    expect(dotsIn(cellOf(container, "2026-10-01"))).toBe(1);
    expect(dotsIn(cellOf(container, "2026-10-23"))).toBe(0);
  });

  it("cells_outside_7_days_not_pressable", async () => {
    const { container, onToggle } = grid(["2026-10-22"]);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.dataset.date)).toEqual(["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"]);
    expect(cellOf(container, "2026-10-17").tagName).not.toBe("BUTTON");
    expect(cellOf(container, "2026-10-25").tagName).not.toBe("BUTTON");
    expect(screen.getByRole("button", { name: copy.dateParts.monthDay(10, 22) })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: copy.dateParts.monthDay(10, 20) })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: copy.dateParts.monthDay(10, 20) }));
    expect(onToggle).toHaveBeenCalledWith("2026-10-20");
    await userEvent.click(cellOf(container, "2026-10-17"));
    await userEvent.click(cellOf(container, "2026-10-25"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("read-only grid has no pressable cell", () => {
    render(<HabitGrid from={gridFrom(TODAY)} today={TODAY} checkedDates={[]} />);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("no_empty_circles_or_x", () => {
    const { container } = grid(["2026-10-22"]);
    const all = cells(container);
    for (const c of all) {
      if (c.dataset.date === "2026-10-22") continue;
      // only the number: no ring, no X, nothing red
      expect(c.children).toHaveLength(1);
      expect(c.textContent).toMatch(/^\d{1,2}$/);
    }
    expect(container.textContent).not.toMatch(/[xX×✕✗]/);
    // today's number is bold, the cells after today are faint
    expect(cellOf(container, TODAY).className).toMatch(/today/);
    expect(cellOf(container, "2026-10-25").className).toMatch(/future/);
    expect(cellOf(container, "2026-10-23").className).not.toMatch(/future|today/);
  });
});

describe("weekLines", () => {
  it("isoWeekMonday", () => {
    expect(isoWeekMonday("2026-W43")).toBe("2026-10-19");
    expect(isoWeekMonday("2026-W40")).toBe("2026-09-28");
    expect(isoWeekMonday("2026-W53")).toBe("2026-12-28");
    expect(isoWeekMonday("2027-W01")).toBe("2027-01-04");
  });

  it("weekLines_skip_zero_weeks", () => {
    const weeks = [
      { week: "2026-W41", count: 1 },
      { week: "2026-W43", count: 2 },
      { week: "2026-W42", count: 3 },
      { week: "2026-W40", count: 0 },
    ];
    expect(weekLines(weeks, TODAY)).toEqual(["이번 주 2번", "지난주 3번", "10월 5일 주 1번"]);
    expect(weekLines([], TODAY)).toEqual([]);
    expect(weekLines([{ week: "2026-W43", count: 0 }], TODAY)).toEqual([]);
  });
});

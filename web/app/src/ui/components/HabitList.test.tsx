import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { Habit } from "../../api/types.gen";
import { copy } from "../../lib/copy";
import { makeHabit, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { HabitList } from "./HabitList";

const DATE = "2026-10-24";

const daily = makeHabit(1, "물 마시기", { week_count: 4 });
const weekly = makeHabit(2, "운동", { kind: "weekly", target_per_week: 3, week_count: 2 });
const met = makeHabit(3, "독서", { kind: "weekly", target_per_week: 3, week_count: 3, checked: true });

// The BE's answer to check_habit / uncheck_habit: {habit, date, already} (SP7 5.4).
function answerWith(habit: (body: Record<string, unknown>) => Habit) {
  return (body: Record<string, unknown>) =>
    HttpResponse.json({
      status: "applied",
      activity_id: 910,
      undo_id: 910,
      result: { habit: habit(body), date: DATE, already: false },
      confirmation: "✓ 습관: 운동", // taste-skill-ignore: BE confirmation (appendix A), not UI
    });
}

const box = (title: string) => screen.getByRole("checkbox", { name: copy.parts.checkLabel(title) });

describe("HabitList", () => {
  it("renders_meta_copy_for_daily_weekly_met", () => {
    renderWithProviders(<HabitList habits={[daily, weekly, met]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(screen.getByText("이번 주 4번")).toBeInTheDocument();
    expect(screen.getByText("이번 주 2번 · 목표 3번")).toBeInTheDocument();
    expect(screen.getByText("이번 주 목표만큼 했어요")).toBeInTheDocument();
    expect(box("물 마시기")).not.toBeChecked();
    expect(box("독서")).toBeChecked();
  });

  it("press_calls_check_then_uncheck", async () => {
    const bodies = serveActions(
      answerWith((b) => ({ ...weekly, checked: b.action === "check_habit", week_count: b.action === "check_habit" ? 3 : 2 })),
    );
    const onChanged = vi.fn();
    renderWithProviders(<HabitList habits={[weekly]} date={DATE} readOnly={false} onChanged={onChanged} />);
    await userEvent.click(box("운동"));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "check_habit", args: { id: 2, date: DATE } });
    await waitFor(() => expect(box("운동")).toBeChecked());
    expect(screen.getByText("이번 주 목표만큼 했어요")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(1);
    // Applied right away, with "되돌리기" on the toast (9장: no confirm for a light, undoable write).
    expect(await screen.findByRole("button", { name: copy.activity.undo })).toBeInTheDocument();

    await userEvent.click(box("운동"));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "uncheck_habit", args: { id: 2, date: DATE } });
    await waitFor(() => expect(box("운동")).not.toBeChecked());
    expect(screen.getByText("이번 주 2번 · 목표 3번")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("a refused check leaves the row as it was", async () => {
    const bodies = serveActions(() =>
      HttpResponse.json({ error: { code: "rejected", message: "쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요." } }, { status: 422 }),
    );
    const onChanged = vi.fn();
    renderWithProviders(<HabitList habits={[daily]} date={DATE} readOnly={false} onChanged={onChanged} />);
    await userEvent.click(box("물 마시기"));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(await screen.findByText("쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요.")).toBeInTheDocument();
    expect(box("물 마시기")).not.toBeChecked();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("read_only_disables_press", async () => {
    const bodies = serveActions();
    renderWithProviders(<HabitList habits={[daily, met]} date={DATE} readOnly onChanged={vi.fn()} />);
    expect(screen.getByText("물 마시기")).toBeInTheDocument();
    for (const c of screen.getAllByRole("checkbox")) expect(c).toBeDisabled();
    await userEvent.click(box("물 마시기"));
    expect(bodies).toHaveLength(0);
    // The checked one still reads as checked: the drawn circle keeps its state.
    expect(box("독서")).toBeChecked();
  });

  it("no_strikethrough_when_checked", () => {
    renderWithProviders(<HabitList habits={[met]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(box("독서")).toBeChecked();
    expect(screen.getByText("독서")).not.toHaveClass("done");
  });

  it("no_ratio_or_remaining_text", () => {
    const many = [
      daily,
      weekly,
      met,
      makeHabit(4, "산책", { kind: "weekly", target_per_week: 6, week_count: 1 }),
      makeHabit(5, "명상", { kind: "weekly", target_per_week: 2, week_count: 5 }),
      makeHabit(6, "일기", { week_count: 0 }),
    ];
    const { container } = renderWithProviders(<HabitList habits={many} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/%/);
    expect(text).not.toMatch(/남음|남은/);
    expect(text).not.toMatch(/\d+\s*\/\s*\d+/);
    expect(container.querySelector("progress, [role='progressbar']")).toBeNull();
  });

  it("rows are 52px with a 44px check area", () => {
    const { container } = renderWithProviders(<HabitList habits={[daily]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(container.querySelector("ul")).toHaveClass("habitRows");
    expect(box("물 마시기")).toHaveClass("check");
  });

  it("no habits shows the add row to the habits screen", () => {
    renderWithProviders(<HabitList habits={[]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(screen.getByRole("link", { name: "습관 추가하기" })).toHaveAttribute("href", "/habits/");
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

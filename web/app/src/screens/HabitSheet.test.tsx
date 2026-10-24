import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { makeHabit, serveActions } from "../test/parts";
import { renderWithProviders } from "../test/render";
import { HabitSheet } from "./HabitSheet";

const submit = (name: string) => screen.getByRole("button", { name });
const titleBox = () => screen.getByLabelText(copy.habits.titleLabel);

function open(habit?: ReturnType<typeof makeHabit>) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  renderWithProviders(<HabitSheet open onClose={onClose} habit={habit ?? null} onSaved={onSaved} />);
  return { onClose, onSaved };
}

describe("HabitSheet", () => {
  it("weekly_requires_1_to_6", async () => {
    const bodies = serveActions();
    open();
    await userEvent.type(titleBox(), "운동");
    await userEvent.click(screen.getByRole("button", { name: copy.areas.health }));
    expect(submit(copy.habits.addSubmit)).toBeEnabled();
    await userEvent.click(screen.getByRole("radio", { name: copy.habits.weekly }));
    // 주 N회 with no number picked yet cannot be added
    expect(submit(copy.habits.addSubmit)).toBeDisabled();
    const pills = screen.getAllByRole("button", { name: /^[1-9]$/ });
    expect(pills.map((p) => p.textContent)).toEqual(["1", "2", "3", "4", "5", "6"]);
    await userEvent.click(screen.getByRole("button", { name: "3" }));
    expect(screen.getByRole("button", { name: "3" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(submit(copy.habits.addSubmit));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "add_habit", args: { title: "운동", area: "health", kind: "weekly", target_per_week: 3 } });
  });

  it("title_40_chars", async () => {
    const bodies = serveActions();
    open();
    await userEvent.type(titleBox(), "가".repeat(45));
    expect(titleBox()).toHaveValue("가".repeat(40));
    // 40 code points with emoji (two UTF-16 units each) are a 40-character title, as the BE counts
    const emoji = "💧".repeat(20) + "물".repeat(20);
    fireEvent.change(titleBox(), { target: { value: emoji } });
    expect(titleBox()).toHaveValue(emoji);
    await userEvent.click(screen.getByRole("button", { name: copy.areas.health }));
    await userEvent.click(submit(copy.habits.addSubmit));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0].args as { title: string }).title).toBe(emoji);
  });

  it("title and area are needed; a blank title is not a title", async () => {
    open();
    expect(submit(copy.habits.addSubmit)).toBeDisabled();
    await userEvent.type(titleBox(), "   ");
    await userEvent.click(screen.getByRole("button", { name: copy.areas.health }));
    expect(submit(copy.habits.addSubmit)).toBeDisabled();
    await userEvent.type(titleBox(), "물");
    expect(submit(copy.habits.addSubmit)).toBeEnabled();
  });

  it("add_calls_add_habit", async () => {
    const bodies = serveActions();
    const { onClose, onSaved } = open();
    expect(screen.getByRole("heading", { name: copy.habits.add })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: copy.habits.daily })).toHaveAttribute("aria-checked", "true");
    await userEvent.type(titleBox(), "  물 마시기 ");
    await userEvent.click(screen.getByRole("button", { name: copy.areas.health }));
    await userEvent.click(submit(copy.habits.addSubmit));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ action: "add_habit", args: { title: "물 마시기", area: "health", kind: "daily" } });
    expect(bodies[0].args).not.toHaveProperty("target_per_week");
    expect(onSaved).toHaveBeenCalled();
  });

  it("a refused add keeps the sheet open", async () => {
    const { HttpResponse } = await import("msw");
    serveActions(() => HttpResponse.json({ error: { code: "rejected", message: "이미 있는 습관이에요." } }, { status: 422 }));
    const { onClose, onSaved } = open();
    await userEvent.type(titleBox(), "운동");
    await userEvent.click(screen.getByRole("button", { name: copy.areas.health }));
    await userEvent.click(submit(copy.habits.addSubmit));
    expect(await screen.findByText("이미 있는 습관이에요.")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("edit_calls_update_habit", async () => {
    const bodies = serveActions();
    const habit = makeHabit(2, "운동", { kind: "weekly", target_per_week: 3, area: "health" });
    const { onClose } = open(habit);
    expect(screen.getByRole("heading", { name: copy.habits.editTitle })).toBeInTheDocument();
    expect(titleBox()).toHaveValue("운동");
    expect(screen.getByRole("button", { name: copy.areas.health })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("radio", { name: copy.habits.weekly })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: "3" })).toHaveAttribute("aria-pressed", "true");
    // nothing changed yet: nothing to save
    expect(submit(copy.habits.save)).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "2" }));
    await userEvent.click(submit(copy.habits.save));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    // only what changed goes (the BE keeps the rest)
    expect(bodies[0]).toEqual(expect.objectContaining({ action: "update_habit", args: { id: 2, kind: "weekly", target_per_week: 2 } }));
  });

  it("edit to daily sends the kind only, a rename sends the title only", async () => {
    const bodies = serveActions();
    const habit = makeHabit(2, "운동", { kind: "weekly", target_per_week: 3 });
    open(habit);
    await userEvent.click(screen.getByRole("radio", { name: copy.habits.daily }));
    expect(screen.queryByRole("button", { name: "3" })).not.toBeInTheDocument();
    await userEvent.click(submit(copy.habits.save));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].args).toEqual({ id: 2, kind: "daily" });
  });

  it("rename sends the title only", async () => {
    const bodies = serveActions();
    open(makeHabit(1, "물 마시기"));
    await userEvent.clear(titleBox());
    await userEvent.type(titleBox(), "물 두 잔");
    await userEvent.click(submit(copy.habits.save));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].args).toEqual({ id: 1, title: "물 두 잔" });
  });
});

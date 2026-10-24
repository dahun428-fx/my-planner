import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, makeHabit, makeTodo, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { ChapterDraft } from "./ChapterDraft";
import { Choice } from "./Choice";
import { HabitCheck } from "./HabitList";
import { MilestoneDraft } from "./MilestoneDraft";
import { TodoDraft } from "./TodoDraft";

// A part restored from the device after a reload (4.6) holds rows as they were then: it writes nothing.
const ctx = makeCtx({ restored: true, onChoose: vi.fn() });

const cases: [string, ReactElement, string][] = [
  ["TodoDraft", <TodoDraft key="a" props={{ task_ids: [1] }} data={{ todos: [makeTodo(1, "빨래", "draft")] }} ctx={ctx} />, "빨래"],
  ["MilestoneDraft", <MilestoneDraft key="b" props={{ milestone_ids: [1] }} data={{ milestones: [{ id: 1, title: "사건", date: "2020-01" }] }} ctx={ctx} />, "사건"],
  ["ChapterDraft", <ChapterDraft key="c" props={{ chapter_ids: [1] }} data={{ chapters: [{ id: 1, title: "챕터", start_month: "2020-01", end_month: null }] }} ctx={ctx} />, "챕터"],
];

describe("restored parts", () => {
  it.each(cases)("%s shows its rows without action buttons", (_name, el, title) => {
    renderWithProviders(el);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toEqual([]);
  });

  it("Choice pills are off: a stale choice must not go into the current conversation", () => {
    renderWithProviders(<Choice props={{ question: "q", options: [{ id: "a", label: "가" }, { id: "b", label: "나" }] }} ctx={ctx} />);
    for (const b of screen.getAllByRole("button")) expect(b).toBeDisabled();
  });

  it("HabitCheck rows are drawn, not pressable: the habits may have been checked elsewhere since", async () => {
    const bodies = serveActions();
    renderWithProviders(<HabitCheck props={{ date: "2026-10-24" }} data={{ habits: [makeHabit(1, "물 마시기"), makeHabit(2, "운동", { checked: true })] }} ctx={ctx} />);
    expect(screen.getByText("물 마시기")).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toEqual([]);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    for (const b of boxes) expect(b).toBeDisabled();
    await userEvent.click(boxes[0]);
    expect(bodies).toHaveLength(0);
    // Online: no "연결되면" reason under a restored card.
    expect(screen.queryByText(copy.offline.writeLater)).toBeNull();
  });
});

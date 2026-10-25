import { screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, makeHabit, makeTodo as t } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { AreaScores } from "./AreaScores";
import { ChapterDraft } from "./ChapterDraft";
import { Choice } from "./Choice";
import { ConditionPicker } from "./ConditionPicker";
import { Confirm } from "./Confirm";
import { HabitCheck } from "./HabitList";
import { LadderPicker } from "./LadderPicker";
import { MilestoneDraft } from "./MilestoneDraft";
import { TodoDraft } from "./TodoDraft";
import { TodoList } from "./TodoList";

const ctx = makeCtx({ readOnly: true });

const cases: [string, ReactElement][] = [
  ["TodoList", <TodoList key="a" props={{ title: "t", task_ids: [1] }} data={{ todos: [t(1, "open")] }} ctx={ctx} />],
  ["Choice", <Choice key="b" props={{ question: "q", options: [{ id: "a", label: "가" }, { id: "b", label: "나" }] }} ctx={ctx} />],
  ["TodoDraft", <TodoDraft key="c" props={{ task_ids: [1] }} data={{ todos: [t(1, "draft")] }} ctx={ctx} />],
  ["ConditionPicker", <ConditionPicker key="d" props={{ date: "2026-10-24" }} ctx={ctx} />],
  ["LadderPicker", <LadderPicker key="e" props={{ period: "2026-10", field: "now" }} ctx={ctx} />],
  ["AreaScores", <AreaScores key="f" props={{ period: "2026-Q4", previous: {} }} ctx={ctx} />],
  ["MilestoneDraft", <MilestoneDraft key="g" props={{ milestone_ids: [1] }} data={{ milestones: [{ id: 1, title: "사건", date: "2020-01" }] }} ctx={ctx} />],
  ["ChapterDraft", <ChapterDraft key="h" props={{ chapter_ids: [1] }} data={{ chapters: [{ id: 1, title: "챕터", start_month: "2020-01", end_month: null }] }} ctx={ctx} />],
  ["Confirm", <Confirm key="i" props={{ summary: "s", confirm_token: "t", action: "drop_task", args: { id: 1 } }} ctx={ctx} />],
  ["HabitCheck", <HabitCheck key="j" props={{ date: "2026-10-24" }} data={{ habits: [makeHabit(1, "물 마시기"), makeHabit(2, "운동", { checked: true })] }} ctx={ctx} />],
];

describe("read only", () => {
  it.each(cases)("read only disables buttons: %s", (_name, el) => {
    renderWithProviders(el);
    const controls = screen.queryAllByRole("button").concat(screen.queryAllByRole("checkbox"), screen.queryAllByRole("radio"), screen.queryAllByRole("textbox"));
    expect(controls.length).toBeGreaterThan(0);
    for (const c of controls) expect(c).toBeDisabled();
    expect(screen.getByText(copy.offline.writeLater)).toBeInTheDocument();
  });
});

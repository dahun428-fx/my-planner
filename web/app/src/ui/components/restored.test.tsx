import { screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { makeCtx, makeTodo } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { ChapterDraft } from "./ChapterDraft";
import { Choice } from "./Choice";
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
});

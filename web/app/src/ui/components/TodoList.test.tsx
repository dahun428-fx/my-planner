import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Todo } from "../../api/types.gen";
import { copy } from "../../lib/copy";
import { makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { TodoList } from "./TodoList";

const todo = (id: number, title: string, status: "open" | "done" = "open"): Todo => ({
  id,
  title,
  status,
  planned_for: "2026-10-24",
  scheduled_at: null,
  parent_id: null,
  areas: [],
  note: "",
  priority: null,
  completed_at: null,
});

describe("TodoList", () => {
  it("checks complete_task", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<TodoList props={{ title: "이번 주", task_ids: [12, 13] }} data={{ todos: [todo(12, "운동 30분"), todo(13, "장보기")] }} ctx={ctx} />);
    await userEvent.click(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동 30분") }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "complete_task", args: { id: 12 } });
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동 30분") })).toBeChecked();
  });

  it("fallback without data", () => {
    renderWithProviders(<TodoList props={{ title: "이번 주", task_ids: [12, 13, 14] }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.todoCount(3))).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("folds after six rows", async () => {
    const many = Array.from({ length: 9 }, (_, i) => todo(i + 1, `일 ${i + 1}`));
    renderWithProviders(<TodoList props={{ title: "많이", task_ids: many.map((t) => t.id) }} data={{ todos: many }} ctx={makeCtx()} />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(6);
    await userEvent.click(screen.getByRole("button", { name: copy.parts.more(3) }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(9);
  });
});

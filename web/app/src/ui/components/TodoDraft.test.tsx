import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, makeTodo, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { TodoDraft } from "./TodoDraft";

const draft = (id: number, title: string) => makeTodo(id, title, "draft");
const data = { todos: [draft(55, "빨래 개기"), draft(56, "우편물 확인")] };

describe("TodoDraft", () => {
  it("confirms checked ids", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<TodoDraft props={{ task_ids: [55, 56] }} data={data} ctx={ctx} />);
    expect(screen.getByText(copy.parts.draftHint)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: copy.parts.checkLabel("우편물 확인") }));
    await userEvent.click(screen.getByRole("button", { name: copy.parts.confirmCount(1) }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "confirm_tasks", args: { ids: [55] } });
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(1));
  });

  it("drops checked", async () => {
    const bodies = serveActions();
    const ctx = makeCtx();
    renderWithProviders(<TodoDraft props={{ task_ids: [55, 56] }} data={data} ctx={ctx} />);
    await userEvent.click(screen.getByRole("button", { name: copy.parts.dropChecked }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies.map((b) => [b.action, (b.args as { id: number }).id])).toEqual([
      ["drop_task", 55],
      ["drop_task", 56],
    ]);
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(1));
  });

  it("fallback without data", () => {
    renderWithProviders(<TodoDraft props={{ task_ids: [55, 56] }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.todoCount(2))).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

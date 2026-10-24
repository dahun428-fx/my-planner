import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { AddTodoSheet } from "./AddTodoSheet";

function actions(answer: (body: Record<string, unknown>) => Response | Promise<Response>) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      bodies.push(body);
      return answer(body);
    }),
  );
  return bodies;
}
const applied = () => HttpResponse.json({ status: "applied", activity_id: 900, undo_id: 900, result: {}, confirmation: "✓ 추가: 치과" }); // taste-skill-ignore: BE confirmation prefix (R4b), not UI

function open(onClose = vi.fn()) {
  renderWithProviders(<AddTodoSheet open onClose={onClose} defaultDate="2026-10-24" />);
  return onClose;
}
const addButton = () => screen.getByRole("button", { name: copy.todos.addSubmit });

describe("AddTodoSheet", () => {
  it("title required and trimmed", async () => {
    const bodies = actions(() => applied());
    open();
    const user = userEvent.setup();
    expect(addButton()).toBeDisabled();
    await user.type(screen.getByLabelText(copy.todos.titleLabel), "   ");
    expect(addButton()).toBeDisabled();
    await user.type(screen.getByLabelText(copy.todos.titleLabel), "  치과  ");
    expect(addButton()).toBeEnabled();
    await user.click(addButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0].args as Record<string, unknown>).title).toBe("치과");
  });

  it("sends add_task with areas and planned_for", async () => {
    const bodies = actions(() => applied());
    const onClose = open();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.todos.titleLabel), "치과");
    await user.click(screen.getByRole("button", { name: copy.areas.health, pressed: false }));
    await user.click(screen.getByRole("button", { name: copy.areas.finance, pressed: false }));
    await user.click(screen.getByRole("radio", { name: copy.todos.dateTomorrow }));
    await user.type(screen.getByLabelText(copy.todos.noteLabel), "예약 확인");
    await user.click(addButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      action: "add_task",
      args: { title: "치과", areas: ["finance", "health"], planned_for: "2026-10-25", note: "예약 확인" },
    });
    expect((bodies[0].args as Record<string, unknown>).scheduled_at).toBeUndefined();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("no date sends no planned_for", async () => {
    const bodies = actions(() => applied());
    open();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.todos.titleLabel), "치과");
    await user.click(screen.getByRole("radio", { name: copy.todos.dateNone }));
    expect(screen.getByLabelText(copy.todos.timeLabel)).toBeDisabled();
    await user.click(addButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0].args as Record<string, unknown>).planned_for).toBeUndefined();
  });

  it("scheduled_at is KST converted to UTC", async () => {
    const bodies = actions(() => applied());
    open();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.todos.titleLabel), "치과");
    await user.click(screen.getByRole("radio", { name: copy.todos.datePick }));
    fireEvent.change(screen.getByLabelText(copy.todos.dateLabel), { target: { value: "2026-10-25" } });
    fireEvent.change(screen.getByLabelText(copy.todos.timeLabel), { target: { value: "14:00" } });
    await user.click(addButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ args: { planned_for: "2026-10-25", scheduled_at: "2026-10-25T05:00:00Z" } });
  });

  it("double tap adds once", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const bodies = actions(async () => {
      await gate;
      return applied();
    });
    open();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.todos.titleLabel), "치과");
    fireEvent.click(addButton());
    fireEvent.click(addButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    release();
    await waitFor(() => expect(screen.getByText("✓ 추가: 치과")).toBeInTheDocument()); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(bodies).toHaveLength(1);
  });

  it("a conflict keeps the sheet open and says it failed", async () => {
    actions(() => HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 }));
    const onClose = open();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.todos.titleLabel), "치과");
    await user.click(addButton());
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});

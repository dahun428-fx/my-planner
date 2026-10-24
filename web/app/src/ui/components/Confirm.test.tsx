import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { applied, makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { Confirm } from "./Confirm";

const props = { summary: "‘장보기’를 할 일에서 뺄까요?", confirm_token: "tok-abc-123", action: "drop_task", args: { id: 13 } };
const conflict = () => HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 });

describe("Confirm", () => {
  it("change sends token with new id", async () => {
    const bodies = serveActions();
    const ctx = makeCtx({ where: "today" });
    renderWithProviders(<Confirm props={props} ctx={ctx} />);
    await userEvent.click(screen.getByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "drop_task", args: { id: 13 }, confirm_token: "tok-abc-123" });
    expect(bodies[0].client_msg_id).toMatch(/^[0-9a-f-]{36}$/);
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(1));
  });

  it("keep sends decline_confirm", async () => {
    const bodies = serveActions();
    const ctx = makeCtx({ where: "today" });
    renderWithProviders(<Confirm props={props} ctx={ctx} />);
    await userEvent.click(screen.getByRole("button", { name: copy.todos.keep }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "decline_confirm", args: { confirm_token: "tok-abc-123" } });
    await waitFor(() => expect(ctx.onAfterAction).toHaveBeenCalledTimes(1));
  });

  it("conflict shows gone copy", async () => {
    serveActions(conflict);
    renderWithProviders(<Confirm props={props} ctx={makeCtx()} />);
    await userEvent.click(screen.getByRole("button", { name: copy.todos.change }));
    expect(await screen.findByText(copy.parts.confirmGone)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.todos.change })).toBeNull();
    expect(screen.queryByText(props.summary)).toBeNull();
  });

  it("two quick presses send one request", async () => {
    const bodies = serveActions();
    renderWithProviders(<Confirm props={props} ctx={makeCtx()} />);
    const b = screen.getByRole("button", { name: copy.todos.change });
    await userEvent.dblClick(b);
    await waitFor(() => expect(bodies).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(bodies).toHaveLength(1);
  });

  it("needs_confirm answer shows the failure toast and keeps the card", async () => {
    serveActions(() => HttpResponse.json({ status: "needs_confirm", confirm_token: "tok-2", summary: "또 확인해요", expires_at: "2026-10-24T10:00:00Z" }));
    renderWithProviders(<Confirm props={props} ctx={makeCtx()} />);
    await userEvent.click(screen.getByRole("button", { name: copy.todos.change }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: copy.todos.change })).toBeEnabled());
    expect(screen.getByText(props.summary)).toBeInTheDocument();
  });

  it("tapping both buttons sends one request", async () => {
    const bodies = serveActions(async () => {
      await new Promise((r) => setTimeout(r, 80));
      return applied();
    });
    renderWithProviders(<Confirm props={props} ctx={makeCtx()} />);
    await userEvent.click(screen.getByRole("button", { name: copy.todos.change }));
    expect(screen.getByRole("button", { name: copy.todos.keep })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: copy.todos.keep }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 150));
    expect(bodies).toHaveLength(1);
  });
});

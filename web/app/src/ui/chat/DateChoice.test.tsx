import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { applied, makeCtx, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import type { PartData, PartTodo } from "../types";
import { DateChoice } from "./DateChoice";

// SP6 6.2, 6.5, Review Focus 3. Today is 2026-10-24 (Sat).
const props = {
  task_id: 53,
  question: "치과 예약은 언제 할까요?",
  candidates: [{ date: "2026-10-24" }, { date: "2026-10-27", note: "오후가 비어요" }, { date: "2026-10-30" }],
};
const todo = (over: Partial<PartTodo> = {}): PartTodo => ({ id: 53, title: "치과 예약", status: "open", planned_for: null, scheduled_at: null, ...over });
const data = (over: Partial<PartTodo> = {}): PartData => ({ today: "2026-10-24", todo: todo(over) });

const candidate = (label: RegExp | string) => screen.getByRole("button", { name: label });
// The card's own buttons (the toast has a "되돌리기" of its own).
const allButtons = () => within(document.querySelector("section")!).getAllByRole("button");

describe("DateChoice", () => {
  it("renders question title and candidates", () => {
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx()} />);
    expect(screen.getByText("치과 예약은 언제 할까요?")).toBeInTheDocument();
    expect(screen.getByText("치과 예약")).toBeInTheDocument();
    expect(candidate(/^오늘 · 10월 24일 \(토\)/)).toBeInTheDocument();
    const tue = candidate(/^10월 27일 \(화\)/);
    expect(within(tue).getByText("오후가 비어요")).toBeInTheDocument();
    // The day and its note read as two words, not one run-together name.
    expect(tue).toHaveAccessibleName("10월 27일 (화) 오후가 비어요");
    expect(candidate(/^10월 30일 \(금\)/)).toBeInTheDocument();
    expect(candidate(copy.parts.otherDay)).toBeInTheDocument();
    expect(allButtons()).toHaveLength(4);
  });

  it("no edit fields", () => {
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx()} />);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  });

  it("pick sends move_task", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const bodies = serveActions(async () => {
      await gate;
      return applied();
    });
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx()} />);
    await userEvent.click(candidate(/^10월 27일/));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "move_task", args: { id: 53, planned_for: "2026-10-27" } });
    for (const b of allButtons()) expect(b).toBeDisabled();
    release();
  });

  it("applied marks chosen", async () => {
    serveActions();
    const ctx = makeCtx();
    renderWithProviders(<DateChoice props={props} data={data()} ctx={ctx} />);
    await userEvent.click(candidate(/^10월 27일/));
    await waitFor(() => expect(candidate(/^10월 27일/)).toHaveAttribute("aria-pressed", "true"));
    expect(candidate(/^오늘/)).toHaveAttribute("aria-pressed", "false");
    for (const b of allButtons()) expect(b).toBeDisabled();
    expect(ctx.onAfterAction).toHaveBeenCalledTimes(1);
  });

  it("failed re-enables", async () => {
    serveActions(() => HttpResponse.error());
    const ctx = makeCtx();
    // No catalog: its good answer would bring the connection back and the "reconnected" toast over this one.
    renderWithProviders(<DateChoice props={props} data={data()} ctx={ctx} />, { catalog: false });
    await userEvent.click(candidate(/^10월 27일/));
    expect(await screen.findByText(copy.actions.offline)).toBeInTheDocument();
    await waitFor(() => expect(candidate(/^10월 27일/)).toBeEnabled());
    expect(candidate(/^10월 27일/)).toHaveAttribute("aria-pressed", "false");
    expect(ctx.onAfterAction).not.toHaveBeenCalled();
  });

  it("rejected re-enables", async () => {
    serveActions(() => HttpResponse.json({ error: { code: "rejected", message: "열린 할 일만 날짜를 옮길 수 있어요." } }, { status: 422 }));
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx()} />);
    await userEvent.click(candidate(/^10월 27일/));
    expect(await screen.findByText("열린 할 일만 날짜를 옮길 수 있어요.")).toBeInTheDocument();
    await waitFor(() => expect(candidate(/^10월 27일/)).toBeEnabled());
  });

  it("needs confirm opens sheet", async () => {
    const bodies = serveActions((b) =>
      b.confirm_token
        ? applied()
        : HttpResponse.json({ status: "needs_confirm", confirm_token: "tok-1", summary: "날짜를 옮겨요: 치과 예약 → 10월 27일 (화)", expires_at: "2026-10-24T09:00:00Z" }),
    );
    const ctx = makeCtx();
    renderWithProviders(<DateChoice props={props} data={data()} ctx={ctx} />);
    await userEvent.click(candidate(/^10월 27일/));
    expect(await screen.findByText("날짜를 옮겨요: 치과 예약 → 10월 27일 (화)")).toBeInTheDocument();
    expect(screen.queryByText(copy.actions.failed)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "move_task", args: { id: 53, planned_for: "2026-10-27" }, confirm_token: "tok-1" });
    expect(bodies[1].client_msg_id).not.toBe(bodies[0].client_msg_id);
    await waitFor(() => expect(candidate(/^10월 27일/)).toHaveAttribute("aria-pressed", "true"));
    expect(ctx.onAfterAction).toHaveBeenCalledTimes(1);
  });

  it("confirm then rejected", async () => {
    // Review Focus 3: the to-do was finished elsewhere between the question and "바꾸기".
    for (const [message, said] of [["열린 할 일만 날짜를 옮길 수 있어요.", "열린 할 일만 날짜를 옮길 수 있어요."], ["", copy.actions.failed]]) {
      serveActions((b) =>
        b.confirm_token
          ? HttpResponse.json({ error: { code: "rejected", message } }, { status: 422 })
          : HttpResponse.json({ status: "needs_confirm", confirm_token: "tok-1", summary: "날짜를 옮겨요: 치과 예약 → 10월 27일 (화)", expires_at: "" }),
      );
      const ctx = makeCtx();
      const { unmount } = renderWithProviders(<DateChoice props={props} data={data()} ctx={ctx} />);
      await userEvent.click(candidate(/^10월 27일/));
      await userEvent.click(await screen.findByRole("button", { name: copy.todos.change }));
      expect(await screen.findByText(said)).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByText("날짜를 옮겨요: 치과 예약 → 10월 27일 (화)")).toBeNull());
      await waitFor(() => expect(candidate(/^10월 27일/)).toBeEnabled());
      expect(candidate(/^10월 27일/)).toHaveAttribute("aria-pressed", "false");
      expect(ctx.onAfterAction).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("confirm that expired says so", async () => {
    serveActions((b) =>
      b.confirm_token
        ? HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 })
        : HttpResponse.json({ status: "needs_confirm", confirm_token: "tok-1", summary: "날짜를 옮겨요: 치과 예약 → 10월 27일 (화)", expires_at: "" }),
    );
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx()} />);
    await userEvent.click(candidate(/^10월 27일/));
    await userEvent.click(await screen.findByRole("button", { name: copy.todos.change }));
    expect(await screen.findByText(copy.todos.confirmExpired)).toBeInTheDocument();
    expect(screen.queryByText(copy.actions.failed)).toBeNull();
    await waitFor(() => expect(candidate(/^10월 27일/)).toBeEnabled());
  });

  it("keeping the date sends nothing and re-enables", async () => {
    const bodies = serveActions(() =>
      HttpResponse.json({ status: "needs_confirm", confirm_token: "tok-1", summary: "날짜를 옮겨요: 치과 예약 → 10월 27일 (화)", expires_at: "" }),
    );
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx()} />);
    await userEvent.click(candidate(/^10월 27일/));
    await userEvent.click(await screen.findByRole("button", { name: copy.todos.keep }));
    await waitFor(() => expect(screen.queryByText("날짜를 옮겨요: 치과 예약 → 10월 27일 (화)")).toBeNull());
    expect(bodies).toHaveLength(1);
    expect(candidate(/^10월 27일/)).toBeEnabled();
  });

  it("other day sends text", async () => {
    const bodies = serveActions();
    const onChoose = vi.fn();
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx({ onChoose })} />);
    await userEvent.click(candidate(copy.parts.otherDay));
    expect(onChoose).toHaveBeenCalledWith("다른 날로 할게요");
    expect(bodies).toHaveLength(0);
  });

  it("already settled", () => {
    const { unmount } = renderWithProviders(<DateChoice props={props} data={data({ status: "done" })} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.alreadySettled)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /10월 27일/ })).toBeNull();
    unmount();
    renderWithProviders(<DateChoice props={props} data={{ today: "2026-10-24", todo: null }} ctx={makeCtx()} />);
    expect(screen.getByText(copy.parts.alreadySettled)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /10월 27일/ })).toBeNull();
  });

  it("read only", () => {
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx({ readOnly: true, onChoose: vi.fn() })} />);
    for (const b of allButtons()) expect(b).toBeDisabled();
    expect(screen.getByText(copy.offline.writeLater)).toBeInTheDocument();
  });

  it("restored", () => {
    renderWithProviders(<DateChoice props={props} data={data()} ctx={makeCtx({ restored: true, onChoose: vi.fn() })} />);
    expect(allButtons()).toHaveLength(4);
    for (const b of allButtons()) expect(b).toBeDisabled();
    expect(screen.queryByText(copy.offline.writeLater)).toBeNull();
  });

  it("no data", () => {
    renderWithProviders(<DateChoice props={props} ctx={makeCtx()} />);
    expect(screen.getByText("치과 예약은 언제 할까요?")).toBeInTheDocument();
    expect(screen.getByText(copy.parts.todoCount(1))).toBeInTheDocument();
    expect(within(document.querySelector("section")!).queryAllByRole("button")).toHaveLength(0);
  });
});

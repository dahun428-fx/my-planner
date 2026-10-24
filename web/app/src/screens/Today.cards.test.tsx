import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import type { Today as TodayData } from "../api/types.gen";
import { copy } from "../lib/copy";
import checkin341 from "../test/fixtures/checkin-341.json";
import todayCards from "../test/fixtures/today-cards.json";
import todayPlain from "../test/fixtures/today.json";
import { serveActions } from "../test/parts";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { Today } from "./Today";

afterEach(async () => {
  await clear();
});

const pending = (id: number) => ({ ...todayPlain.checkins[1], id });

function serve(data: unknown, details: Record<number, unknown> = {}) {
  const asked: number[] = [];
  server.use(
    http.get(`${BASE}/today`, () => HttpResponse.json(data as TodayData)),
    http.get(`${BASE}/checkins/:id`, ({ params }) => {
      const id = Number(params.id);
      asked.push(id);
      return HttpResponse.json(details[id] ?? { ...checkin341, id, cards: [] });
    }),
  );
  return asked;
}

describe("Today cards", () => {
  it("collects ui_confirm from pending checkins", async () => {
    const data = { ...todayPlain, checkins: [pending(341), pending(342)] };
    const asked = serve(data, { 341: checkin341 });
    renderWithProviders(<Today />, { catalog: true });
    expect(await screen.findByText("‘장보기’를 할 일에서 뺄까요?")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: copy.today.needsConfirm })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: copy.todos.change })).toHaveLength(1);
    // the draft card in the same check-in is not a confirm
    expect(screen.queryByText(copy.parts.draftHeading)).toBeNull();
    expect(asked.sort()).toEqual([341, 342]);
    // sits after the pending check-in line and before the brief
    const heading = screen.getByRole("heading", { name: copy.today.needsConfirm });
    const brief = screen.getByText(/좋은 아침이에요/);
    expect(heading.compareDocumentPosition(brief) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("no confirm block when none", async () => {
    serve(todayPlain);
    renderWithProviders(<Today />, { catalog: true });
    await screen.findByText("운동 30분");
    await waitFor(() => expect(screen.queryByRole("heading", { name: copy.today.needsConfirm })).toBeNull());
  });

  it("change on a confirm sends the token and reads again", async () => {
    const bodies = serveActions();
    const asked = serve({ ...todayPlain }, { 341: checkin341 });
    renderWithProviders(<Today />, { catalog: true });
    await userEvent.click(await screen.findByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "drop_task", args: { id: 13 }, confirm_token: "tok-abc-123" });
    await waitFor(() => expect(asked.filter((i) => i === 341).length).toBeGreaterThan(1));
  });

  it("pinned cards in order with secretary mark", async () => {
    serve(todayCards);
    renderWithProviders(<Today />, { catalog: true });
    const first = await screen.findByText("이번 주에 챙길 것");
    const second = await screen.findByText("이번 주 운동");
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByText(copy.today.pinnedBySecretary)).toHaveLength(2);
    // the card draws its todos from data
    expect(screen.getAllByRole("checkbox", { name: copy.parts.checkLabel("운동 30분") })).toHaveLength(2); // list row + card row
    // pinned cards come after the to-do list
    const list = screen.getByText("빨래 널기");
    expect(list.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("unpin and reorder send actions", async () => {
    const bodies = serveActions();
    serve(todayCards);
    renderWithProviders(<Today />, { catalog: true });
    await screen.findByText("이번 주에 챙길 것");

    await userEvent.click(screen.getByRole("button", { name: copy.today.pinnedMore("이번 주에 챙길 것") }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).queryByRole("button", { name: copy.today.moveUp })).toBeNull(); // already first
    await userEvent.click(within(sheet).getByRole("button", { name: copy.today.moveDown }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "reorder_cards", args: { ids: [7, 5] } });

    await userEvent.click(screen.getByRole("button", { name: copy.today.pinnedMore("이번 주 운동") }));
    const sheet2 = screen.getByRole("dialog");
    expect(within(sheet2).queryByRole("button", { name: copy.today.moveDown })).toBeNull(); // already last
    await userEvent.click(within(sheet2).getByRole("button", { name: copy.today.moveUp }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "reorder_cards", args: { ids: [7, 5] } });

    await userEvent.click(screen.getByRole("button", { name: copy.today.pinnedMore("이번 주 운동") }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: copy.today.unpin }));
    await waitFor(() => expect(bodies).toHaveLength(3));
    expect(bodies[2]).toMatchObject({ action: "unpin_card", args: { id: 7 } });
  });

  it("unpin conflict shows a toast and reads again", async () => {
    serveActions(() => HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 }));
    let reads = 0;
    server.use(http.get(`${BASE}/today`, () => (reads++, HttpResponse.json(todayCards as TodayData))));
    renderWithProviders(<Today />, { catalog: true });
    await screen.findByText("이번 주에 챙길 것");
    const before = reads;
    await userEvent.click(screen.getByRole("button", { name: copy.today.pinnedMore("이번 주에 챙길 것") }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: copy.today.unpin }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    await waitFor(() => expect(reads).toBeGreaterThan(before));
  });

  it("reorder needs_confirm shows a toast", async () => {
    serveActions(() => HttpResponse.json({ status: "needs_confirm", confirm_token: "t", summary: "s", expires_at: "2026-10-24T10:00:00Z" }));
    serve(todayCards);
    renderWithProviders(<Today />, { catalog: true });
    await screen.findByText("이번 주에 챙길 것");
    await userEvent.click(screen.getByRole("button", { name: copy.today.pinnedMore("이번 주에 챙길 것") }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: copy.today.moveDown }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
  });

  it("a check-in that is gone does not freeze the block", async () => {
    const data = { ...todayPlain, checkins: [pending(341), pending(342)] };
    serve(data, { 341: checkin341 });
    server.use(http.get(`${BASE}/checkins/342`, () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 })));
    renderWithProviders(<Today />, { catalog: true });
    expect(await screen.findByText("‘장보기’를 할 일에서 뺄까요?")).toBeInTheDocument();
  });

  it("reads each pending check-in once", async () => {
    const asked = serve({ ...todayPlain }, { 341: checkin341 });
    renderWithProviders(<Today />, { catalog: true });
    await screen.findByText("‘장보기’를 할 일에서 뺄까요?");
    await new Promise((r) => setTimeout(r, 100));
    expect(asked).toEqual([341]);
  });
});

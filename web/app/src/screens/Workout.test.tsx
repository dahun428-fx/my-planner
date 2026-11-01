import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { clear } from "idb-keyval";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Workout as WorkoutData } from "../api/types.gen";
import { ChatSheetContext } from "../chat/sheetContext";
import { copy } from "../lib/copy";
import { renderWithProviders, seedSnap } from "../test/render";
import { BASE, server } from "../test/server";
import { Workout } from "./Workout";

afterEach(async () => {
  await clear();
});

const PLAN: WorkoutData["plan"] = {
  id: 4,
  title: "주 2번 집 운동",
  note: null,
  created_at: "2026-10-30T01:00:00Z",
  sessions: [
    {
      id: 1,
      position: 1,
      label: "하체",
      weekdays: [0, 3],
      items: [
        { name: "고블릿 스쿼트", sets: 3, reps: "8-10", weight_kg: 16, minutes: null, note: "무릎 안 아픈 깊이까지" },
        { name: "런지", sets: 3, reps: "10", weight_kg: null, minutes: null, note: null },
      ],
    },
    { id: 2, position: 2, label: "상체", weekdays: null, items: [{ name: "푸시업", sets: 3, reps: "최대", weight_kg: null, minutes: null, note: null }] },
  ],
};

const DATA: WorkoutData = {
  plan: PLAN,
  logs: [
    {
      id: 11,
      date: "2026-10-30",
      title: "하체",
      effort: 3,
      note: null,
      session_id: 1,
      items: [
        { name: "스쿼트", sets: 5, reps: 5, weight_kg: 60, minutes: null, distance_km: null },
        { name: "걷기", sets: null, reps: null, weight_kg: null, minutes: 30, distance_km: 2.5 },
      ],
    },
    { id: 12, date: "2026-10-28", title: "상체", effort: null, note: null, session_id: null, items: [] },
  ],
  notes: [
    { id: 21, kind: "equipment", text: "집에 덤벨 20kg까지", updated_at: "2026-10-29T01:00:00Z" },
    { id: 22, kind: "injury", text: "왼쪽 무릎이 가끔 아파요", updated_at: "2026-10-29T01:00:00Z" },
  ],
};

const serve = (data: WorkoutData | (() => WorkoutData) = DATA) => {
  server.use(http.get(`${BASE}/workout`, () => HttpResponse.json(typeof data === "function" ? data() : data)));
};

function actions(handler: (b: Record<string, unknown>) => object) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      const b = (await request.json()) as Record<string, unknown>;
      bodies.push(b);
      return HttpResponse.json(handler(b));
    }),
  );
  return bodies;
}

describe("Workout (SP12 11.2)", () => {
  // The BE's applied answer; the read that follows finds the row gone.
  const applied = (id: number, confirmation: string) => {
    gone = true;
    return { status: "applied", activity_id: id, undo_id: id, result: {}, confirmation };
  };
  let gone = false;
  beforeEach(() => {
    gone = false;
  });

  it("empty state shows talk button that opens the sheet on the mate", async () => {
    serve({ plan: null, logs: [], notes: [] });
    const open = vi.fn();
    renderWithProviders(
      <ChatSheetContext.Provider value={{ open, onClosed: () => () => {} }}>
        <Workout />
      </ChatSheetContext.Provider>,
      { route: "/workout/" },
    );
    expect(screen.getByRole("heading", { level: 1, name: copy.workout.title })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.workout.back })).toHaveAttribute("href", "/more/");
    expect(await screen.findByText(copy.workout.planEmpty)).toBeInTheDocument();
    expect(screen.getByText(copy.workout.logsEmpty)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: copy.workout.talk }));
    expect(open).toHaveBeenCalledWith({ agent: "mate" });
  });

  it("plan sessions and weekdays render", async () => {
    serve();
    renderWithProviders(<Workout />, { route: "/workout/" });
    expect(await screen.findByRole("heading", { name: copy.workout.planHeading })).toBeInTheDocument();
    expect(screen.getByText("주 2번 집 운동")).toBeInTheDocument();
    const lower = screen.getByRole("button", { name: copy.workout.expandLabel("하체") });
    expect(lower).toHaveTextContent("월·목");
    expect(screen.getByRole("button", { name: copy.workout.expandLabel("상체") })).not.toHaveTextContent("·");
    expect(screen.queryByText("고블릿 스쿼트")).toBeNull();
    await userEvent.click(lower);
    expect(screen.getByText("고블릿 스쿼트")).toBeInTheDocument();
    expect(screen.getByText(/8-10/)).toBeInTheDocument();
    expect(screen.queryByText(copy.workout.planEmpty)).toBeNull();
  });

  it("log expands to items", async () => {
    serve();
    renderWithProviders(<Workout />, { route: "/workout/" });
    const row = await screen.findByRole("button", { name: copy.workout.expandLabel("하체 10-30") });
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(row).toHaveTextContent("10-30");
    expect(row).toHaveTextContent(copy.workout.sessionItems(2));
    expect(screen.queryByText("스쿼트")).toBeNull();
    await userEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("스쿼트")).toBeInTheDocument();
    expect(screen.getByText(/60kg/)).toBeInTheDocument();
    expect(screen.getByText(/2.5km/)).toBeInTheDocument();
  });

  it("log delete asks then applies", async () => {
    serve(() => (gone ? { ...DATA, logs: DATA.logs.slice(1) } : DATA));
    const bodies = actions((b) =>
      b.confirm_token
        ? applied(90, "✓ 운동 기록 지움: 하체")
        : { status: "needs_confirm", confirm_token: "tok-1", summary: "운동 기록 '하체'(10-30)를 지울까요?", expires_at: "2026-10-31T00:00:00Z" },
    );
    renderWithProviders(<Workout />, { route: "/workout/" });
    await screen.findByRole("button", { name: copy.workout.expandLabel("하체 10-30") });
    await userEvent.click(screen.getByRole("button", { name: copy.today.moreActions("하체") }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.workout.delete }));
    const sheet = await screen.findByText("운동 기록 '하체'(10-30)를 지울까요?");
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ action: "delete_workout_log", args: { id: 11 }, confirm_token: null });
    await userEvent.click(within(sheet.closest("[role=dialog]") as HTMLElement).getByRole("button", { name: copy.workout.delete }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "delete_workout_log", args: { id: 11 }, confirm_token: "tok-1" });
    await waitFor(() => expect(screen.queryByText("운동 기록 '하체'(10-30)를 지울까요?")).toBeNull());
    await waitFor(() => expect(screen.queryByRole("button", { name: copy.workout.expandLabel("하체 10-30") })).toBeNull());
  });

  it("keeping the log in the sheet sends nothing more", async () => {
    serve();
    const bodies = actions(() => ({ status: "needs_confirm", confirm_token: "tok-1", summary: "지울까요?", expires_at: "x" }));
    renderWithProviders(<Workout />, { route: "/workout/" });
    await screen.findByRole("button", { name: copy.workout.expandLabel("하체 10-30") });
    await userEvent.click(screen.getByRole("button", { name: copy.today.moreActions("하체") }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.workout.delete }));
    await userEvent.click(await screen.findByRole("button", { name: copy.workout.keep }));
    expect(bodies).toHaveLength(1);
    await waitFor(() => expect(screen.queryByText("지울까요?")).toBeNull());
  });

  it("note delete shows undo toast", async () => {
    serve(() => (gone ? { ...DATA, notes: DATA.notes.slice(1) } : DATA));
    const bodies = actions(() => applied(91, "✓ 몸 메모 지움"));
    renderWithProviders(<Workout />, { route: "/workout/" });
    expect(await screen.findByText(copy.workout.notesHint)).toBeInTheDocument();
    expect(screen.getByText(copy.workout.noteKinds.equipment)).toBeInTheDocument();
    expect(screen.getByText(copy.workout.noteKinds.injury)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: copy.today.moreActions("집에 덤벨 20kg까지") }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.workout.delete }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "drop_body_note", args: { id: 21 } });
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("✓ 몸 메모 지움");
    expect(within(toast).getByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("집에 덤벨 20kg까지")).toBeNull());
  });

  it("offline shows snapshot", async () => {
    await seedSnap("workout", DATA);
    server.use(http.get(`${BASE}/workout`, () => HttpResponse.error()));
    renderWithProviders(<Workout />, { route: "/workout/", conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(await screen.findByText("주 2번 집 운동")).toBeInTheDocument();
    expect(screen.getByText("집에 덤벨 20kg까지")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.workout.expandLabel("하체 10-30") })).toBeInTheDocument();
    // read only: nothing to swipe or delete
    expect(screen.queryByRole("button", { name: copy.today.moreActions("하체") })).toBeNull();
  });

  it("no calendar or counts", async () => {
    serve();
    const { container } = renderWithProviders(<Workout />, { route: "/workout/" });
    await screen.findByText("주 2번 집 운동");
    await userEvent.click(screen.getByRole("button", { name: copy.workout.expandLabel("하체 10-30") }));
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\d+\s*회/);
    expect(text).not.toContain("%");
    for (const word of ["연속", "스트릭", "달성률"]) expect(text).not.toContain(word);
    expect(container.querySelector("table, [role=grid], [role=gridcell]")).toBeNull();
    expect(screen.queryAllByRole("progressbar")).toHaveLength(0);
  });
});

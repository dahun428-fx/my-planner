import "fake-indexeddb/auto";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Drafts, Priorities, Today as TodayData, Week } from "../api/types.gen";
import { copy } from "../lib/copy";
import { notifyDataChanged } from "../lib/push";
import draftsJson from "../test/fixtures/drafts.json";
import monthJson from "../test/fixtures/priorities-month.json";
import quarterJson from "../test/fixtures/priorities-quarter.json";
import todayJson from "../test/fixtures/today.json";
import weekJson from "../test/fixtures/week.json";
import yearJson from "../test/fixtures/priorities-year.json";
import { renderWithProviders, seedSnap } from "../test/render";
import { BASE, server } from "../test/server";
import { Todos } from "./Todos";

const today = todayJson as TodayData;
const week = weekJson as Week;
const drafts = draftsJson as Drafts;
const byCadence: Record<string, Priorities> = {
  month: monthJson as Priorities,
  quarter: quarterJson as Priorities,
  year: yearJson as Priorities,
};

afterEach(async () => {
  vi.useRealTimers();
  await clear();
});

const notFound = () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 });

function serve(over: { drafts?: () => Response; priorities?: () => Response } = {}) {
  const cadences: string[] = [];
  server.use(
    http.get(`${BASE}/today`, () => HttpResponse.json(today)),
    http.get(`${BASE}/week`, () => HttpResponse.json(week)),
    http.get(`${BASE}/drafts`, () => (over.drafts ? over.drafts() : HttpResponse.json(drafts))),
    http.get(`${BASE}/priorities`, ({ request }) => {
      const c = new URL(request.url).searchParams.get("cadence") ?? "";
      cadences.push(c);
      return over.priorities ? over.priorities() : HttpResponse.json(byCadence[c]);
    }),
  );
  return cadences;
}

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

const applied = () => HttpResponse.json({ status: "applied", activity_id: 900, undo_id: 900, result: {}, confirmation: "✓ 처리했어요" }); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
const needsConfirm = () =>
  HttpResponse.json({ status: "needs_confirm", confirm_token: "ct-1", summary: "이번 주 우선순위예요. 빼면 순서가 바뀌어요.", expires_at: "2026-10-24T09:00:00Z" });

const tabOf = (name: string) => screen.getByRole("radio", { name });

describe("Todos", () => {
  it("more button at the top right goes to /more/ (spec 9.1)", async () => {
    renderWithProviders(<Todos />);
    expect(await screen.findByRole("link", { name: "더보기" })).toHaveAttribute("href", "/more/");
  });

  it("writes and the launcher go off together when the BE stops taking writes", async () => {
    serve();
    actions(() => HttpResponse.json({ error: { code: "too_many_auth_failures", message: "x" } }, { status: 429 }));
    renderWithProviders(<Todos tab="week" />);
    const add = await screen.findByRole("button", { name: copy.todos.add });
    await waitFor(() => expect(add).toBeEnabled());
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeEnabled());
    fireEvent.click(screen.getByRole("checkbox", { name: copy.today.checkLabel("장보기") }));
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeDisabled(), { timeout: 3000 }); // CI 부하에서 429 → 쓰기 멈춤 전파가 1초를 넘은 적이 있다
    expect(add).toBeDisabled();
    expect(screen.queryByRole("checkbox", { name: copy.today.checkLabel("장보기") })).toBeNull(); // a read-only row has no check
  });

  it("chat launcher: on when connected, off with the reason when not", async () => {
    serve();
    const { unmount } = renderWithProviders(<Todos tab="week" />);
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeEnabled());
    unmount();
    const off = renderWithProviders(<Todos tab="week" />, { conn: "offline" });
    await waitFor(() => expect(screen.getByRole("button", { name: copy.offline.chatLater })).toBeDisabled());
    off.unmount();
    renderWithProviders(<Todos tab="week" />, { conn: "unauthorized" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: copy.chat.launcher })).toHaveAccessibleDescription(copy.chat.launcherBlocked.unauthorized),
    );
    expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeDisabled();
  });

  it("defaults to week tab", async () => {
    serve();
    renderWithProviders(<Todos />);
    expect(tabOf(copy.todos.periods.week)).toHaveAttribute("aria-checked", "true");
    expect(await screen.findByText("장보기")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: copy.todos.title })).toBeInTheDocument();
  });

  it("tab switches with query", async () => {
    serve();
    const { router } = renderWithProviders(<Todos tab="week" />);
    await screen.findByText("장보기");
    await userEvent.setup().click(await screen.findByRole("radio", { name: copy.todos.periods.quarter }));
    expect(router.replace).toHaveBeenCalledWith("/todos/?tab=quarter");
  });

  it("week shows priorities without counts", async () => {
    serve();
    const { container } = renderWithProviders(<Todos tab="week" />);
    await screen.findByText("장보기");
    expect(screen.getByRole("heading", { name: copy.todos.weekPriorities })).toBeInTheDocument();
    // The finished one shows as a checked box (also on its day), never as a count.
    for (const box of screen.getAllByRole("checkbox", { name: copy.today.doneLabel("주간 계획 세우기") })) expect(box).toHaveAttribute("aria-checked", "true");
    expect(container.textContent).not.toMatch(/\d\s*\/\s*\d/);
    expect(container.textContent).not.toContain("%");
  });

  it("week lists the to-dos with no date under their own heading", async () => {
    serve();
    renderWithProviders(<Todos tab="week" />);
    const heading = await screen.findByRole("heading", { name: copy.todos.undated });
    const group = heading.closest("section") ?? heading.parentElement!.parentElement!;
    expect(within(group).getByText("언젠가 읽을 책 고르기")).toBeInTheDocument();
  });

  it("week keeps a checked to-do with no date, struck through after the open ones", async () => {
    serve();
    const [open] = week.undated ?? [];
    const done = { ...open, id: 9901, title: "어제 끝낸 정리", status: "done" as const, completed_at: "2026-10-24T01:00:00Z" };
    server.use(http.get(`${BASE}/week`, () => HttpResponse.json({ ...week, undated: [done, open] })));
    renderWithProviders(<Todos tab="week" />);
    const heading = await screen.findByRole("heading", { name: copy.todos.undated });
    const group = heading.closest("section") ?? heading.parentElement!.parentElement!;
    const boxes = within(group).getAllByRole("checkbox");
    expect(boxes.map((b) => b.getAttribute("aria-checked"))).toEqual(["false", "true"]);
    expect(boxes[1]).toHaveAccessibleName(copy.today.doneLabel("어제 끝낸 정리"));
  });

  it("month shows the to-dos planned in it with their day (10/28 is not only a priority)", async () => {
    serve();
    renderWithProviders(<Todos tab="month" />);
    const heading = await screen.findByRole("heading", { name: copy.todos.periodTodos(copy.todos.periods.month) });
    const group = heading.closest("section") ?? heading.parentElement!.parentElement!;
    expect(within(group).getByText("분기 보고서 초안")).toBeInTheDocument();
    expect(within(group).getByText(copy.dateParts.monthDay(10, 28))).toBeInTheDocument();
  });

  it("an answer that changed something reads the lists again at once, sheet still open", async () => {
    let weekHits = 0;
    serve();
    server.use(http.get(`${BASE}/week`, () => {
      weekHits += 1;
      return HttpResponse.json(week);
    }));
    renderWithProviders(<Todos tab="week" />);
    await screen.findByText("장보기");
    const before = weekHits;
    notifyDataChanged();
    await waitFor(() => expect(weekHits).toBe(before + 1));
  });

  it("empty day collapsed", async () => {
    serve();
    renderWithProviders(<Todos tab="week" />);
    await screen.findByText("장보기");
    // 화 has nothing: one line, no group heading for it.
    expect(screen.getByText(copy.todos.emptyDay("화"))).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: new RegExp("^화 ") })).toBeNull();
    expect(screen.getByRole("heading", { name: copy.todos.dayHeading("토", 10, 24, true) })).toBeInTheDocument();
  });

  it.each(["month", "quarter", "year"] as const)("%s calls priorities with cadence", async (cadence) => {
    const cadences = serve();
    renderWithProviders(<Todos tab={cadence} />);
    expect(await screen.findByText(byCadence[cadence].items[0].title)).toBeInTheDocument();
    expect(cadences).toContain(cadence);
  });

  it("drafts confirm one and all", async () => {
    serve();
    const bodies = actions(() => applied());
    renderWithProviders(<Todos tab="week" />);
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { name: copy.todos.drafts(2) })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: copy.todos.confirmLabel("치과 예약하기") }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "confirm_tasks", args: { ids: [51] } });
    await user.click(screen.getByRole("button", { name: copy.todos.confirmAll }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "confirm_tasks", args: { ids: [51, 52] } });
    await user.click(screen.getByRole("button", { name: copy.todos.dropLabel("여름 옷 정리") }));
    await waitFor(() => expect(bodies).toHaveLength(3));
    expect(bodies[2]).toMatchObject({ action: "drop_task", args: { id: 52 } });
  });

  it("no bulk confirm for a single draft", async () => {
    serve({ drafts: () => HttpResponse.json({ items: [drafts.items[0]] }) });
    renderWithProviders(<Todos tab="week" />);
    await screen.findByRole("heading", { name: copy.todos.drafts(1) });
    expect(screen.queryByRole("button", { name: copy.todos.confirmAll })).toBeNull();
  });

  it("hides month tab and drafts on 404", async () => {
    serve({ drafts: notFound, priorities: notFound });
    renderWithProviders(<Todos tab="week" />);
    await screen.findByText("장보기");
    await waitFor(() => expect(screen.queryByRole("radio", { name: copy.todos.periods.month })).toBeNull());
    expect(screen.queryByRole("radio", { name: copy.todos.periods.quarter })).toBeNull();
    expect(screen.queryByRole("radio", { name: copy.todos.periods.year })).toBeNull();
    expect(screen.getByRole("radio", { name: copy.todos.periods.week })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: new RegExp("^초안") })).toBeNull();
  });

  it("swipe tomorrow and drop with confirm", async () => {
    serve();
    // 01:30 KST on the 25th: the device says the 25th, the BE's logical day is still the 24th.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-25T01:30:00+09:00"));
    const bodies = actions((b) => (b.action === "drop_task" && !b.confirm_token ? needsConfirm() : applied()));
    renderWithProviders(<Todos tab="week" />);
    fireEvent.contextMenu(await screen.findByText("장보기"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "move_task", args: { id: 34, planned_for: "2026-10-25" } });

    fireEvent.contextMenu(screen.getByText("책 열 쪽 읽기"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.drop }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    const none = bodies[1];
    expect(none).toMatchObject({ action: "drop_task", args: { id: 35 } });
    expect(none.confirm_token ?? null).toBeNull();
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText("이번 주 우선순위예요. 빼면 순서가 바뀌어요.")).toBeInTheDocument();
    await userEvent.setup().click(within(sheet).getByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(3));
    expect(bodies[2]).toMatchObject({ action: "drop_task", args: { id: 35 }, confirm_token: "ct-1" });
    expect(bodies[2].client_msg_id).not.toBe(bodies[1].client_msg_id);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("confirm expired copy on 409", async () => {
    serve();
    actions((b) => (b.confirm_token ? HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 }) : needsConfirm()));
    renderWithProviders(<Todos tab="week" />);
    fireEvent.contextMenu(await screen.findByText("책 열 쪽 읽기"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.drop }));
    const sheet = await screen.findByRole("dialog");
    await userEvent.setup().click(within(sheet).getByRole("button", { name: copy.todos.change }));
    expect(await screen.findByText(copy.todos.confirmExpired)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a conflict on tomorrow says it failed", async () => {
    serve();
    actions(() => HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 }));
    renderWithProviders(<Todos tab="week" />);
    fireEvent.contextMenu(await screen.findByText("장보기"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
  });

  it("tomorrow on scheduled todo opens confirm sheet", async () => {
    // SP6 8 (BE-2): Todos' "내일로" asks first for a to-do with a time.
    const SUMMARY = "날짜를 옮겨요: 장보기 → 10월 25일 (일)";
    serve();
    const bodies = actions((b) => (b.confirm_token ? applied() : HttpResponse.json({ status: "needs_confirm", confirm_token: "ct-9", summary: SUMMARY, expires_at: "2026-10-24T09:00:00Z" })));
    renderWithProviders(<Todos tab="week" />);
    const user = userEvent.setup();
    fireEvent.contextMenu(await screen.findByText("장보기"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText(SUMMARY)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: copy.todos.change }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "move_task", args: { id: 34, planned_for: "2026-10-25" }, confirm_token: "ct-9" });
    expect(bodies[1].client_msg_id).not.toBe(bodies[0].client_msg_id);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.contextMenu(screen.getByText("장보기"));
    fireEvent.click(screen.getByRole("button", { name: copy.todos.tomorrow }));
    const again = await screen.findByRole("dialog");
    await waitFor(() => expect(within(again).getByText(SUMMARY)).toBeInTheDocument());
    await user.click(within(again).getByRole("button", { name: copy.todos.keep }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(bodies).toHaveLength(3);
  });

  it("change date never asks first", async () => {
    // SP9 5.4: to-dos have no time, so EditTodoSheet's "날짜 바꾸기" sends move_task once, with no confirm token.
    serve();
    const bodies = actions(() => applied());
    renderWithProviders(<Todos tab="week" />);
    const user = userEvent.setup();
    fireEvent.contextMenu(await screen.findByText("장보기"));
    await user.click(screen.getByRole("button", { name: copy.todos.changeDate }));
    fireEvent.change(await screen.findByLabelText(copy.todos.dateLabel), { target: { value: "2026-10-28" } });
    await user.click(screen.getByRole("button", { name: copy.todos.save }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "move_task", args: { id: 34, planned_for: "2026-10-28" } });
    expect(bodies[0].confirm_token ?? null).toBeNull();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("long press edit title and date", async () => {
    serve();
    const bodies = actions(() => applied());
    renderWithProviders(<Todos tab="week" />);
    const user = userEvent.setup();
    fireEvent.contextMenu(await screen.findByText("장보기"));
    await user.click(screen.getByRole("button", { name: copy.todos.changeDate }));
    let dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(copy.todos.dateLabel), { target: { value: "2026-10-27" } });
    await user.click(within(dialog).getByRole("button", { name: copy.todos.save }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "move_task", args: { id: 34, planned_for: "2026-10-27" } });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.contextMenu(screen.getByText("장보기"));
    await user.click(screen.getByRole("button", { name: copy.todos.editTitle }));
    dialog = await screen.findByRole("dialog");
    const field = within(dialog).getByLabelText(copy.todos.titleLabel);
    expect(field).toHaveValue("장보기");
    await user.clear(field);
    await user.type(field, "  마트 장보기 ");
    await user.click(within(dialog).getByRole("button", { name: copy.todos.save }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "update_task", args: { id: 34, title: "마트 장보기" } });
  });

  it("offline week from snapshot, others later", async () => {
    await seedSnap("week", week);
    const first = renderWithProviders(<Todos tab="week" />, { conn: "offline" });
    expect(await screen.findByText("장보기")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.todos.add })).toBeDisabled();
    expect(screen.queryByRole("checkbox")).toBeNull();
    first.unmount();
    renderWithProviders(<Todos tab="month" />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.later)).toBeInTheDocument();
    expect(screen.queryByText("이사 견적 받기")).toBeNull();
  });

  it("day tab shows today's todos", async () => {
    serve();
    renderWithProviders(<Todos tab="day" />);
    expect(await screen.findByText("운동 30분")).toBeInTheDocument();
  });

  it("double tap on 확정 sends one request", async () => {
    serve();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const bodies = actions(async () => {
      await gate;
      return applied();
    });
    renderWithProviders(<Todos tab="week" />);
    const btn = await screen.findByRole("button", { name: copy.todos.confirmLabel("치과 예약하기") });
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.click(screen.getByRole("button", { name: copy.todos.confirmAll }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    release();
    await screen.findByText("✓ 처리했어요"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(bodies).toHaveLength(1);
  });

  it("bulk confirm sits in the drafts heading row, right of the heading and above the rows", async () => {
    serve();
    renderWithProviders(<Todos tab="week" />);
    const bulk = await screen.findByRole("button", { name: copy.todos.confirmAll });
    const heading = screen.getByRole("heading", { name: copy.todos.drafts(2) });
    expect(heading.parentElement).toContainElement(bulk);
    expect(Boolean(heading.compareDocumentPosition(bulk) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    const firstRow = screen.getByText("치과 예약하기");
    expect(Boolean(bulk.compareDocumentPosition(firstRow) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  });

  it("a failing /drafts shows a retryable block error", async () => {
    serve({ drafts: () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) });
    renderWithProviders(<Todos tab="week" />);
    expect(await screen.findByText(copy.errors.block("internal"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.errors.retry })).toBeInTheDocument();
  });

  it("a failing /priorities shows its real code", async () => {
    serve({ priorities: () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) });
    renderWithProviders(<Todos tab="quarter" />);
    expect(await screen.findByText(copy.errors.block("internal"))).toBeInTheDocument();
  });

  it("falls back to week in the URL when ranges are hidden", async () => {
    serve({ priorities: notFound });
    const { router } = renderWithProviders(<Todos tab="quarter" />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/todos/?tab=week"));
  });

  it("probes priorities once per connection", async () => {
    const cadences = serve();
    const { router } = renderWithProviders(<Todos tab="week" />);
    await screen.findByText("장보기");
    await waitFor(() => expect(cadences.length).toBeGreaterThan(0));
    expect(cadences).toEqual(["month"]);
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("keyboard user edits a title from the 더 보기 button", async () => {
    serve();
    const bodies = actions(() => applied());
    renderWithProviders(<Todos tab="week" />);
    const user = userEvent.setup();
    const more = await screen.findByRole("button", { name: copy.today.moreActions("장보기") });
    more.focus();
    await user.keyboard("{Enter}");
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.todos.editTitle }));
    const dialog = await screen.findByRole("dialog");
    const field = within(dialog).getByLabelText(copy.todos.titleLabel);
    await user.clear(field);
    await user.type(field, "마트");
    await user.click(within(dialog).getByRole("button", { name: copy.todos.save }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "update_task", args: { id: 34, title: "마트" } });
  });
});

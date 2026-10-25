import "fake-indexeddb/auto";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EventItem } from "../api/types.gen";
import { copy } from "../lib/copy";
import SchedulePage from "../pages/schedule";
import { ev } from "../test/events";
import { RouterContext } from "next/dist/shared/lib/router-context.shared-runtime";
import { mockRouter, renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { Schedule } from "./Schedule";

// 2026-10-26(월) 10:00 서울. 그 주는 10/26(월)~11/01(일).
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-26T10:00:00+09:00"));
});
afterEach(async () => {
  vi.useRealTimers();
  await clear();
});

const WEEK = [
  ev(1, "2026-10-27", "14:00", { title: "치과", area: "health" }),
  ev(2, "2026-10-27", null, { title: "엄마 생신" }),
  ev(3, "2026-10-27", "09:30", { title: "팀 회의", repeat: "weekly", origin: "chat" }),
  ev(4, "2026-10-30", "19:00", { title: "저녁 약속" }),
];

// `GET /events?start&end`: 그 기간 안의 것만. 물은 기간을 적어 둔다.
function serve(items: EventItem[] = WEEK) {
  const asked: string[] = [];
  server.use(
    http.get(`${BASE}/events`, ({ request }) => {
      const u = new URL(request.url);
      const start = u.searchParams.get("start") ?? "";
      const end = u.searchParams.get("end") ?? "";
      asked.push(`${start}..${end}`);
      return HttpResponse.json({ start, end, items: items.filter((e) => e.date >= start && e.date <= end) });
    }),
  );
  return asked;
}

const strip = () => screen.getByRole("group", { name: copy.schedule.week });
// 일정 있는 날은 읽는 이름에 "일정 있음"이 붙는다(점은 눈으로만 보이므로).
const dayButton = (m: number, d: number, w: string) =>
  within(strip()).getByRole("button", { name: new RegExp(`^${copy.parts.dayLabel(m, d, w).replace(/[()]/g, "\\$&")}`) });

describe("Schedule (spec 9.2)", () => {
  it("opens on today: the month as the large title, the week strip Monday to Sunday, today marked", async () => {
    const asked = serve();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    expect(await screen.findByRole("heading", { level: 1, name: copy.schedule.month(10) })).toBeInTheDocument();
    const days = within(strip()).getAllByRole("button");
    expect(days).toHaveLength(7);
    expect(days[0]).toHaveAccessibleName(copy.parts.dayLabel(10, 26, "월"));
    expect(days[6]).toHaveAccessibleName(copy.parts.dayLabel(11, 1, "일"));
    expect(days[0]).toHaveAttribute("aria-current", "date");
    expect(days[0]).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(asked).toContain("2026-10-26..2026-11-01"));
    expect(new Set(asked)).toEqual(new Set(["2026-10-26..2026-11-01"])); // the week only, never more
  });

  it("a dot only under the days that have events (no count)", async () => {
    serve();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    await waitFor(() => expect(dayButton(10, 27, "화")).toHaveAttribute("data-events", "true"));
    expect(dayButton(10, 30, "금")).toHaveAttribute("data-events", "true");
    // 화면 읽기에도: 점이 있는 날만 이름에 "일정 있음"
    expect(dayButton(10, 27, "화")).toHaveAccessibleName(copy.schedule.hasEvents(copy.parts.dayLabel(10, 27, "화")));
    for (const [d, w] of [[26, "월"], [28, "수"], [29, "목"], [31, "토"]] as const) {
      expect(dayButton(10, d, w)).not.toHaveAttribute("data-events");
      expect(dayButton(10, d, w)).toHaveAccessibleName(copy.parts.dayLabel(10, d, w));
    }
    expect(within(strip()).queryByText("3")).not.toBeInTheDocument();
  });

  it("an empty day says so", async () => {
    serve();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    expect(await screen.findByText(copy.schedule.empty)).toBeInTheDocument();
  });

  it("a day's list: all-day first, then by time; time, title, area dot, repeat and 비서 marks", async () => {
    serve();
    const user = userEvent.setup();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    await waitFor(() => expect(dayButton(10, 27, "화")).toHaveAttribute("data-events", "true"));
    await user.click(dayButton(10, 27, "화"));
    const list = await screen.findByRole("list", { name: copy.parts.dayLabel(10, 27, "화") });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("엄마 생신");
    expect(rows[1]).toHaveTextContent("팀 회의");
    expect(rows[2]).toHaveTextContent("치과");
    expect(rows[0]).toHaveTextContent(copy.schedule.allDay);
    expect(rows[1]).toHaveTextContent("09:30");
    expect(within(rows[1]).getByRole("img", { name: copy.schedule.repeating })).toBeInTheDocument();
    expect(within(rows[2]).queryByRole("img", { name: copy.schedule.repeating })).not.toBeInTheDocument();
    expect(rows[1]).toHaveTextContent(copy.schedule.bySecretary);
    expect(rows[2]).toHaveTextContent("14:00");
    expect(rows[2].querySelector('.area-dot[data-area="health"]')).not.toBeNull();
    expect(rows[2]).not.toHaveTextContent(copy.schedule.bySecretary);
  });

  it("?date= opens that day and its week (a push opens /schedule/?date=)", async () => {
    const asked = serve();
    renderWithProviders(<Schedule />, { route: "/schedule/?date=2026-11-04" });
    expect(await screen.findByRole("heading", { level: 1, name: copy.schedule.month(11) })).toBeInTheDocument();
    expect(dayButton(11, 4, "수")).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(asked).toContain("2026-11-02..2026-11-08"));
  });

  it("an address date that is not a day opens today", async () => {
    serve();
    renderWithProviders(<Schedule />, { route: "/schedule/?date=2026-02-30" });
    expect(await screen.findByRole("heading", { level: 1, name: copy.schedule.month(10) })).toBeInTheDocument();
    expect(dayButton(10, 26, "월")).toHaveAttribute("aria-pressed", "true");
  });

  it("picking a day keeps it in the address", async () => {
    serve();
    const user = userEvent.setup();
    const { router } = renderWithProviders(<Schedule />, { route: "/schedule/" });
    await user.click(await screen.findByRole("button", { name: copy.parts.dayLabel(10, 29, "목") }));
    expect(router.replace).toHaveBeenLastCalledWith("/schedule/?date=2026-10-29", undefined, { shallow: true, scroll: false });
  });

  it("swipe left is the next week, right the week before", async () => {
    const asked = serve();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    await screen.findByRole("heading", { level: 1, name: copy.schedule.month(10) });
    const swipe = (dx: number) => {
      fireEvent.pointerDown(strip(), { pointerId: 1, clientX: 200, clientY: 10, pointerType: "touch" });
      fireEvent.pointerUp(strip(), { pointerId: 1, clientX: 200 + dx, clientY: 14, pointerType: "touch" });
    };
    swipe(-120);
    expect(await screen.findByRole("button", { name: copy.parts.dayLabel(11, 2, "월") })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { level: 1, name: copy.schedule.month(11) })).toBeInTheDocument();
    await waitFor(() => expect(asked).toContain("2026-11-02..2026-11-08"));
    swipe(120);
    swipe(120);
    expect(await screen.findByRole("button", { name: copy.parts.dayLabel(10, 19, "월") })).toHaveAttribute("aria-pressed", "true");
    // 조금 밀거나 세로로 민 것은 주를 바꾸지 않는다.
    fireEvent.pointerDown(strip(), { pointerId: 2, clientX: 200, clientY: 10, pointerType: "touch" });
    fireEvent.pointerUp(strip(), { pointerId: 2, clientX: 180, clientY: 200, pointerType: "touch" });
    expect(screen.getByRole("button", { name: copy.parts.dayLabel(10, 19, "월") })).toHaveAttribute("aria-pressed", "true");
  });

  it("tapping the title opens the month; picking a day goes to its week and folds it", async () => {
    serve();
    const user = userEvent.setup();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    const toggle = await screen.findByRole("button", { name: copy.schedule.month(10) });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const month = screen.getByRole("group", { name: copy.schedule.monthOf(2026, 10) });
    await user.click(within(month).getByRole("button", { name: copy.parts.dayLabel(10, 14, "수") }));
    expect(screen.queryByRole("group", { name: copy.schedule.monthOf(2026, 10) })).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(dayButton(10, 14, "수")).toHaveAttribute("aria-pressed", "true");
    // 다시 누르면 접힌다
    await user.click(toggle);
    await user.click(toggle);
    expect(screen.queryByRole("group", { name: copy.schedule.monthOf(2026, 10) })).not.toBeInTheDocument();
  });

  it("the month calendar moves by month", async () => {
    serve();
    const user = userEvent.setup();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    await user.click(await screen.findByRole("button", { name: copy.schedule.month(10) }));
    await user.click(screen.getByRole("button", { name: copy.schedule.nextMonth }));
    const month = screen.getByRole("group", { name: copy.schedule.monthOf(2026, 11) });
    await user.click(within(month).getByRole("button", { name: copy.parts.dayLabel(11, 30, "월") }));
    expect(screen.getByRole("heading", { level: 1, name: copy.schedule.month(11) })).toBeInTheDocument();
  });

  it("swipe a repeating row left: 건너뛰기 skips that day only, with undo", async () => {
    serve();
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.post(`${BASE}/actions`, async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ status: "applied", activity_id: 70, undo_id: 70, result: {}, confirmation: "✓ 이번만 건너뜀: 팀 회의 (10/27)" });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Schedule />, { route: "/schedule/?date=2026-10-27" });
    const list = await screen.findByRole("list", { name: copy.parts.dayLabel(10, 27, "화") });
    await user.click(within(list).getByRole("button", { name: copy.today.moreActions("팀 회의") }));
    await user.click(await screen.findByRole("button", { name: copy.schedule.skip }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "delete_event", args: { id: 3, scope: "one", date: "2026-10-27" } });
    expect(await screen.findByRole("button", { name: copy.chat.undo })).toBeInTheDocument();
  });

  it("a one-off row offers 지우기", async () => {
    serve();
    const user = userEvent.setup();
    renderWithProviders(<Schedule />, { route: "/schedule/?date=2026-10-27" });
    const list = await screen.findByRole("list", { name: copy.parts.dayLabel(10, 27, "화") });
    await user.click(within(list).getByRole("button", { name: copy.today.moreActions("치과") }));
    expect(await screen.findByRole("button", { name: copy.schedule.delete })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.schedule.skip })).not.toBeInTheDocument();
  });

  it("offline: the notice, no +, no swipe menu", async () => {
    renderWithProviders(<Schedule />, { route: "/schedule/", conn: "offline" });
    expect(await screen.findByRole("button", { name: copy.offline.reconnect })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.schedule.add })).toBeDisabled();
  });

  it("waits for the address before the first read: a push to ?date= asks that week only", async () => {
    const asked = serve();
    const notReady = { ...mockRouter("/schedule/"), isReady: false, query: {} };
    const { rerender } = renderWithProviders(
      <RouterContext.Provider value={notReady}>
        <SchedulePage />
      </RouterContext.Provider>,
      { route: "/schedule/?date=2026-11-04" },
    );
    await screen.findByRole("navigation", { name: copy.tabs.navLabel });
    await new Promise((r) => setTimeout(r, 50));
    expect(asked).toEqual([]);
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    rerender(
      <RouterContext.Provider value={mockRouter("/schedule/?date=2026-11-04")}>
        <SchedulePage />
      </RouterContext.Provider>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: copy.schedule.month(11) })).toBeInTheDocument();
    await waitFor(() => expect(asked).toContain("2026-11-02..2026-11-08"));
    expect(asked).not.toContain("2026-10-26..2026-11-01");
  });

  it("the month calendar steps with the chevron icons", async () => {
    serve();
    const user = userEvent.setup();
    renderWithProviders(<Schedule />, { route: "/schedule/" });
    await user.click(await screen.findByRole("button", { name: copy.schedule.month(10) }));
    const prev = screen.getByRole("button", { name: copy.schedule.prevMonth });
    const next = screen.getByRole("button", { name: copy.schedule.nextMonth });
    expect(prev.querySelector("svg path")?.getAttribute("d")).toBe(next.querySelector("svg path")?.getAttribute("d"));
    expect(prev).not.toHaveTextContent("‹");
  });

  it("the page marks the schedule tab", async () => {
    serve();
    renderWithProviders(<SchedulePage />, { route: "/schedule/" });
    const nav = screen.getByRole("navigation", { name: copy.tabs.navLabel });
    expect(within(nav).getByRole("link", { name: copy.tabs.schedule })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("link", { name: "더보기" })).toHaveAttribute("href", "/more/");
  });
});

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MemoItem, MemoList } from "../api/types.gen";
import { copy } from "../lib/copy";
import MemosPage from "../pages/memos";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { Memos } from "./Memos";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-25T15:00:00+09:00"));
});
afterEach(() => {
  vi.useRealTimers();
});

const item = (o: Partial<MemoItem>): MemoItem => ({
  id: 1,
  title: "제목",
  preview: "",
  area: null,
  pinned: false,
  origin: "user",
  updated_at: "2026-10-25T05:02:00Z",
  ...o,
});

// As the BE sends the first page: every pinned memo first, then the rest newest first (6.4).
const LIST: MemoItem[] = [
  item({ id: 3, title: "고정 메모", pinned: true, updated_at: "2026-10-20T01:00:00Z" }),
  item({ id: 1, title: "읽을 책", preview: "사피엔스", area: "learning", updated_at: "2026-10-25T05:02:00Z" }), // 오늘 14:02
  item({ id: 2, title: "장보기", origin: "chat", updated_at: "2026-10-24T03:00:00Z" }), // 어제
  item({ id: 4, title: "옛 메모", updated_at: "2026-10-21T03:00:00Z" }), // 10월 21일
];

interface Seen {
  q: string | null;
  at: number;
}

function serve(answer: (q: string | null) => MemoList = () => ({ items: LIST, next_before: null })) {
  const seen: Seen[] = [];
  server.use(
    http.get(`${BASE}/memos`, ({ request }) => {
      const q = new URL(request.url).searchParams.get("q");
      seen.push({ q, at: performance.now() });
      return HttpResponse.json(answer(q));
    }),
  );
  return seen;
}

function actions(confirmation: string) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ status: "applied", activity_id: 900, undo_id: 900, result: {}, confirmation });
    }),
  );
  return bodies;
}

const rowLink = (title: string) => screen.getByRole("link", { name: new RegExp(title) });

describe("Memos (spec 9.4)", () => {
  it("pinned group first, then the rest; each row has the title, the day it changed, the preview and the area dot", async () => {
    serve();
    renderWithProviders(<Memos />, { route: "/memos/" });
    expect(screen.getByRole("heading", { level: 1, name: "메모" })).toBeInTheDocument();
    await screen.findByText("읽을 책");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["고정됨", "메모"]);
    const [pinned, rest] = screen.getAllByRole("heading", { level: 2 }).map((h) => h.closest("section") as HTMLElement);
    expect(within(pinned).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/memos/view/?id=3"]);
    expect(within(rest).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "/memos/view/?id=1",
      "/memos/view/?id=2",
      "/memos/view/?id=4",
    ]);
    expect(rowLink("읽을 책")).toHaveTextContent("오늘 14:02");
    expect(rowLink("읽을 책")).toHaveTextContent("사피엔스");
    expect(rowLink("장보기")).toHaveTextContent("어제");
    expect(rowLink("옛 메모")).toHaveTextContent("10월 21일");
    // The area as a small dot (DESIGN.md), named for screen readers.
    const dot = rowLink("읽을 책").querySelector("[data-area]");
    expect(dot).toHaveAttribute("data-area", "learning");
    expect(dot).toHaveClass("area-dot");
    expect(rowLink("읽을 책")).toHaveTextContent(copy.areas.learning);
  });

  it("no pinned memos: one list, no group headings", async () => {
    serve(() => ({ items: LIST.filter((m) => !m.pinned), next_before: null }));
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("읽을 책");
    expect(screen.queryAllByRole("heading", { level: 2 })).toEqual([]);
  });

  it("a memo the secretary made carries the 비서 mark", async () => {
    serve();
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("장보기");
    expect(within(rowLink("장보기")).getByText(copy.memos.bySecretary)).toBeInTheDocument();
    expect(within(rowLink("읽을 책")).queryByText(copy.memos.bySecretary)).toBeNull();
  });

  it("search asks GET /memos?q= once, 300ms after the typing stops", async () => {
    const seen = serve((q) => ({ items: q ? LIST.filter((m) => m.preview.includes(q) || m.title.includes(q)) : LIST, next_before: null }));
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("장보기");
    const searches = () => seen.filter((s) => s.q !== null);
    await userEvent.type(screen.getByRole("searchbox", { name: copy.memos.search }), "사피");
    const typedAt = performance.now();
    expect(searches()).toEqual([]); // nothing yet: still inside the 300ms
    await waitFor(() => expect(searches().map((s) => s.q)).toEqual(["사피"]));
    expect(searches()[0].at - typedAt).toBeGreaterThanOrEqual(250);
    await waitFor(() => expect(screen.queryByText("장보기")).toBeNull());
    expect(screen.getByText("읽을 책")).toBeInTheDocument();
  });

  it("empty list says so; a search with no match says that instead", async () => {
    serve(() => ({ items: [], next_before: null }));
    renderWithProviders(<Memos />, { route: "/memos/" });
    expect(await screen.findByText("아직 메모가 없어요. 떠오르는 걸 적어 두세요.")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox", { name: copy.memos.search }), "없는말");
    expect(await screen.findByText(copy.memos.noMatch)).toBeInTheDocument();
    expect(screen.queryByText(copy.memos.empty)).toBeNull();
  });

  it("swipe left: 고정 pins the memo, the toast offers undo, the list is read again", async () => {
    const seen = serve();
    const bodies = actions("✓ 메모를 고정했어요: 읽을 책");
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("읽을 책");
    const reads = seen.length;
    const surface = rowLink("읽을 책").parentElement as HTMLElement;
    fireEvent.pointerDown(surface, { pointerId: 1, clientX: 300, clientY: 10, pointerType: "touch" });
    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 200, clientY: 12, pointerType: "touch" });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 200, clientY: 12, pointerType: "touch" });
    await userEvent.click(await screen.findByRole("button", { name: copy.memos.pin }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "pin_memo", args: { id: 1 } });
    const toast = screen.getByRole("status");
    await waitFor(() => expect(toast).toHaveTextContent("✓ 메모를 고정했어요: 읽을 책"));
    expect(within(toast).getByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
    await waitFor(() => expect(seen.length).toBeGreaterThan(reads));
  });

  it("a pinned memo offers 고정 풀기; 지우기 deletes, and 되돌리기 brings it back and reads the list again", async () => {
    const seen = serve();
    const bodies = actions("✓ 메모를 지웠어요: 고정 메모");
    const undos: string[] = [];
    server.use(
      http.post(`${BASE}/activity/:id/undo`, ({ params }) => {
        undos.push(String(params.id));
        return HttpResponse.json({ status: "undone", confirmation: "되돌렸어요" });
      }),
    );
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("고정 메모");
    const reads = seen.length;
    await userEvent.click(screen.getByRole("button", { name: copy.today.moreActions("고정 메모") }));
    const menu = await screen.findByRole("dialog");
    expect(within(menu).getByRole("button", { name: copy.memos.unpin })).toBeInTheDocument();
    expect(within(menu).queryByRole("button", { name: copy.memos.pin })).toBeNull();
    await userEvent.click(within(menu).getByRole("button", { name: copy.memos.delete }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "delete_memo", args: { id: 3 } });
    await waitFor(() => expect(seen.length).toBeGreaterThan(reads));
    const afterDelete = seen.length;
    await userEvent.click(within(screen.getByRole("status")).getByRole("button", { name: copy.activity.undo }));
    await waitFor(() => expect(undos).toEqual(["900"]));
    await waitFor(() => expect(seen.length).toBeGreaterThan(afterDelete));
  });

  it("a rejected pin (10 pinned) shows the BE's sentence", async () => {
    serve();
    server.use(
      http.post(`${BASE}/actions`, () =>
        HttpResponse.json({ status: "rejected", activity_id: null, error: { code: "too_many_pinned", message: copy.memos.limits.too_many_pinned } }, { status: 422 }),
      ),
    );
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("읽을 책");
    await userEvent.click(screen.getByRole("button", { name: copy.today.moreActions("읽을 책") }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.memos.pin }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.memos.limits.too_many_pinned));
  });

  it("a pin the BE finds already done (no activity) is no failure: no toast, the list is read again", async () => {
    const seen = serve();
    server.use(http.post(`${BASE}/actions`, () => HttpResponse.json({ status: "applied", activity_id: null, result: { id: 1, pinned: true, already: true }, confirmation: null })));
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("읽을 책");
    const reads = seen.length;
    await userEvent.click(screen.getByRole("button", { name: copy.today.moreActions("읽을 책") }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.memos.pin }));
    await waitFor(() => expect(seen.length).toBeGreaterThan(reads));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("+ opens a new memo; the more button sits beside it", async () => {
    serve();
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("읽을 책");
    await waitFor(() => expect(screen.getByRole("link", { name: copy.memos.add })).toHaveAttribute("href", "/memos/view/?new=1"));
    expect(screen.getByRole("link", { name: "더보기" })).toHaveAttribute("href", "/more/");
  });

  it("more pages by next_before", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/memos`, ({ request }) => {
        const before = new URL(request.url).searchParams.get("before");
        seen.push(before);
        return HttpResponse.json(
          before ? { items: [item({ id: 9, title: "더 옛 메모", updated_at: "2026-10-01T03:00:00Z" })], next_before: null } : { items: LIST, next_before: "20261021T030000000000Z_4" },
        );
      }),
    );
    renderWithProviders(<Memos />, { route: "/memos/" });
    await screen.findByText("옛 메모");
    await userEvent.click(screen.getByRole("button", { name: copy.memos.more }));
    expect(await screen.findByText("더 옛 메모")).toBeInTheDocument();
    expect(seen.filter((b) => b !== null)).toEqual(["20261021T030000000000Z_4"]);
    expect(screen.queryByRole("button", { name: copy.memos.more })).toBeNull();
  });

  it("offline: the notice, no swipe menu, no +", async () => {
    serve();
    renderWithProviders(<Memos />, { route: "/memos/", conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: copy.memos.add })).toBeNull();
    expect(screen.getByRole("button", { name: copy.memos.add })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /더 보기$/ })).toBeNull();
  });

  it("a memo with photos shows its first one small at the row's right (SP10 7.1)", async () => {
    serve(() => ({ items: [item({ id: 1, title: "영수증", photos: [{ id: 30, width: 2048, height: 1536 }] }), item({ id: 2, title: "글만" })], next_before: null }));
    const asked: string[] = [];
    server.use(
      http.get(`${BASE}/photos/:id`, ({ request, params }) => {
        asked.push(`${params.id}:${new URL(request.url).searchParams.get("size")}:${request.headers.get("authorization") ? "key" : "none"}`);
        return new HttpResponse(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), { headers: { "Content-Type": "image/jpeg" } });
      }),
    );
    renderWithProviders(<Memos />, { route: "/memos/" });
    const row = (await screen.findByText("영수증")).closest("a")!;
    await waitFor(() => expect(row.querySelector("img")?.getAttribute("src")).toMatch(/^blob:/));
    expect(asked).toEqual(["30:thumb:key"]);
    expect(screen.getByText("글만").closest("a")!.querySelector("[data-photo]")).toBeNull();
  });

  it("the page marks the memos tab", async () => {
    serve();
    renderWithProviders(<MemosPage />, { route: "/memos/" });
    const nav = screen.getByRole("navigation", { name: copy.tabs.navLabel });
    expect(within(nav).getByRole("link", { name: copy.tabs.memos })).toHaveAttribute("aria-current", "page");
    await screen.findByText("읽을 책");
  });
});

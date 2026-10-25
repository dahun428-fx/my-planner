import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { ConversationItem } from "../api/types.gen";
import { copy } from "../lib/copy";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { ConversationList, groupConversations } from "./ConversationList";

// 2026-10-29(목) 12:00 서울. 이번 주는 10/26(월)부터.
const NOW = Date.parse("2026-10-29T03:00:00Z");

const conv = (id: number, at: string, over: Partial<ConversationItem> = {}): ConversationItem => ({
  id,
  kind: "chat",
  channel: "app",
  run_id: null,
  opened_at: at,
  last_message_at: at,
  closed_at: at,
  title: `대화 ${id}`,
  summary: `요약 ${id}`,
  ...over,
});

const ITEMS = [
  conv(1, "2026-10-29T01:00:00Z", { title: "치과 예약", summary: "내일 14:00 치과를 일정에 넣었어요.\n알림은 30분 전." }),
  conv(2, "2026-10-28T11:00:00Z", { kind: "run", run_id: 341, title: "저녁 돌아보기" }),
  conv(3, "2026-10-26T00:30:00Z", { title: null, summary: null, closed_at: null }),
  conv(4, "2026-10-20T09:00:00Z", { title: "책 고르기" }),
  conv(5, "2025-12-01T09:00:00Z", { title: "작년 대화" }),
];

/** GET /conversations: `q` narrows by title; every request's query is kept. DELETE answers 204. */
function serve(items: ConversationItem[] = ITEMS) {
  const seen = { queries: [] as URLSearchParams[], deleted: [] as number[] };
  let left = [...items];
  server.use(
    http.get(`${BASE}/conversations`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      seen.queries.push(q);
      const word = q.get("q");
      return HttpResponse.json({ items: word ? left.filter((c) => (c.title ?? "").includes(word)) : left, next_before: null });
    }),
    http.delete(`${BASE}/conversations/:id`, ({ params }) => {
      seen.deleted.push(Number(params.id));
      left = left.filter((c) => c.id !== Number(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return seen;
}

/** The row button that holds a title (not the row's "… 더 보기" menu button). */
const rowOf = (title: string) => screen.getByText(title).closest("button") as HTMLElement;

const handlers = () => ({ onOpen: vi.fn(), onNew: vi.fn(), onDeleted: vi.fn() });

describe("groupConversations", () => {
  it("오늘, 어제, 이번 주, then months (another year with its year)", () => {
    const groups = groupConversations(ITEMS, NOW);
    expect(groups.map((g) => [g.label, g.items.map((c) => c.id)])).toEqual([
      ["오늘", [1]],
      ["어제", [2]],
      ["이번 주", [3]],
      ["10월", [4]],
      ["2025년 12월", [5]],
    ]);
  });

  it("the Seoul date decides, not the device's: 00:30 Seoul on the 29th is 오늘", () => {
    const groups = groupConversations([conv(9, "2026-10-28T15:30:00Z")], NOW);
    expect(groups[0].label).toBe(copy.chat.groups.today);
  });
});

describe("ConversationList", () => {
  it("shows the app conversations by date with title, summary line and time", async () => {
    const seen = serve();
    renderWithProviders(<ConversationList readOnly={false} now={NOW} {...handlers()} />);
    expect(await screen.findByText("치과 예약")).toBeInTheDocument();
    expect(seen.queries[0].get("channel")).toBe("app");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["오늘", "어제", "이번 주", "10월", "2025년 12월"]);
    const row = rowOf("치과 예약");
    // The summary's first line only; the time of today's row.
    expect(within(row).getByText("내일 14:00 치과를 일정에 넣었어요.")).toBeInTheDocument();
    expect(within(row).queryByText(/알림은 30분 전/)).toBeNull();
    expect(within(row).getByText("10:00")).toBeInTheDocument();
    // Older rows show the day instead.
    expect(within(rowOf("책 고르기")).getByText("10월 20일")).toBeInTheDocument();
    expect(rowOf(copy.chat.untitled)).toBeInTheDocument();
  });

  it("a check-in conversation has 체크인 before its title", async () => {
    serve();
    renderWithProviders(<ConversationList readOnly={false} now={NOW} {...handlers()} />);
    await screen.findByText("저녁 돌아보기");
    const row = rowOf("저녁 돌아보기");
    const tag = within(row).getByText(copy.chat.checkinTag);
    expect(tag.compareDocumentPosition(within(row).getByText("저녁 돌아보기")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(rowOf("치과 예약")).queryByText(copy.chat.checkinTag)).toBeNull();
  });

  it("searches titles and summaries with q (after typing stops)", async () => {
    const seen = serve();
    const user = userEvent.setup();
    renderWithProviders(<ConversationList readOnly={false} now={NOW} {...handlers()} />);
    await screen.findByText("치과 예약");
    await user.type(screen.getByRole("searchbox", { name: copy.chat.search }), "책");
    await waitFor(() => expect(screen.queryByText("치과 예약")).toBeNull());
    expect(screen.getByText("책 고르기")).toBeInTheDocument();
    expect(seen.queries.at(-1)?.get("q")).toBe("책");
    await user.type(screen.getByRole("searchbox", { name: copy.chat.search }), "없는말");
    expect(await screen.findByText(copy.chat.noMatch)).toBeInTheDocument();
  });

  it("opening a row hands its id up", async () => {
    serve();
    const h = handlers();
    const user = userEvent.setup();
    renderWithProviders(<ConversationList readOnly={false} now={NOW} {...h} />);
    await screen.findByText("책 고르기");
    await user.click(rowOf("책 고르기"));
    expect(h.onOpen).toHaveBeenCalledWith(4);
  });

  it("지우기 asks first with the 9.5 sentence, then deletes the row", async () => {
    const seen = serve();
    const h = handlers();
    const user = userEvent.setup();
    renderWithProviders(<ConversationList readOnly={false} now={NOW} {...h} />);
    await screen.findByText("책 고르기");
    // The row's menu (the long press / keyboard way to the swipe actions).
    await user.click(screen.getByRole("button", { name: copy.today.moreActions("책 고르기") }));
    await user.click(screen.getByRole("button", { name: copy.chat.delete }));
    expect(await screen.findByText("이 대화를 지울까요? 되돌릴 수 없어요.")).toBeInTheDocument();
    // Keep: nothing goes.
    await user.click(screen.getByRole("button", { name: copy.chat.keep }));
    expect(seen.deleted).toEqual([]);
    await user.click(screen.getByRole("button", { name: copy.today.moreActions("책 고르기") }));
    await user.click(screen.getByRole("button", { name: copy.chat.delete }));
    const ask = await screen.findByText(copy.chat.deleteAsk);
    await user.click(within(ask.closest("[role=dialog]") as HTMLElement).getByRole("button", { name: copy.chat.delete }));
    await waitFor(() => expect(seen.deleted).toEqual([4]));
    await waitFor(() => expect(screen.queryByText("책 고르기")).toBeNull());
    expect(h.onDeleted).toHaveBeenCalledWith(4);
  });

  it("새 대화 sits at the top and hands up", async () => {
    serve();
    const h = handlers();
    const user = userEvent.setup();
    renderWithProviders(<ConversationList readOnly={false} now={NOW} {...h} />);
    const button = screen.getByRole("button", { name: copy.chat.newConversation });
    await screen.findByText("치과 예약");
    expect(button.compareDocumentPosition(screen.getByRole("searchbox")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(button);
    expect(h.onNew).toHaveBeenCalledTimes(1);
  });

  it("read-only: no 새 대화, no opening and no delete", async () => {
    serve();
    renderWithProviders(<ConversationList readOnly now={NOW} {...handlers()} />);
    await screen.findByText("치과 예약");
    expect(screen.getByRole("button", { name: copy.chat.newConversation })).toBeDisabled();
    expect(rowOf("치과 예약")).toBeDisabled();
    expect(screen.queryByRole("button", { name: copy.today.moreActions("책 고르기") })).toBeNull();
  });

  it("an empty list says so", async () => {
    serve([]);
    renderWithProviders(<ConversationList readOnly={false} now={NOW} {...handlers()} />);
    expect(await screen.findByText(copy.chat.noConversations)).toBeInTheDocument();
  });
});

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CurveHistory } from "../api/types.gen";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import { resetMemory } from "../lib/curveMemory";
import history from "../test/fixtures/curve-history.json";
import historyEmpty from "../test/fixtures/curve-history-empty.json";
import { BASE, ORIGIN } from "../test/handlers";
import { server } from "../test/server";
import { CurveScreen } from "./CurveScreen";
import { HistoryView } from "./HistoryView";

import { resetRouter, router } from "../test/router";
vi.mock("next/router", async () => (await import("../test/router")).routerModule);

const data = history as CurveHistory;
const withChapter = (patch: Partial<CurveHistory["chapters"][number]>, i = 0): CurveHistory => ({
  ...data,
  chapters: data.chapters.map((c, j) => (j === i ? { ...c, ...patch } : c)),
});

beforeEach(() => {
  resetMemory();
  resetRouter();
});
afterEach(() => vi.restoreAllMocks());

function renderTab(body: object = history) {
  const seen: string[] = [];
  server.use(
    http.get(`${BASE}/curve/history`, ({ request }) => {
      seen.push(new URL(request.url).search);
      return HttpResponse.json(body as Record<string, unknown>);
    }),
  );
  localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
  render(
    <ConnectionProvider>
      <CurveScreen />
    </ConnectionProvider>,
  );
  return seen;
}

const shown = () => document.querySelectorAll("[data-chapter-id]").length;
const chapterOf = (title: string) => screen.getByRole("region", { name: title });

describe("HistoryView", () => {
  it("tab_in_url_survives_reload", async () => {
    router.query = { tab: "history" };
    const seen = renderTab();
    expect(await screen.findByText("지금까지 걸어온 길 · 챕터 2개 · 사건 4개 · 2019년부터")).toBeInTheDocument();
    expect(seen).toEqual([""]);
    expect(screen.getByRole("button", { name: "히스토리" })).toHaveAttribute("aria-pressed", "true");
  });

  it("default_tab_is_curve", async () => {
    renderTab();
    expect(screen.getByRole("button", { name: "곡선" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText(/지금까지 걸어온 길/)).toBeNull();
  });

  it("tab_buttons_write_the_address_shallowly", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(screen.getByRole("button", { name: "히스토리" }));
    expect(router.replace).toHaveBeenCalledWith({ query: { tab: "history" } }, undefined, { shallow: true });
    expect(await screen.findByText(/지금까지 걸어온 길/)).toBeInTheDocument();
  });

  it("chapter_rows_and_tags", async () => {
    router.query = { tab: "history" };
    renderTab();
    const first = await screen.findByRole("region", { name: "꾸민 새 출발" });
    expect(within(first).getByText("2025 –")).toBeInTheDocument();
    expect(within(first).getByText(/사다리 평균 5\.1 · 사건 2개/)).toBeInTheDocument();
    const row = within(first).getByRole("button", { name: /꾸민 첫 전시/ });
    expect(row.textContent).toContain("2025.09");
    expect(row.textContent).toContain("꾸민 메모: 작은 카페 벽에 세 점");
    expect(row.textContent).toContain("높은 때");
    expect(row.textContent).toContain("배움");
    expect(row.querySelector('[data-area="learning"]')).not.toBeNull();
    // the whole-number ladder has no ".0"
    expect(within(chapterOf("꾸민 배움의 해")).getByText(/그때 사다리 6 · 사건 0개/)).toBeInTheDocument();
    // newest chapter first, events newest first
    const titles = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(titles).toEqual(["꾸민 새 출발", "꾸민 배움의 해", "시기를 정하지 않은 사건"]);
    expect(within(first).getAllByRole("button").map((b) => b.textContent)).toEqual([
      expect.stringContaining("꾸민 이사 결정"),
      expect.stringContaining("꾸민 첫 전시"),
    ]);
  });

  it("assistant_tag_only_for_chat_origin", () => {
    render(<HistoryView history={data} isPhone={false} />);
    const chat = screen.getByRole("button", { name: /꾸민 이사 결정/ });
    const seed = screen.getByRole("button", { name: /꾸민 첫 전시/ });
    expect(chat.textContent).toContain("비서가 만듦");
    expect(seed.textContent).not.toContain("비서가 만듦");
    expect(screen.getAllByText("비서가 만듦")).toHaveLength(1);
  });

  it("estimate_marks", () => {
    const plain = withChapter({ sketch: null }, 0);
    render(<HistoryView history={plain} isPhone={false} />);
    const ch = chapterOf("꾸민 새 출발");
    expect(within(ch).getByText("추정")).toBeInTheDocument(); // chapter tag
    expect(within(ch).getByText("기억으로 그린 시기예요.")).toBeInTheDocument();
    // a certain chapter has neither
    expect(within(chapterOf("꾸민 배움의 해")).queryByText("추정")).toBeNull();
    expect(within(chapterOf("꾸민 배움의 해")).queryByText("기억으로 그린 시기예요.")).toBeNull();
    // an estimated kind reads "힘든 때 · 추정"
    expect(screen.getByRole("button", { name: /꾸민 긴 감기/ }).textContent).toContain("힘든 때 · 추정");
  });

  it("estimate_date_has_a_word_before_it", () => {
    const h = withChapter({ events: [{ ...data.chapters[0].events[1], certainty: "estimate" }] }, 0);
    render(<HistoryView history={h} isPhone={false} />);
    expect(screen.getByRole("button", { name: /꾸민 첫 전시/ }).textContent).toContain("추정 2025.09");
  });

  it("empty_kind_message_keeps_chapter_header", async () => {
    const user = userEvent.setup();
    render(<HistoryView history={data} isPhone={false} />);
    await user.click(screen.getByRole("button", { name: "힘든 때" }));
    expect(screen.getByRole("button", { name: "힘든 때" })).toHaveAttribute("aria-pressed", "true");
    const ch = chapterOf("꾸민 새 출발");
    expect(within(ch).getByRole("heading", { name: "꾸민 새 출발" })).toBeInTheDocument();
    expect(within(ch).getByText("이 시기에는 고른 종류의 사건이 없어요.")).toBeInTheDocument();
    // the unassigned group still holds the one low event
    expect(screen.getByRole("button", { name: /꾸민 긴 감기/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /꾸민 첫 자전거/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "전체" }));
    expect(within(ch).queryByText("이 시기에는 고른 종류의 사건이 없어요.")).toBeNull();
  });

  it("sort_toggle", async () => {
    const user = userEvent.setup();
    render(<HistoryView history={data} isPhone={false} />);
    const headings = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    await user.click(screen.getByRole("button", { name: "최근부터 ▾" }));
    expect(screen.getByRole("button", { name: "오래된 것부터 ▾" })).toBeInTheDocument();
    expect(headings()).toEqual(["시기를 정하지 않은 사건", "꾸민 배움의 해", "꾸민 새 출발"]);
    // events inside a chapter turn around too
    expect(within(chapterOf("꾸민 새 출발")).getAllByRole("button").map((b) => b.textContent)).toEqual([
      expect.stringContaining("꾸민 첫 전시"),
      expect.stringContaining("꾸민 이사 결정"),
    ]);
    await user.click(screen.getByRole("button", { name: "오래된 것부터 ▾" }));
    expect(headings()[0]).toBe("꾸민 새 출발");
  });

  it("phone_folded_chapter_expands", async () => {
    const user = userEvent.setup();
    const chapters = Array.from({ length: 6 }, (_, i) => ({
      ...data.chapters[1],
      id: 10 + i,
      title: `꾸민 시기 ${6 - i}`,
      start: `20${25 - i}-01`,
      end: `20${25 - i}-12`,
    }));
    const six: CurveHistory = { ...data, chapters, unassigned: { events: [], hidden_sensitive: { count: 0, years: [] } } };
    const { unmount } = render(<HistoryView history={six} isPhone />);
    expect(shown()).toBe(4);
    const more = screen.getByRole("button", { name: "꾸민 시기 2 · 2021 – 2021 더 보기" });
    expect(screen.getByRole("button", { name: "꾸민 시기 1 · 2020 – 2020 더 보기" })).toBeInTheDocument();
    await user.click(more);
    expect(shown()).toBe(5);
    expect(chapterOf("꾸민 시기 2")).toBeInTheDocument();
    // kept for this tab only: a remount keeps it, a fresh tab does not
    unmount();
    const { unmount: unmount2 } = render(<HistoryView history={six} isPhone />);
    expect(shown()).toBe(5);
    unmount2();
    // a desktop never folds
    render(<HistoryView history={six} isPhone={false} />);
    expect(screen.queryByRole("button", { name: /더 보기/ })).toBeNull();
    expect(shown()).toBe(6);
  });

  it("folded_button_says_it_is_collapsed", () => {
    const many: CurveHistory = { ...data, chapters: Array.from({ length: 5 }, (_, i) => ({ ...data.chapters[1], id: 20 + i, title: `꾸민 옛 ${i}` })) };
    render(<HistoryView history={many} isPhone />);
    expect(screen.getByRole("button", { name: /더 보기/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("hidden_sensitive_alone_makes_no_unassigned_group_yet", () => {
    const h: CurveHistory = { ...data, unassigned: { events: [], hidden_sensitive: { count: 2, years: [2020] } } };
    render(<HistoryView history={h} isPhone={false} />);
    expect(screen.queryByRole("heading", { name: "시기를 정하지 않은 사건" })).toBeNull();
  });

  it("area_pictogram_takes_the_area_colour_rule", () => {
    render(<HistoryView history={data} isPhone={false} />);
    const tag = screen.getByRole("button", { name: /꾸민 첫 전시/ }).querySelector('[data-area="learning"]')!;
    expect(tag.querySelector(".pictogram")).not.toBeNull();
    expect(readFileSync(join(__dirname, "../styles/globals.css"), "utf8")).toMatch(/\.history-tags \.stat-name \.pictogram\s*\{\s*color: var\(--area\)/);
  });

  it("phone_follows_the_viewport_media_query", async () => {
    const desktop = vi.fn().mockImplementation(() => ({ matches: true, addEventListener: () => {}, removeEventListener: () => {} }));
    vi.stubGlobal("matchMedia", desktop);
    window.matchMedia = desktop as unknown as typeof window.matchMedia;
    router.query = { tab: "history" };
    const many: CurveHistory = { ...data, chapters: Array.from({ length: 6 }, (_, i) => ({ ...data.chapters[1], id: 30 + i, title: `꾸민 긴 ${i}`, start: `20${25 - i}-01` })) };
    renderTab(many);
    await screen.findByRole("region", { name: "꾸민 긴 5" });
    expect(screen.queryByRole("button", { name: /더 보기/ })).toBeNull();
    expect(desktop).toHaveBeenCalledWith("(min-width: 720px)");
    // @ts-expect-error remove the stand-in again
    delete window.matchMedia;
    vi.unstubAllGlobals();
  });

  it("no_curve_request_before_the_router_is_ready", async () => {
    router.isReady = false;
    const seen: string[] = [];
    server.use(http.get(`${BASE}/curve`, ({ request }) => (seen.push(request.url), HttpResponse.json({}))));
    renderTab();
    await new Promise((r) => setTimeout(r, 50));
    expect(seen).toEqual([]);
  });

  it("empty_state_copy", async () => {
    router.query = { tab: "history" };
    renderTab(historyEmpty);
    expect(await screen.findByText("시드를 가져오거나 대화에서 사건을 남기면 여기에 쌓여요.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });

  it("row_opens_popover", async () => {
    const user = userEvent.setup();
    render(<HistoryView history={data} isPhone={false} />);
    await user.click(screen.getByRole("button", { name: /꾸민 첫 전시/ }));
    const dialog = screen.getByRole("dialog", { name: "꾸민 첫 전시" });
    expect(dialog.textContent).toContain("2025년 9월 · 높은 때");
    expect(dialog.textContent).toContain("꾸민 메모: 작은 카페 벽에 세 점");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: /꾸민 첫 전시/ })).toHaveFocus();
  });

  it("sensitive_row_is_marked", async () => {
    const h = withChapter({ events: [{ ...data.chapters[0].events[0], sensitive: true }] }, 0);
    render(<HistoryView history={h} isPhone={false} />);
    expect(screen.getByRole("button", { name: /꾸민 이사 결정/ }).textContent).toContain("민감");
  });

  it("no_local_storage_writes", async () => {
    const user = userEvent.setup();
    const set = vi.spyOn(Storage.prototype, "setItem");
    render(<HistoryView history={data} isPhone />);
    await user.click(screen.getByRole("button", { name: "높은 때" }));
    await user.click(screen.getByRole("button", { name: "최근부터 ▾" }));
    await user.click(screen.getByRole("button", { name: /꾸민 첫 전시/ }));
    expect(set).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  });
});

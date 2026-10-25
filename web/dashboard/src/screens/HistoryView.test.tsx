import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CurveHistory } from "../api/types.gen";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import { memory, resetMemory } from "../lib/curveMemory";
import history from "../test/fixtures/curve-history.json";
import historySensitive from "../test/fixtures/curve-history-sensitive.json";
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

  it("hidden_sensitive_alone_makes_an_unassigned_group_with_its_line", () => {
    const h: CurveHistory = { ...data, unassigned: { events: [], hidden_sensitive: { count: 2, years: [2020] } } };
    render(<HistoryView history={h} isPhone={false} />);
    const group = screen.getByRole("region", { name: "시기를 정하지 않은 사건" });
    expect(within(group).getByText("가려 둔 사건 2개 · 2020년")).toBeInTheDocument();
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
    memory.sensitive = true;
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

// ---- SP8-10: sensitive events (8.5), the glance strip and the side summary (8.6) ----

const SECRET = "꾸민 조용한 겨울";
const sensitiveData = historySensitive as CurveHistory;

/** A history where chapter 1 and the unassigned group each hide one event: the plain answer and the include_sensitive one. */
function twoGroups() {
  const secret1 = { ...data.chapters[0].events[0], id: 90, title: "꾸민 첫 비밀", date: "2025-05", sensitive: true, kind: "low" as const };
  const plain: CurveHistory = {
    ...data,
    chapters: data.chapters.map((c, i) => (i === 0 ? { ...c, hidden_sensitive: { count: 1, years: [2025] } } : c)),
  };
  const full: CurveHistory = {
    ...sensitiveData,
    chapters: sensitiveData.chapters.map((c, i) => (i === 0 ? { ...c, events: [...c.events, secret1] } : c)),
    summary: { ...sensitiveData.summary, events: 6 },
  };
  return { plain, full };
}

function renderServed(plain: CurveHistory, full: CurveHistory) {
  const seen: string[] = [];
  server.use(
    http.get(`${BASE}/curve/history`, ({ request }) => {
      const q = new URL(request.url).search;
      seen.push(q);
      return HttpResponse.json((q.includes("include_sensitive=true") ? full : plain) as unknown as Record<string, unknown>);
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

describe("HistoryView sensitive events", () => {
  it("hidden_line_counts_years", () => {
    render(<HistoryView history={data} isPhone={false} />);
    const group = screen.getByRole("region", { name: "시기를 정하지 않은 사건" });
    expect(within(group).getByText("가려 둔 사건 1개 · 2025년")).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "보기" })).toBeInTheDocument();
    // a chapter without any shows no line
    expect(within(chapterOf("꾸민 새 출발")).queryByText(/가려 둔 사건/)).toBeNull();
  });

  it("sensitive_title_not_in_dom_before_show", async () => {
    router.query = { tab: "history" };
    const { plain, full } = twoGroups();
    renderServed(plain, full);
    await screen.findAllByText("가려 둔 사건 1개 · 2025년");
    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(document.body.innerHTML).not.toContain("꾸민 첫 비밀");
  });

  it("show_fetches_once_and_expands_that_chapter_only", async () => {
    const user = userEvent.setup();
    router.query = { tab: "history" };
    const { plain, full } = twoGroups();
    const seen = renderServed(plain, full);
    const ch = await screen.findByRole("region", { name: "꾸민 새 출발" });
    expect(seen).toEqual([""]);
    await user.click(within(ch).getByRole("button", { name: "보기" }));
    expect(await within(chapterOf("꾸민 새 출발")).findByRole("button", { name: /꾸민 첫 비밀/ })).toBeInTheDocument();
    expect(seen).toEqual(["", "?include_sensitive=true"]);
    // the tag, and the other group still hides its own
    expect(within(chapterOf("꾸민 새 출발")).getByRole("button", { name: /꾸민 첫 비밀/ }).textContent).toContain("민감");
    expect(screen.queryByText(SECRET)).toBeNull();
    const group = screen.getByRole("region", { name: "시기를 정하지 않은 사건" });
    expect(within(group).getByText("가려 둔 사건 1개 · 2025년")).toBeInTheDocument();
    // the curve tab's shared state is not touched, and the chapter's line is gone
    expect(memory.sensitive).toBe(false);
    expect(within(chapterOf("꾸민 새 출발")).queryByText(/가려 둔 사건/)).toBeNull();
    // a second "보기" in another group asks for nothing more
    await user.click(within(group).getByRole("button", { name: "보기" }));
    expect(await screen.findByRole("button", { name: new RegExp(SECRET) })).toBeInTheDocument();
    expect(seen).toEqual(["", "?include_sensitive=true"]);
  });

  it("summary_counts_only_what_is_shown", async () => {
    const user = userEvent.setup();
    router.query = { tab: "history" };
    const { plain, full } = twoGroups();
    renderServed(plain, full);
    const ch = await screen.findByRole("region", { name: "꾸민 새 출발" });
    await user.click(within(ch).getByRole("button", { name: "보기" }));
    await within(chapterOf("꾸민 새 출발")).findByRole("button", { name: /꾸민 첫 비밀/ });
    // 6 in the answer, one of them (in the unassigned group) still hidden
    expect(screen.getByText(/지금까지 걸어온 길 · 챕터 2개 · 사건 5개/)).toBeInTheDocument();
    // the opened chapter's title is there; the still hidden group's is in no text, label or attribute
    expect(document.body.innerHTML).toContain("꾸민 첫 비밀");
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("hide_folds_again", async () => {
    const user = userEvent.setup();
    router.query = { tab: "history" };
    const { plain, full } = twoGroups();
    const seen = renderServed(plain, full);
    const ch = await screen.findByRole("region", { name: "꾸민 새 출발" });
    await user.click(within(ch).getByRole("button", { name: "보기" }));
    const row = await within(chapterOf("꾸민 새 출발")).findByRole("button", { name: /꾸민 첫 비밀/ });
    await user.click(within(row.closest("li")!).getByRole("button", { name: "가리기" }));
    expect(screen.queryByText("꾸민 첫 비밀")).toBeNull();
    expect(within(chapterOf("꾸민 새 출발")).getByText("가려 둔 사건 1개 · 2025년")).toBeInTheDocument();
    // nothing is open any more: the plain answer is asked for again and the raw one let go
    await waitFor(() => expect(seen).toEqual(["", "?include_sensitive=true", ""]));
    expect(document.body.innerHTML).not.toContain("꾸민 첫 비밀");
  });

  it("toggle_off_expands_all_and_matches_curve_tab", async () => {
    const user = userEvent.setup();
    router.query = { tab: "history" };
    const { plain, full } = twoGroups();
    const seen = renderServed(plain, full);
    const toggle = await screen.findByRole("checkbox", { name: "민감한 사건 가림" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    expect(await screen.findByRole("button", { name: new RegExp(SECRET) })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /꾸민 첫 비밀/ })).toBeInTheDocument();
    expect(seen).toEqual(["", "?include_sensitive=true"]);
    // the same state as the curve tab's "민감한 사건 보기"
    expect(memory.sensitive).toBe(true);
    expect(screen.queryByText(/가려 둔 사건/)).toBeNull();
    await user.click(toggle);
    expect(memory.sensitive).toBe(false);
    expect(screen.queryByText(SECRET)).toBeNull();
    expect(screen.getAllByText(/가려 둔 사건 1개/)).toHaveLength(2);
  });

  it("hiding_again_folds_chapters_opened_one_by_one_and_lets_go_of_the_raw_answer", async () => {
    const user = userEvent.setup();
    router.query = { tab: "history" };
    const { plain, full } = twoGroups();
    const seen = renderServed(plain, full);
    const ch = await screen.findByRole("region", { name: "꾸민 새 출발" });
    await user.click(within(ch).getByRole("button", { name: "보기" }));
    await within(chapterOf("꾸민 새 출발")).findByRole("button", { name: /꾸민 첫 비밀/ });
    await user.click(screen.getByRole("checkbox", { name: "민감한 사건 가림" })); // off: all open
    await user.click(screen.getByRole("checkbox", { name: "민감한 사건 가림" })); // on: all folded
    expect(memory.sensitive).toBe(false);
    expect(memory.sensitiveOpened.size).toBe(0);
    // the plain answer is asked for again; nothing sensitive stays in the page
    await waitFor(() => expect(seen[seen.length - 1]).toBe(""));
    await screen.findAllByText("가려 둔 사건 1개 · 2025년");
    expect(document.body.innerHTML).not.toContain("꾸민 첫 비밀");
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("since_year_follows_what_is_shown", () => {
    const h: CurveHistory = {
      ...data,
      since_year: 2001,
      chapters: data.chapters,
      unassigned: { events: [{ ...data.unassigned.events[0], id: 50, date: "2001-03", sensitive: true }], hidden_sensitive: { count: 0, years: [] } },
    };
    render(<HistoryView history={h} isPhone={false} />);
    expect(screen.getByText(/2023년부터/)).toBeInTheDocument();
  });

  it("curve_tab_sensitive_on_means_history_toggle_off", async () => {
    router.query = { tab: "history" };
    memory.sensitive = true;
    const { plain, full } = twoGroups();
    const seen = renderServed(plain, full);
    const toggle = await screen.findByRole("checkbox", { name: "민감한 사건 가림" });
    expect(toggle).not.toBeChecked();
    expect(seen).toEqual(["?include_sensitive=true"]);
    expect(await screen.findByRole("button", { name: new RegExp(SECRET) })).toBeInTheDocument();
  });
});

describe("HistoryView summary and layout", () => {
  it("summary_lines_omit_null", () => {
    const { rerender } = render(<HistoryView history={data} isPhone={false} />);
    const box = screen.getByRole("group", { name: "옆 요약" });
    const pairs = [...box.querySelectorAll("li")].map((li) => [li.querySelector(".meta")!.textContent, li.querySelector(".history-summary-value")!.textContent]);
    expect(pairs).toEqual([
      ["가장 높았던 챕터", "꾸민 배움의 해 · 사다리 6"],
      ["전환점", "1번 · 2026년"],
      ["가장 길었던 챕터", "꾸민 배움의 해 · 2년"],
      ["기억과 기록", "2025년부터는 매일 기록으로 그려요"],
    ]);
    const bare: CurveHistory = { ...data, summary: { ...data.summary, highest: null, longest: null, records_since: null, turning_points: { count: 0, years: [] } } };
    rerender(<HistoryView history={bare} isPhone={false} />);
    const after = screen.getByRole("group", { name: "옆 요약" });
    expect(after.querySelectorAll("li")).toHaveLength(0);
    expect(after.textContent).not.toContain("가장 높았던");
    expect(after.textContent).not.toContain("null");
  });

  it("no_ratio_rank_or_lowest_words", () => {
    render(<HistoryView history={data} isPhone={false} />);
    const text = screen.getByRole("group", { name: "옆 요약" }).textContent!;
    for (const w of ["%", "순위", "가장 낮았던"]) expect(text).not.toContain(w);
    expect(document.querySelector(".glance")!.textContent).not.toMatch(/%|순위|가장 낮았던/);
  });

  it("help_box_copy", () => {
    render(<HistoryView history={data} isPhone={false} />);
    expect(screen.getByText("비서가 정리를 돕는 법")).toBeInTheDocument();
    expect(
      screen.getByText("대화에서 나온 일을 사건 초안으로 만들어 두면, 확인 버튼을 눌러야 여기에 올라와요. 지난 챕터도 '이 시기 같이 정리하자'라고 말하면 돼요."),
    ).toBeInTheDocument();
  });

  it("desktop_side_summary_and_phone_order", () => {
    const { unmount } = render(<HistoryView history={data} isPhone={false} />);
    const side = screen.getByRole("complementary", { name: "한눈에 띠와 옆 요약" });
    expect(within(side).getByText("한눈에 보는 지난 길")).toBeInTheDocument();
    expect(within(side).getByRole("group", { name: "옆 요약" })).toBeInTheDocument();
    // the strip is first in the side column; the list is in the main one
    expect(side.firstElementChild!.querySelector(".glance") ?? side.firstElementChild!.matches(".glance")).toBeTruthy();
    expect(side.contains(chapterOf("꾸민 새 출발"))).toBe(false);
    unmount();

    render(<HistoryView history={data} isPhone />);
    expect(screen.queryByRole("complementary")).toBeNull();
    const strip = document.querySelector(".glance")!;
    const filters = screen.getByRole("group", { name: "거르기" });
    const list = chapterOf("꾸민 새 출발");
    const summary = screen.getByRole("group", { name: "옆 요약" });
    const before = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(before(strip, filters)).toBe(true);
    expect(before(filters, list)).toBe(true);
    expect(before(list, summary)).toBe(true);
  });
});

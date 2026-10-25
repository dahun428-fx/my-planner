import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Moment } from "../api/types.gen";
import { copy, momentDay } from "../lib/copy";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { StatusMoments } from "./StatusMoments";

const T = copy.statusScreen;

const moment = (id: number, date: string, text: string, area: Moment["area"], hidden = false): Moment => ({
  id,
  date,
  text,
  area,
  sources: ["task"],
  hidden,
});

const THREE: Moment[] = [
  moment(41, "2026-10-24", "포트폴리오 사례 하나를 끝까지 다듬었어요", "career"),
  moment(42, "2026-10-24", "아침마다 물을 마셨어요", "health"),
  moment(37, "2026-10-23", "오래 미룬 전화를 걸었어요", null),
];

interface Sent {
  action: string;
  args: { id: number };
  confirm_token: string | null;
}

/** POST /actions: records every body and answers with `answer(body)`. */
function actions(answer: (b: Sent) => object, sent: Sent[] = []) {
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      const body = (await request.json()) as Sent;
      sent.push(body);
      return HttpResponse.json(answer(body));
    }),
  );
  return sent;
}

const applied = (confirmation: string, undo_id: number | null = null) => ({
  status: "applied",
  activity_id: 900,
  undo_id,
  result: {},
  confirmation,
});

const rowOf = (text: string) => screen.getByText(text).closest("li") as HTMLElement;

function swipe(el: HTMLElement, dx: number) {
  fireEvent.pointerDown(el, { pointerId: 1, clientX: 300, clientY: 10, pointerType: "touch" });
  fireEvent.pointerMove(el, { pointerId: 1, clientX: 300 + dx, clientY: 12, pointerType: "touch" });
  fireEvent.pointerUp(el, { pointerId: 1, clientX: 300 + dx, clientY: 12, pointerType: "touch" });
}

function renderMoments(props: Partial<Parameters<typeof StatusMoments>[0]> = {}, conn: "online" | "offline" = "online") {
  const onChanged = props.onChanged ?? (() => {});
  return renderWithProviders(<StatusMoments moments={THREE} hiddenCount={0} {...props} onChanged={onChanged} />, { conn });
}

describe("StatusMoments (SP8 10.2)", () => {
  it("groups_by_day_header", () => {
    renderMoments();
    expect(screen.getByRole("heading", { level: 2, name: "이룬 순간" })).toBeInTheDocument();
    const heads = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(heads).toEqual(["10월 24일 (토)", "10월 23일 (금)"]);
    expect(momentDay("2026-10-24")).toBe("10월 24일 (토)");
    const first = rowOf(THREE[0].text);
    expect(first.querySelector("svg.pictogram use")).toHaveAttribute("href", "#p-career");
    expect(first).toHaveAttribute("data-area", "career");
    const noArea = rowOf(THREE[2].text);
    expect(noArea.querySelector("svg.pictogram use")).toHaveAttribute("href", "#p-memory");
    expect(noArea).not.toHaveAttribute("data-area");
  });

  it("swipe_hide_collapses_and_toast_undo", async () => {
    const sent = actions(() => applied("이룬 순간 숨김 (10/24)", 77));
    const changed: number[] = [];
    renderMoments({ onChanged: () => changed.push(1) });
    const row = rowOf(THREE[1].text);
    swipe(row.querySelector("[class*=surface]") as HTMLElement, -120);
    fireEvent.click(await screen.findByRole("button", { name: T.hide }));

    // The row folds (the class says so at once), then leaves; the toast says "숨겼어요" with 되돌리기.
    await waitFor(() => expect(row.closest("[class*=collapse]")?.className).toMatch(/closing/));
    expect(await screen.findByText("숨겼어요")).toBeInTheDocument();
    expect(screen.queryByText("이룬 순간 숨김 (10/24)")).toBeNull();
    expect(screen.getByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(THREE[1].text)).toBeNull());
    expect(sent).toEqual([{ action: "hide_moment", args: { id: 42 }, client_msg_id: expect.any(String), confirm_token: null }]);
    expect(changed.length).toBeGreaterThan(0);
    // The other rows stay.
    expect(screen.getByText(THREE[0].text)).toBeInTheDocument();
  });

  it("more_button_is_seen_on_every_row", () => {
    // 10.2 (final review S4): people who cannot swipe see the way to 숨기기·지우기 without focusing first.
    renderMoments();
    for (const m of THREE) {
      const more = within(rowOf(m.text)).getByRole("button", { name: `${T.more}, ${m.text}` });
      expect(more).toHaveClass("moreShown");
      expect(more.querySelector("svg")).not.toBeNull();
    }
  });

  it("undo_brings_the_row_back", async () => {
    actions(() => applied("이룬 순간 숨김 (10/24)", 77));
    server.use(
      http.post(`${BASE}/activity/77/undo`, () =>
        HttpResponse.json({ status: "undone", activity_id: 901, undone: 77, confirmation: "되돌렸어요" }),
      ),
    );
    renderMoments();
    await userEvent.click(within(rowOf(THREE[1].text)).getByRole("button", { name: /^더 보기/ }));
    await userEvent.click(await screen.findByRole("button", { name: T.hide }));
    await waitFor(() => expect(screen.queryByText(THREE[1].text)).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: copy.activity.undo }));
    expect(await screen.findByText(THREE[1].text)).toBeInTheDocument();
  });

  it("more_button_opens_sheet_with_two_actions", async () => {
    renderMoments();
    const row = rowOf(THREE[0].text);
    await userEvent.click(within(row).getByRole("button", { name: /^더 보기/ }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getAllByRole("button").map((b) => b.textContent)).toEqual(["숨기기", "지우기"]);
  });

  it("delete_asks_confirm_then_sends_token", async () => {
    const sent = actions((b) =>
      b.confirm_token === null
        ? { status: "needs_confirm", confirm_token: "tok-1", summary: "이 순간을 지울까요?", expires_at: "2026-10-25T00:00:00Z" }
        : applied("이룬 순간 지움 (10/24)"),
    );
    renderMoments();
    await userEvent.click(within(rowOf(THREE[2].text)).getByRole("button", { name: /^더 보기/ }));
    await userEvent.click(await screen.findByRole("button", { name: T.delete }));

    // The sheet's own words, not the BE's summary.
    expect(await screen.findByText("이 순간을 지울까요? 되돌릴 수 없어요.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "그대로 두기" })).toBeInTheDocument();
    expect(sent.map((s) => s.confirm_token)).toEqual([null]);
    await userEvent.click(screen.getByRole("button", { name: "지우기" }));
    await waitFor(() => expect(sent.map((s) => s.confirm_token)).toEqual([null, "tok-1"]));
    expect(sent.every((s) => s.action === "delete_moment" && s.args.id === 37)).toBe(true);
    await waitFor(() => expect(screen.queryByText(THREE[2].text)).toBeNull());
    // Nothing to undo on a delete.
    expect(screen.queryByRole("button", { name: copy.activity.undo })).toBeNull();
  });

  it("keep_closes_sheet_sends_nothing_more", async () => {
    const sent = actions(() => ({ status: "needs_confirm", confirm_token: "tok-1", summary: "x", expires_at: "2026-10-25T00:00:00Z" }));
    renderMoments();
    await userEvent.click(within(rowOf(THREE[2].text)).getByRole("button", { name: /^더 보기/ }));
    await userEvent.click(await screen.findByRole("button", { name: T.delete }));
    await userEvent.click(await screen.findByRole("button", { name: "그대로 두기" }));
    await waitFor(() => expect(screen.queryByText("이 순간을 지울까요? 되돌릴 수 없어요.")).toBeNull());
    expect(sent).toHaveLength(1); // only the first ask
    expect(screen.getByText(THREE[2].text)).toBeInTheDocument();
  });

  it("hidden_group_lists_and_unhide", async () => {
    const asked: string[] = [];
    server.use(
      http.get(`${BASE}/moments`, ({ request }) => {
        asked.push(new URL(request.url).search);
        return HttpResponse.json({
          from: "2026-10-12",
          to: "2026-10-25",
          items: [...THREE, moment(50, "2026-10-22", "조용히 숨긴 순간이에요", "learning", true)],
        });
      }),
    );
    const sent = actions(() => applied("이룬 순간 다시 보임 (10/22)", 78));
    const changed: number[] = [];
    renderMoments({ hiddenCount: 1, onChanged: () => changed.push(1) });

    // Folded: only the count, and the hidden text is not on the page.
    const toggle = screen.getByRole("button", { name: "숨긴 순간 1개" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("조용히 숨긴 순간이에요")).toBeNull();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("조용히 숨긴 순간이에요")).toBeInTheDocument();
    expect(asked).toEqual(["?include_hidden=true"]);
    // Only the hidden ones are listed there (the visible ones are above, once each).
    expect(screen.getAllByText(THREE[0].text)).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "다시 보이기" }));
    expect(await screen.findByText("다시 보여요")).toBeInTheDocument();
    expect(sent).toEqual([{ action: "unhide_moment", args: { id: 50 }, client_msg_id: expect.any(String), confirm_token: null }]);
    expect(screen.getByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("조용히 숨긴 순간이에요")).toBeNull());
    expect(changed.length).toBeGreaterThan(0);
  });

  it("no_hidden_group_without_hidden", () => {
    renderMoments({ hiddenCount: 0 });
    expect(screen.queryByRole("button", { name: /숨긴 순간/ })).toBeNull();
  });

  it("older_loads_14_more_days", async () => {
    const asked: string[] = [];
    server.use(
      http.get(`${BASE}/moments`, ({ request }) => {
        asked.push(new URL(request.url).search);
        return HttpResponse.json({
          from: "2026-10-09",
          to: "2026-10-22",
          items: [moment(30, "2026-10-20", "더 이른 날의 순간이에요", "finance")],
        });
      }),
    );
    renderMoments();
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    expect(await screen.findByText("더 이른 날의 순간이에요")).toBeInTheDocument();
    // The first page starts the day after the earliest shown day, so that day comes back whole.
    expect(asked).toEqual(["?before=2026-10-24&days=14"]);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["10월 24일 (토)", "10월 23일 (금)", "10월 20일 (화)"]);
    // The next page goes before what was fetched last.
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    await waitFor(() => expect(asked).toHaveLength(2));
    expect(asked[1]).toBe("?before=2026-10-09&days=14");
  });

  it("older_keeps_the_rest_of_a_day_cut_at_20", async () => {
    // Seven days of three moments: `GET /status` gives the newest 20, so 10월 18일 comes with only two of its three.
    const days = ["2026-10-24", "2026-10-23", "2026-10-22", "2026-10-21", "2026-10-20", "2026-10-19", "2026-10-18"];
    const all = days.flatMap((d, i) => [0, 1, 2].map((slot) => moment(100 - (i * 3 + slot), d, `${d}의 ${slot + 1}번째 순간이에요`, "health")));
    expect(all).toHaveLength(21);
    const asked: string[] = [];
    server.use(
      http.get(`${BASE}/moments`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        asked.push(`?${q.toString()}`);
        // The BE's rule: `to` is the day before `before`, and the page reaches 14 days back from it.
        const to = new Date(`${q.get("before")}T00:00:00Z`);
        to.setUTCDate(to.getUTCDate() - 1);
        const from = new Date(to);
        from.setUTCDate(from.getUTCDate() - 13);
        const [f, t] = [from.toISOString().slice(0, 10), to.toISOString().slice(0, 10)];
        return HttpResponse.json({ from: f, to: t, items: all.filter((m) => m.date >= f && m.date <= t) });
      }),
    );
    renderMoments({ moments: all.slice(0, 20) });
    expect(screen.queryByText("2026-10-18의 3번째 순간이에요")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    expect(await screen.findByText("2026-10-18의 3번째 순간이에요")).toBeInTheDocument();
    expect(asked).toEqual(["?before=2026-10-19&days=14"]);
    for (const m of all) expect(screen.getAllByText(m.text)).toHaveLength(1);
    // The cut day stays one group, in its own order.
    const heads = screen.getAllByRole("heading", { level: 3 });
    expect(heads).toHaveLength(7);
    const last = heads[6].parentElement as HTMLElement;
    expect(within(last).getAllByText(/^2026-10-18의/).map((el) => el.textContent)).toEqual([
      "2026-10-18의 1번째 순간이에요",
      "2026-10-18의 2번째 순간이에요",
      "2026-10-18의 3번째 순간이에요",
    ]);
  });

  it("empty_copy", () => {
    renderMoments({ moments: [] });
    expect(screen.getByText("하루가 끝나면 비서가 그날 해낸 일을 몇 줄로 남겨 둬요.")).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("older_loads_14_more_days_when_week_is_empty", async () => {
    const asked: string[] = [];
    server.use(
      http.get(`${BASE}/moments`, ({ request }) => {
        asked.push(new URL(request.url).search);
        return HttpResponse.json({ from: "2026-10-12", to: "2026-10-25", items: [moment(30, "2026-10-15", "쉬기 전 마지막 순간이에요", "finance")] });
      }),
    );
    renderMoments({ moments: [] });
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    expect(await screen.findByText("쉬기 전 마지막 순간이에요")).toBeInTheDocument();
    expect(asked).toEqual(["?days=14"]);
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    await waitFor(() => expect(asked).toHaveLength(2));
    expect(asked[1]).toBe("?before=2026-10-12&days=14");
  });

  it("older_says_nothing_more_when_a_page_is_empty", async () => {
    const asked: string[] = [];
    server.use(
      http.get(`${BASE}/moments`, ({ request }) => {
        asked.push(new URL(request.url).search);
        // First page: only a day already shown (comes back whole, nothing new). Second page: one new moment.
        return HttpResponse.json(
          asked.length === 1
            ? { from: "2026-10-10", to: "2026-10-23", items: [THREE[2]] }
            : { from: "2026-09-26", to: "2026-10-09", items: [moment(30, "2026-10-05", "더 이른 날의 순간이에요", "finance")] },
        );
      }),
    );
    renderMoments();
    expect(screen.queryByText(T.olderNone)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    await waitFor(() => expect(asked).toHaveLength(1));
    // The overlap page alone never triggers the line.
    await act(async () => {});
    expect(screen.queryByText("더 없어요.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    expect(await screen.findByText("더 이른 날의 순간이에요")).toBeInTheDocument();
    expect(screen.queryByText("더 없어요.")).toBeNull();
  });

  it("older_says_nothing_more_after_two_empty_pages", async () => {
    let n = 0;
    server.use(
      http.get(`${BASE}/moments`, () => {
        n += 1;
        return HttpResponse.json(n === 1 ? { from: "2026-10-10", to: "2026-10-23", items: [THREE[2]] } : { from: "2026-09-26", to: "2026-10-09", items: [] });
      }),
    );
    renderMoments();
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    await waitFor(() => expect(n).toBe(1));
    await act(async () => {});
    expect(screen.queryByText("더 없어요.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "지난 순간 더 보기" }));
    expect(await screen.findByText("더 없어요.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "지난 순간 더 보기" })).toBeInTheDocument();
  });

  it("offline_read_only", async () => {
    renderMoments({ hiddenCount: 1 }, "offline");
    await act(async () => {});
    await waitFor(() => expect(screen.queryByRole("button", { name: /^더 보기/ })).toBeNull());
    expect(screen.queryByRole("button", { name: T.hide })).toBeNull();
    // The text is still there to read.
    expect(screen.getByText(THREE[0].text)).toBeInTheDocument();
  });
});

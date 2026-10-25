import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ActivityResponse } from "../api/types.gen";
import { copy } from "../lib/copy";
import asc from "../test/fixtures/activity-asc.json";
import desc1 from "../test/fixtures/activity-desc-1.json";
import todayJson from "../test/fixtures/today.json";
import desc2 from "../test/fixtures/activity-desc-2.json";
import checkin341 from "../test/fixtures/checkin-341.json";
import checkinsToday from "../test/fixtures/checkins-today.json";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { Activity } from "./Activity";

beforeEach(() => {
  bodies.length = 0;
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-24T20:00:00+09:00"));
});
afterEach(async () => {
  vi.useRealTimers();
  await clear();
});

const bad = () => HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 });

function serve(over: { first?: () => Response; checkins?: () => Response } = {}) {
  const urls: URL[] = [];
  server.use(
    http.get(`${BASE}/activity`, ({ request }) => {
      const u = new URL(request.url);
      urls.push(u);
      if (u.searchParams.get("before")) return HttpResponse.json(desc2 as ActivityResponse);
      return over.first ? over.first() : HttpResponse.json(desc1 as ActivityResponse);
    }),
    http.get(`${BASE}/today`, () => HttpResponse.json(todayJson)),
    http.get(`${BASE}/checkins`, () => (over.checkins ? over.checkins() : HttpResponse.json({ items: [] }))),
  );
  return urls;
}

const bodies: Record<string, unknown>[] = [];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function undoes(answer: () => Response) {
  const ids: string[] = [];
  server.use(
    http.post(`${BASE}/activity/:id/undo`, async ({ params, request }) => {
      ids.push(String(params.id));
      bodies.push((await request.json()) as Record<string, unknown>);
      return answer();
    }),
  );
  return ids;
}

const rowOf = (text: string) => screen.getByText(text).closest("div[class*=row]") as HTMLElement;

describe("Activity", () => {
  it("more button at the top right goes to /more/ (spec 9.1)", async () => {
    renderWithProviders(<Activity />);
    expect(await screen.findByRole("link", { name: "더보기" })).toHaveAttribute("href", "/more/");
  });

  it("chat launcher: on when connected, off with the reason when not", async () => {
    serve();
    const { unmount } = renderWithProviders(<Activity />);
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeEnabled());
    unmount();
    const off = renderWithProviders(<Activity />, { conn: "offline" });
    await waitFor(() => expect(screen.getByRole("button", { name: copy.offline.chatLater })).toBeDisabled());
    off.unmount();
    renderWithProviders(<Activity />, { conn: "safe_mode" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: copy.chat.launcher })).toHaveAccessibleDescription(copy.chat.launcherBlocked.safe_mode),
    );
    expect(screen.getByRole("button", { name: copy.chat.launcher })).toBeDisabled();
  });

  it("newest first in date groups", async () => {
    const urls = serve();
    renderWithProviders(<Activity />);
    expect(await screen.findByText("‘장보기’를 내일로 옮겼어요")).toBeInTheDocument();
    expect(urls[0].searchParams.get("order")).toBe("desc");
    expect(urls[0].searchParams.get("limit")).toBe("50");
    const heads = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(heads).toEqual([copy.activity.today, copy.activity.yesterday, "10월 22일"]);
    const a = screen.getByText("‘장보기’를 내일로 옮겼어요");
    const b = screen.getByText("‘운동 30분’을 마쳤어요");
    expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 05:10Z is 14:10 in Seoul; actor and channel
    expect(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByText(copy.activity.meta("14:10", copy.actors.secretary, copy.channels.app))).toBeInTheDocument();
    expect(screen.getByText(copy.activity.meta("11:00", copy.actors.secretary, copy.channels.scheduler))).toBeInTheDocument();
  });

  it("secretary rows have hue dot and text", async () => {
    serve();
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    expect(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByText(copy.activity.bySecretary)).toBeInTheDocument();
    expect(within(rowOf("‘운동 30분’을 마쳤어요")).queryByText(copy.activity.bySecretary)).toBeNull();
    expect(screen.getAllByText(copy.activity.bySecretary)).toHaveLength(3);
  });

  it("undo button only with undo_id", async () => {
    serve();
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    expect(screen.getAllByRole("button", { name: copy.activity.undo })).toHaveLength(2);
    expect(within(rowOf("카드를 올려 뒀어요")).queryByRole("button")).toBeNull();
  });

  it("undo success toasts and refetches", async () => {
    const urls = serve();
    const ids = undoes(() => HttpResponse.json({ status: "undone", confirmation: "되돌렸어요" }));
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    const before = urls.length;
    await userEvent.click(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo }));
    expect(await screen.findByText("되돌렸어요")).toBeInTheDocument();
    expect(ids).toEqual(["120"]);
    expect(bodies[0].client_msg_id).toMatch(UUID);
    await waitFor(() => expect(urls.length).toBeGreaterThan(before));
  });

  it("double tap sends one undo", async () => {
    serve();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const ids: string[] = [];
    server.use(
      http.post(`${BASE}/activity/:id/undo`, async ({ params }) => {
        ids.push(String(params.id));
        await gate;
        return HttpResponse.json({ status: "undone", confirmation: "되돌렸어요" });
      }),
    );
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    const btn = within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo });
    await userEvent.dblClick(btn);
    release();
    await screen.findByText("되돌렸어요");
    expect(ids).toEqual(["120"]);
  });

  it("undo superseded changes row text only", async () => {
    const urls = serve();
    undoes(() => HttpResponse.json({ error: { code: "superseded", message: "x" } }, { status: 409 }));
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    const n = urls.length;
    await userEvent.click(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo }));
    expect(await within(rowOf("‘장보기’를 내일로 옮겼어요")).findByText(copy.activity.undoBlocked.superseded)).toBeInTheDocument();
    expect(within(rowOf("‘장보기’를 내일로 옮겼어요")).queryByRole("button")).toBeNull();
    expect(screen.getAllByRole("button", { name: copy.activity.undo })).toHaveLength(1);
    expect(urls.length).toBe(n);
    expect(screen.getAllByText(copy.activity.undoBlocked.superseded)).toHaveLength(1); // the row only, no toast
  });

  it("undo expired and not undoable", async () => {
    const urls = serve();
    let code = "undo_expired";
    server.use(
      http.post(`${BASE}/activity/:id/undo`, () =>
        code === "undo_expired"
          ? HttpResponse.json({ error: { code, message: "x" } }, { status: 409 })
          : HttpResponse.json({ error: { code, message: "x" } }, { status: 422 }),
      ),
    );
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    await userEvent.click(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo }));
    expect(await screen.findByText(copy.activity.undoBlocked.undo_expired)).toBeInTheDocument();
    const reads = urls.length;
    code = "not_undoable";
    await userEvent.click(within(rowOf("‘운동 30분’을 마쳤어요")).getByRole("button", { name: copy.activity.undo }));
    expect(await screen.findByText(copy.activity.undoBlocked.not_undoable)).toBeInTheDocument();
    expect(urls.length).toBe(reads);
    expect(screen.getAllByText(copy.activity.undoBlocked.not_undoable)).toHaveLength(1);
    expect(screen.getAllByText(copy.activity.undoBlocked.undo_expired)).toHaveLength(1);
  });

  it("groups by the logical day and follows /today.date", async () => {
    vi.setSystemTime(new Date("2026-10-25T01:30:00+09:00"));
    const lateNight = { ...desc1.items[0], id: 130, at: "2026-10-24T15:30:00Z", summary: "자정 지나 한 일", undo_id: null }; // 00:30 on the 25th, Seoul
    serve({ first: () => HttpResponse.json({ items: [lateNight, desc1.items[1], desc1.items[2]], next_since: null, next_before: null }) });
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json({ ...todayJson, date: "2026-10-24" })));
    renderWithProviders(<Activity />);
    await screen.findByText("자정 지나 한 일");
    await waitFor(() => expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([copy.activity.today, copy.activity.yesterday]));
    const group = screen.getByText("자정 지나 한 일").closest("section") as HTMLElement;
    expect(within(group).getByText("‘운동 30분’을 마쳤어요")).toBeInTheDocument();
    expect(within(group).getByText(copy.activity.meta("00:30", copy.actors.secretary, copy.channels.app))).toBeInTheDocument();
  });

  it("undo on an older page keeps the list and marks the row", async () => {
    serve();
    undoes(() => HttpResponse.json({ status: "undone", confirmation: "되돌렸어요" }));
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    await userEvent.click(screen.getByRole("button", { name: copy.activity.more }));
    await screen.findByText("‘치과 예약’을 더했어요");
    server.use(http.post(`${BASE}/activity/:id/undo`, () => HttpResponse.json({ status: "undone", confirmation: "되돌렸어요" })));
    // make an older row undoable by serving it so on the next page read
    await userEvent.click(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo }));
    await screen.findByText("되돌렸어요");
    expect(screen.getByText("‘치과 예약’을 더했어요")).toBeInTheDocument();
    expect(screen.getByText("‘장보기’를 내일로 옮겼어요").closest("s")).not.toBeNull();
  });

  it("undo that fails says so", async () => {
    serve();
    undoes(() => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }));
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    await userEvent.click(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo }));
    expect(await screen.findByText(copy.actions.undoFailed)).toBeInTheDocument();
    // the button comes back so the person can try again
    expect(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo })).toBeEnabled();
  });

  it("already undone reads again", async () => {
    const urls = serve();
    undoes(() => HttpResponse.json({ status: "already_undone" }));
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    const n = urls.length;
    await userEvent.click(within(rowOf("‘장보기’를 내일로 옮겼어요")).getByRole("button", { name: copy.activity.undo }));
    await waitFor(() => expect(urls.length).toBeGreaterThan(n));
  });

  it("undone row strikethrough", async () => {
    serve();
    renderWithProviders(<Activity />);
    const title = await screen.findByText("‘책 반납’을 뺐어요");
    expect(title.closest("s")).not.toBeNull();
    expect(within(rowOf("‘책 반납’을 뺐어요")).getByText(copy.activity.undoneAt("20:30"))).toBeInTheDocument();
    expect(screen.getByText("‘장보기’를 내일로 옮겼어요").closest("s")).toBeNull();
  });

  it("loads more with before cursor", async () => {
    const urls = serve();
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    await userEvent.click(screen.getByRole("button", { name: copy.activity.more }));
    expect(await screen.findByText("‘치과 예약’을 더했어요")).toBeInTheDocument();
    const more = urls.find((u) => u.searchParams.get("before"));
    expect(more?.searchParams.get("before")).toBe("117");
    expect(more?.searchParams.get("order")).toBe("desc");
    expect(more?.searchParams.get("limit")).toBe("50");
    // the last page has no next_before: no more button
    expect(screen.queryByRole("button", { name: copy.activity.more })).toBeNull();
    expect(screen.getByText("‘장보기’를 내일로 옮겼어요")).toBeInTheDocument();
  });

  it("load more that fails says so and can retry", async () => {
    serve();
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    server.use(http.get(`${BASE}/activity`, ({ request }) => (new URL(request.url).searchParams.get("before") ? HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) : HttpResponse.json(desc1 as ActivityResponse))));
    await userEvent.click(screen.getByRole("button", { name: copy.activity.more }));
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.activity.more })).toBeEnabled();
  });

  it("falls back to since pages and reverses", async () => {
    const urls: URL[] = [];
    server.use(
      http.get(`${BASE}/today`, () => HttpResponse.json(todayJson)),
      http.get(`${BASE}/checkins`, () => HttpResponse.json({ items: [] })),
      http.get(`${BASE}/activity`, ({ request }) => {
        const u = new URL(request.url);
        urls.push(u);
        const since = u.searchParams.get("since");
        if (since === null) return HttpResponse.json(asc as ActivityResponse); // before R4a: oldest first, no next_before
        if (since === asc.next_since) return HttpResponse.json({ items: [], next_since: null, next_before: null });
        return HttpResponse.json(asc as ActivityResponse);
      }),
    );
    renderWithProviders(<Activity />);
    expect(await screen.findByText("‘장보기’를 내일로 옮겼어요")).toBeInTheDocument();
    const sinces = urls.filter((u) => u.searchParams.get("since") !== null);
    expect(sinces[0].searchParams.get("limit")).toBe("200");
    expect(sinces[0].searchParams.get("since")).toBe("2026-10-17T11:00:00Z"); // 7 days before now
    expect(sinces.some((u) => u.searchParams.get("since") === asc.next_since)).toBe(true);
    const a = screen.getByText("‘장보기’를 내일로 옮겼어요");
    const b = screen.getByText("‘치과 예약’을 더했어요");
    expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy.activity.more })).toBeNull();
  });

  it("falls back when the BE answers 400", async () => {
    const urls: URL[] = [];
    server.use(
      http.get(`${BASE}/today`, () => HttpResponse.json(todayJson)),
      http.get(`${BASE}/checkins`, () => HttpResponse.json({ items: [] })),
      http.get(`${BASE}/activity`, ({ request }) => {
        const u = new URL(request.url);
        urls.push(u);
        if (u.searchParams.get("order") === "desc") return bad();
        return HttpResponse.json(u.searchParams.get("since") === asc.next_since ? { items: [], next_since: null, next_before: null } : (asc as ActivityResponse));
      }),
    );
    renderWithProviders(<Activity />);
    expect(await screen.findByText("‘치과 예약’을 더했어요")).toBeInTheDocument();
    expect(urls.some((u) => u.searchParams.get("since") !== null)).toBe(true);
    const a = screen.getByText("‘장보기’를 내일로 옮겼어요");
    const b = screen.getByText("‘치과 예약’을 더했어요");
    expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("confirm block on top from pending checkins", async () => {
    serve({ checkins: () => HttpResponse.json(checkinsToday) });
    server.use(http.get(`${BASE}/checkins/:id`, ({ params }) => HttpResponse.json({ ...checkin341, id: Number(params.id) })));
    renderWithProviders(<Activity />);
    expect(await screen.findByText("‘장보기’를 할 일에서 뺄까요?")).toBeInTheDocument();
    const heading = screen.getByRole("heading", { name: copy.activity.needsConfirm });
    const first = await screen.findByText("‘장보기’를 내일로 옮겼어요");
    expect(heading.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("no confirm block when nothing is pending", async () => {
    serve();
    renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    expect(screen.queryByRole("heading", { name: copy.activity.needsConfirm })).toBeNull();
  });

  it("no remaining-time text", async () => {
    serve();
    const { container } = renderWithProviders(<Activity />);
    await screen.findByText("‘장보기’를 내일로 옮겼어요");
    expect(container.textContent).not.toMatch(/남았|남은|까지|분 후|시간 후|마감/);
  });

  it("shows empty line when there is nothing", async () => {
    serve({ first: () => HttpResponse.json({ items: [], next_since: null, next_before: null }) });
    renderWithProviders(<Activity />);
    expect(await screen.findByText(copy.activity.empty)).toBeInTheDocument();
  });

  it("offline shows later", async () => {
    serve({ first: () => HttpResponse.error(), checkins: () => HttpResponse.error() });
    renderWithProviders(<Activity />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.later)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.activity.undo })).toBeNull();
  });

  it("offline connection disables everything even when /activity answers", async () => {
    serve({ checkins: () => HttpResponse.json(checkinsToday) });
    renderWithProviders(<Activity />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.later)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 200));
    expect(screen.queryByRole("button", { name: copy.activity.undo })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.activity.more })).toBeNull();
    expect(screen.queryByRole("heading", { name: copy.activity.needsConfirm })).toBeNull();
    expect(screen.queryByText("‘장보기’를 내일로 옮겼어요")).toBeNull();
  });

  it("unauthorized points to settings", async () => {
    serve({ first: () => new HttpResponse(null, { status: 401 }) });
    renderWithProviders(<Activity />);
    expect(await screen.findByRole("link", { name: copy.errors.goSettings })).toBeInTheDocument();
  });

  it("other errors show a block error with retry", async () => {
    serve({ first: () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) });
    renderWithProviders(<Activity />);
    expect(await screen.findByRole("button", { name: copy.errors.retry })).toBeInTheDocument();
  });
});

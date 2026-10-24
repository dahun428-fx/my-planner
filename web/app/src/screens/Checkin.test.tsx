import "fake-indexeddb/auto";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckinDetail, Today } from "../api/types.gen";
import { chatSheetChunk } from "../chat/loadChatSheet";
import { copy } from "../lib/copy";
import { serveChat, serveHistory, sse, sseResponse } from "../test/chat";
import answeredJson from "../test/fixtures/checkin-341-answered.json";
import briefJson from "../test/fixtures/checkin-340-brief.json";
import missedJson from "../test/fixtures/checkin-341-missed.json";
import pendingJson from "../test/fixtures/checkin-341.json";
import todayJson from "../test/fixtures/today.json";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { Checkin } from "./Checkin";

const pending = pendingJson as CheckinDetail;
const answered = answeredJson as CheckinDetail;
const missed = missedJson as CheckinDetail;
const brief = briefJson as CheckinDetail;
const today = todayJson as Today;

// 18:10 in Seoul: inside the 341 reply window (until 20:00).
const NOW = Date.parse("2026-10-24T09:10:00Z");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"], shouldAdvanceTime: true });
  vi.setSystemTime(NOW);
});

afterEach(async () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  await clear();
});

function serve(c: CheckinDetail = pending, t: Today = today) {
  const hits = { checkin: 0, today: 0 };
  server.use(
    http.get(`${BASE}/checkins/${c.id}`, () => {
      hits.checkin += 1;
      return HttpResponse.json(c);
    }),
    http.get(`${BASE}/today`, () => {
      hits.today += 1;
      return HttpResponse.json(t);
    }),
  );
  return hits;
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

const textAnswer = (conv: number) =>
  sse([
    { type: "start", messageId: "m-1", messageMetadata: { conversation_id: conv, channel: "app", kind: "chat", checkin_id: 341 } },
    { type: "start-step" },
    { type: "text-start", id: "t1" },
    { type: "text-delta", id: "t1", delta: "네, 알겠어요" },
    { type: "text-end", id: "t1" },
    { type: "finish-step" },
    { type: "finish", messageMetadata: { conversation_id: conv, channel: "app", kind: "chat" } },
    "[DONE]",
  ]);

const input = () => screen.findByRole("textbox", { name: copy.chat.inputLabel });

describe("Checkin", () => {
  it("renders loop name and delivery", async () => {
    serve();
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByRole("heading", { level: 1, name: "저녁 체크인" })).toBeInTheDocument();
    expect(screen.getByText("18:00에 보냄 · 앱 알림으로 받음")).toBeInTheDocument();
    expect(screen.getByText(pending.text)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.checkin.back })).toHaveAttribute("href", "/");
    expect(screen.getByText(copy.checkin.canReply)).toBeInTheDocument();
  });

  it("no deadline shown", async () => {
    serve();
    renderWithProviders(<Checkin id={341} />);
    await screen.findByRole("heading", { level: 1, name: "저녁 체크인" });
    await screen.findAllByText(copy.todos.tomorrow);
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("20:00"); // reply_until in Seoul time
    expect(text).not.toMatch(/\d+\s*(분|시간)\s*(뒤|남)|남은 시간|마감/);
  });

  it("cards render as parts", async () => {
    serve();
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText("‘장보기’를 할 일에서 뺄까요?")).toBeInTheDocument();
  });

  it("evening shows open todos with tomorrow and done", async () => {
    serve();
    const bodies = actions(() => applied());
    const user = userEvent.setup();
    renderWithProviders(<Checkin id={341} />);
    const shop = (await screen.findByText("장보기", { selector: "li *" })).closest("li") as HTMLElement;
    expect(within(shop).getByRole("button", { name: copy.checkin.tomorrowLabel("장보기") })).toBeInTheDocument();
    // A finished one is grey text, not a button.
    const laundry = screen.getByText("빨래 널기").closest("li") as HTMLElement;
    expect(within(laundry).getByText(copy.checkin.done)).toBeInTheDocument();
    expect(within(laundry).queryByRole("button")).toBeNull();

    await user.click(within(shop).getByRole("button", { name: copy.checkin.tomorrowLabel("장보기") }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "move_task", args: { id: 13, planned_for: "2026-10-25" } });

    await user.click(within(shop).getByRole("button", { name: copy.checkin.completeLabel("장보기") }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "complete_task", args: { id: 13 } });
    expect(bodies[0].client_msg_id).not.toBe(bodies[1].client_msg_id);
  });

  it("double tap sends one request and reads again after the answer", async () => {
    const hits = serve();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const bodies = actions(async () => {
      await gate;
      return applied();
    });
    const user = userEvent.setup();
    renderWithProviders(<Checkin id={341} />);
    const btn = await screen.findByRole("button", { name: copy.checkin.completeLabel("장보기") });
    await user.dblClick(btn);
    release();
    await waitFor(() => expect(hits.today).toBeGreaterThan(1));
    expect(bodies).toHaveLength(1);
  });

  it("a conflict or a confirm question is said and the list is read again", async () => {
    const hits = serve();
    let n = 0;
    actions(() => {
      n += 1;
      return n === 1
        ? HttpResponse.json({ error: { code: "conflict", message: "x" } }, { status: 409 })
        : HttpResponse.json({ status: "needs_confirm", confirm_token: "t", summary: "정말요?", expires_at: "2026-10-24T10:00:00Z" });
    });
    const user = userEvent.setup();
    renderWithProviders(<Checkin id={341} />);
    const btn = await screen.findByRole("button", { name: copy.checkin.completeLabel("장보기") });
    const before = hits.today;
    await user.click(btn);
    expect(await screen.findByText(copy.actions.failed)).toBeInTheDocument();
    await waitFor(() => expect(hits.today).toBeGreaterThan(before));
    const afterConflict = hits.today;
    await user.click(screen.getByRole("button", { name: copy.checkin.completeLabel("장보기") }));
    await waitFor(() => expect(n).toBe(2));
    await waitFor(() => expect(hits.today).toBeGreaterThan(afterConflict));
    expect(screen.getAllByText(copy.actions.failed).length).toBeGreaterThan(0);
  });

  it("brief has no todo block", async () => {
    const hits = serve(brief);
    renderWithProviders(<Checkin id={340} />);
    expect(await screen.findByRole("heading", { level: 1, name: "아침 브리핑" })).toBeInTheDocument();
    expect(screen.getByText("텔레그램으로 받음", { exact: false })).toBeInTheDocument();
    expect(await screen.findByText("오늘 일정")).toBeInTheDocument();
    expect(screen.queryByText(copy.checkin.todosHeading)).toBeNull();
    expect(screen.queryByRole("button", { name: copy.checkin.tomorrowLabel("장보기") })).toBeNull();
    expect(hits.today).toBe(0);
  });

  it("reply sends checkin_id", async () => {
    serve({ ...pending, conversation_ids: { app: 44, telegram: null } });
    serveHistory({ messages: { 44: [{ id: "m-44-1", at: "2026-10-24T09:00:05Z", speaker: "secretary", text: pending.text }] } });
    const bodies = serveChat(() => sseResponse(textAnswer(44)));
    const user = userEvent.setup();
    renderWithProviders(<Checkin id={341} />);
    await user.type(await input(), "3점이요");
    const send = screen.getByRole("button", { name: copy.chat.send });
    await waitFor(() => expect(send).toBeEnabled());
    await user.click(send);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ checkin_id: 341, conversation_id: 44 });
    expect(await screen.findByText("네, 알겠어요")).toBeInTheDocument();
  });

  it("loads that run's conversation not latest", async () => {
    serve({ ...pending, conversation_ids: { app: 44, telegram: null } });
    const seen = serveHistory({
      conversations: [{ id: 99, last_message_at: "2026-10-24T09:30:00Z" }],
      messages: {
        44: [{ id: "m-44-1", at: "2026-10-24T09:00:05Z", speaker: "secretary", text: "이 회차의 대화예요" }],
        99: [{ id: "m-99-1", at: "2026-10-24T09:30:00Z", speaker: "secretary", text: "다른 대화예요" }],
      },
    });
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText("이 회차의 대화예요")).toBeInTheDocument();
    expect(screen.queryByText("다른 대화예요")).toBeNull();
    expect(seen.conversations).toBe(0);
    expect(seen.messages).toEqual([44]);
  });

  it("starts empty when the run has no conversation yet", async () => {
    serve();
    const seen = serveHistory({ conversations: [{ id: 99, last_message_at: "2026-10-24T09:30:00Z" }], messages: { 99: [{ id: "m-99-1", at: "2026-10-24T09:30:00Z", speaker: "secretary", text: "다른 대화예요" }] } });
    const bodies = serveChat(() => sseResponse(textAnswer(46)));
    const user = userEvent.setup();
    renderWithProviders(<Checkin id={341} />);
    await user.type(await input(), "네");
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.send })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ checkin_id: 341, conversation_id: null });
    expect(seen.conversations).toBe(0);
    expect(screen.queryByText("다른 대화예요")).toBeNull();
  });

  it("answered shows channel and keeps cards", async () => {
    serve(answered);
    serveHistory({ messages: { 44: [] } });
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText(copy.checkin.answeredVia(copy.channels.telegram))).toBeInTheDocument();
    expect(screen.queryByText(copy.checkin.canReply)).toBeNull();
    expect(await screen.findByText("‘장보기’를 할 일에서 뺄까요?")).toBeInTheDocument();
    expect(screen.getByText("18:00에 보냄 · 앱 알림과 텔레그램으로 받음")).toBeInTheDocument();
  });

  it("missed shows 지나감 and keeps input", async () => {
    serve(missed);
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText(copy.checkin.passed)).toBeInTheDocument();
    const box = await input();
    await waitFor(() => expect(box).toBeEnabled());
    expect(screen.queryByText(copy.checkin.canReply)).toBeNull();
  });

  it("turns passed when window ends while open", async () => {
    serve({ ...pending, reply_until: "2026-10-24T09:10:30Z" }); // 30 s from NOW
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText(copy.checkin.canReply)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    expect(screen.getByText(copy.checkin.passed)).toBeInTheDocument();
    expect(screen.queryByText(copy.checkin.canReply)).toBeNull();
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeInTheDocument());
  });

  it("bad id redirects", async () => {
    serve();
    const { router } = renderWithProviders(<Checkin id={Number.NaN} />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
  });

  it("offline shows frame only", async () => {
    const hits = { today: 0 };
    server.use(
      http.get(`${BASE}/checkins/341`, () => HttpResponse.error()),
      http.get(`${BASE}/today`, () => {
        hits.today += 1;
        return HttpResponse.error();
      }),
    );
    renderWithProviders(<Checkin id={341} />, { conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.checkin.back })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "저녁 체크인" })).toBeNull();
    expect(screen.queryByText(pending.text)).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByText(copy.checkin.todosHeading)).toBeNull();
    expect(hits.today).toBe(0);
  });

  it("a failed chat chunk says so and retries", async () => {
    serve();
    const load = vi.spyOn(chatSheetChunk, "load").mockRejectedValueOnce(new Error("chunk"));
    const user = userEvent.setup();
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText(copy.checkin.replyFailed)).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: copy.errors.retry }));
    expect(await input()).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("answered without a channel says so without guessing", async () => {
    serve({ ...answered, answered_via: null });
    serveHistory({ messages: { 44: [] } });
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText(copy.checkin.answered)).toBeInTheDocument();
    expect(screen.queryByText(copy.checkin.answeredVia(copy.channels.app))).toBeNull();
  });

  it("status reads again after a reply finishes", async () => {
    const hits = serve({ ...pending, conversation_ids: { app: 44, telegram: null } });
    serveHistory({ messages: { 44: [] } });
    serveChat(() => sseResponse(textAnswer(44)));
    const user = userEvent.setup();
    renderWithProviders(<Checkin id={341} />);
    await user.type(await input(), "네");
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.send })).toBeEnabled());
    const before = hits.checkin;
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await screen.findByText("네, 알겠어요");
    await waitFor(() => expect(hits.checkin).toBeGreaterThan(before));
  });

  it("keeps the last to-dos, disabled, when the connection drops", async () => {
    vi.useRealTimers(); // the polling interval has to be fake too
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
    serve();
    renderWithProviders(<Checkin id={341} />);
    await screen.findByRole("button", { name: copy.checkin.completeLabel("장보기") });
    server.use(http.get(`${BASE}/today`, () => HttpResponse.error()), http.get(`${BASE}/checkins/341`, () => HttpResponse.error()));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16_000);
    });
    await screen.findByText(copy.offline.lead, {}, { timeout: 3000 });
    expect(screen.getByRole("button", { name: copy.checkin.completeLabel("장보기") })).toBeDisabled();
  });

  it("an unknown check-in is said, with retry", async () => {
    server.use(http.get(`${BASE}/checkins/341`, () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 })));
    renderWithProviders(<Checkin id={341} />);
    expect(await screen.findByText(copy.errors.block("not_found"), { exact: false })).toBeInTheDocument();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Memo } from "../api/types.gen";
import { copy } from "../lib/copy";
import { clearPhotoCache } from "../lib/photoCache";
import { PhotoUnopenable, shrinkPhoto } from "../lib/shrinkPhoto";
import { renderWithProviders } from "../test/render";
import { healthAnswers } from "../test/handlers";
import { BASE, server } from "../test/server";
import { MemoEditor } from "./MemoEditor";

// SP10 12장 앱 (메모 쪽): 사진 줄과 보기, 넣을 자리, 읽기 상태에서 끝남, 실패 뒤 "다시 읽기", 8장 응답→문구.
// jsdom has no image decoder: shrinkPhoto (its own tests fake the bitmap) stands in here.
vi.mock("../lib/shrinkPhoto", async (orig) => {
  const real = await orig<typeof import("../lib/shrinkPhoto")>();
  return {
    ...real,
    shrinkPhoto: vi.fn(async () => ({
      image: new Blob([new Uint8Array(300)], { type: "image/jpeg" }),
      thumb: new Blob([new Uint8Array(30)], { type: "image/jpeg" }),
    })),
  };
});

const MEMO: Memo = {
  id: 7,
  title: "읽을 책",
  body: "읽을 책\n- 끝 줄",
  area: null,
  pinned: false,
  origin: "user",
  created_at: "2026-10-25T05:00:00Z",
  updated_at: "2026-10-25T05:02:00.123456Z",
  photos: [],
};

interface Sent {
  action: string;
  args: Record<string, unknown>;
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

/** The fake BE: memo 7, /actions, POST /photos (ids from 12), its read and GET /photos. */
function fakeBe(opts: { memo?: Memo; read?: (id: number) => Promise<Response> | Response; upload?: () => Response } = {}) {
  const sent: Sent[] = [];
  const gets: string[] = [];
  let nextId = 12;
  const order: string[] = [];
  server.use(
    http.get(`${BASE}/memos/:id`, () => HttpResponse.json(opts.memo ?? MEMO)),
    http.post(`${BASE}/actions`, async ({ request }) => {
      const b = (await request.json()) as Sent;
      sent.push({ action: b.action, args: b.args });
      order.push(b.action);
      const body = String(b.args.body ?? MEMO.body);
      if (b.action === "attach_photo") return HttpResponse.json({ status: "applied", activity_id: 901, undo_id: null, result: { ...b.args, position: 0 }, confirmation: copy.photos.attached });
      if (b.action === "detach_photo") return HttpResponse.json({ status: "applied", activity_id: 902, undo_id: 902, result: { ...b.args, detached: true }, confirmation: copy.photos.detached });
      const result = { id: 7, title: body.split("\n")[0], area: null, pinned: false, updated_at: `2026-10-25T05:1${sent.length}:00Z` };
      const n = Array.isArray(b.args.photo_ids) ? b.args.photo_ids.length : 0;
      const confirmation = b.action === "create_memo" ? (n ? copy.photos.created(result.title, n) : copy.memos.confirm.created(result.title)) : copy.memos.confirm.updated(result.title);
      return HttpResponse.json({ status: "applied", activity_id: 900 + sent.length, undo_id: b.action === "create_memo" ? 900 : null, result, confirmation });
    }),
    http.post(`${BASE}/photos`, () => {
      order.push("upload");
      return opts.upload?.() ?? HttpResponse.json({ id: nextId++, width: 2048, height: 1536, bytes: 300 }, { status: 201 });
    }),
    http.post(`${BASE}/photos/:id/read`, async ({ params }) => {
      order.push("read");
      return opts.read ? opts.read(Number(params.id)) : HttpResponse.json({ text: "사진 속 글", unreadable: false });
    }),
    http.get(`${BASE}/photos/:id`, ({ request, params }) => {
      gets.push(`${params.id}:${new URL(request.url).searchParams.get("size")}`);
      return new HttpResponse(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), { headers: { "Content-Type": "image/jpeg" } });
    }),
  );
  return { sent, gets, order };
}

const picture = () => new File([new Uint8Array(50)], "IMG_0001.jpg", { type: "image/jpeg" });
const fileInput = () => document.querySelector('input[type="file"]') as HTMLInputElement;
const box = () => screen.getByRole("textbox", { name: copy.memos.body }) as HTMLTextAreaElement;

/** Presses "사진" with the caret at `at` and picks a photo. */
async function pick(at?: number) {
  if (at !== undefined) box().setSelectionRange(at, at);
  await userEvent.click(screen.getByRole("button", { name: copy.photos.button }));
  await userEvent.upload(fileInput(), picture());
}

beforeEach(() => clearPhotoCache());
afterEach(() => vi.mocked(shrinkPhoto).mockClear());

describe("MemoEditor photos (SP10 7.1)", () => {
  it("a new memo: the photo joins the row above the body, is read, its text goes in at the caret, and the save sends photo_ids", async () => {
    const read = deferred<Response>();
    const be = fakeBe({ read: () => read.promise });
    renderWithProviders(<MemoEditor id={null} />, { route: "/memos/view/?new=1" });
    await userEvent.type(box(), "책 메모");
    await pick();
    // The row: one small photo, shown from the bytes just sent (the BE gives it out only once attached).
    const strip = await screen.findByRole("list", { name: copy.photos.strip });
    const img = within(strip).getByRole("button", { name: copy.photos.photo(1, 1) }).querySelector("img");
    await waitFor(() => expect(img?.getAttribute("src")).toMatch(/^blob:/));
    expect(await screen.findByText(copy.photos.reading)).toBeInTheDocument();
    // Writing goes on while it is read.
    expect(box()).not.toHaveAttribute("readonly");
    read.resolve(HttpResponse.json({ text: "사진 속 글", unreadable: false }));
    await waitFor(() => expect(box()).toHaveValue("책 메모\n사진 속 글"));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.inserted));
    expect(screen.queryByText(copy.photos.reading)).toBeNull();
    await waitFor(() => expect(be.sent.some((s) => s.action === "create_memo")).toBe(true), { timeout: 2500 });
    expect(be.sent.find((s) => s.action === "create_memo")!.args).toEqual({ body: "책 메모\n사진 속 글", photo_ids: [12] });
    expect(be.sent.some((s) => s.action === "attach_photo")).toBe(false);
    expect(be.gets).toEqual([]);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.created("책 메모", 1)));
  });

  it("a saved memo: the photo is attached at once, then read; the text goes where the caret was even after typing before it", async () => {
    const read = deferred<Response>();
    const be = fakeBe({ read: () => read.promise });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(5); // the start of "- 끝 줄"
    await waitFor(() => expect(be.order).toEqual(["upload", "attach_photo", "read"]));
    expect(be.sent[0].args).toEqual({ memo_id: 7, photo_id: 12 });
    // Typing at the start while the photo is read moves the anchor along.
    box().focus();
    box().setSelectionRange(0, 0);
    await userEvent.keyboard("새 ");
    read.resolve(HttpResponse.json({ text: "책 한 쪽", unreadable: false }));
    await waitFor(() => expect(box()).toHaveValue("새 읽을 책\n책 한 쪽\n- 끝 줄"));
    await waitFor(() => expect(be.sent.some((s) => s.action === "update_memo" && s.args.body === "새 읽을 책\n책 한 쪽\n- 끝 줄")).toBe(true), { timeout: 2500 });
    // update_memo carries no photos (11장).
    for (const s of be.sent.filter((x) => x.action === "update_memo")) expect(s.args).not.toHaveProperty("photo_ids");
  });

  it("완료 while it is read: back to reading, and when the text comes it goes in and is saved at once", async () => {
    const read = deferred<Response>();
    const be = fakeBe({ read: () => read.promise });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(MEMO.body.length);
    await screen.findByText(copy.photos.reading);
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.done }));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(screen.getByText(copy.photos.reading)).toBeInTheDocument();
    const before = be.sent.length;
    read.resolve(HttpResponse.json({ text: "읽은 글", unreadable: false }));
    await waitFor(() => expect(be.sent.length).toBe(before + 1));
    expect(be.sent.at(-1)).toMatchObject({ action: "update_memo", args: { id: 7, body: `${MEMO.body}\n읽은 글` } });
    await waitFor(() => expect(document.querySelector("main")).toHaveTextContent("읽은 글"));
  });

  it("a read that does not go through leaves the photo and offers 다시 읽기", async () => {
    let reads = 0;
    fakeBe({
      read: () => (++reads === 1 ? HttpResponse.json({ error: { code: "unavailable", message: "x" } }, { status: 503 }) : HttpResponse.json({ text: "둘째 시도", unreadable: false })),
    });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(MEMO.body.length);
    const again = await screen.findByRole("button", { name: copy.photos.reread });
    expect(screen.getByRole("button", { name: copy.photos.photo(1, 1) })).toBeInTheDocument();
    expect(box()).toHaveValue(MEMO.body);
    await userEvent.click(again);
    await waitFor(() => expect(box()).toHaveValue(`${MEMO.body}\n둘째 시도`));
    expect(screen.queryByRole("button", { name: copy.photos.reread })).toBeNull();
  });

  it("unreadable: no text goes in, and it says the photo stays", async () => {
    fakeBe({ read: () => HttpResponse.json({ text: "", unreadable: true }) });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(2);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.unreadable));
    expect(box()).toHaveValue(MEMO.body);
    expect(screen.getByRole("button", { name: copy.photos.photo(1, 1) })).toBeInTheDocument();
  });

  it("429 photo_read_limit says so and offers no 다시 읽기", async () => {
    fakeBe({ read: () => HttpResponse.json({ error: { code: "photo_read_limit", message: "x" } }, { status: 429 }) });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(2);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.readLimit));
    expect(screen.queryByRole("button", { name: copy.photos.reread })).toBeNull();
    expect(screen.queryByText(copy.photos.reading)).toBeNull();
    expect(screen.getByRole("button", { name: copy.photos.photo(1, 1) })).toBeInTheDocument();
  });

  it("over 20,000 code points the rest is left out, and it says so", async () => {
    const long = { ...MEMO, body: `${"가".repeat(19_995)}` };
    fakeBe({ memo: long, read: () => HttpResponse.json({ text: "0123456789", unreadable: false }) });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText(long.body));
    await pick(long.body.length);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.cut));
    expect(box().value).toBe(`${long.body}\n0123`);
  });

  it.each([
    ["429 photo_limit", () => HttpResponse.json({ error: { code: "photo_limit", message: "x" } }, { status: 429 }), copy.photos.dailyLimit],
    ["413", () => HttpResponse.json({ error: { code: "photo_too_large", message: "x" } }, { status: 413 }), copy.photos.tooLarge],
    ["415", () => HttpResponse.json({ error: { code: "photo_not_jpeg", message: "x" } }, { status: 415 }), copy.photos.cannotOpen],
    ["507", () => HttpResponse.json({ error: { code: "disk_full", message: "x" } }, { status: 507 }), copy.photos.diskFull],
  ])("an upload refused with %s: no photo, and the 8장 sentence", async (_what, upload, text) => {
    const be = fakeBe({ upload });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(2);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(text));
    expect(screen.queryByRole("list", { name: copy.photos.strip })).toBeNull();
    expect(be.sent).toEqual([]);
  });

  it("the laptop off (network failure): the SP5 sentence, and nothing is kept to send later", async () => {
    let tries = 0;
    const be = fakeBe({
      upload: () => {
        tries++;
        return HttpResponse.error();
      },
    });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    server.use(healthAnswers.unreachable());
    await pick(2);
    expect(await screen.findByText(copy.actions.offline)).toBeInTheDocument();
    expect(tries).toBe(2); // once more with the same client_msg_id, then no more (ADR 0009: no queue)
    expect(screen.queryByRole("list", { name: copy.photos.strip })).toBeNull();
    expect(be.sent).toEqual([]);
  });

  it("a photo that cannot be opened on the device says so and sends nothing", async () => {
    vi.mocked(shrinkPhoto).mockRejectedValueOnce(new PhotoUnopenable());
    const be = fakeBe();
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(2);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.cannotOpen));
    expect(be.order).toEqual([]);
  });

  it("409 photo_in_use on attach: the photo leaves the row and it says so", async () => {
    const be = fakeBe();
    server.use(
      http.post(`${BASE}/actions`, () => HttpResponse.json({ error: { code: "photo_in_use", message: "x" } }, { status: 409 })),
    );
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(2);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.inUse));
    expect(screen.queryByRole("list", { name: copy.photos.strip })).toBeNull();
    expect(be.order).not.toContain("read");
  });

  it("422 too_many_photos on attach is the memo's 10 limit", async () => {
    fakeBe();
    server.use(
      http.post(`${BASE}/actions`, () => HttpResponse.json({ status: "rejected", activity_id: null, error: { code: "too_many_photos", message: "x" } }, { status: 422 })),
    );
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await pick(2);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.memoLimit));
  });

  it("a memo with 10 photos: 사진 is dimmed and says the limit", async () => {
    const ten = { ...MEMO, photos: Array.from({ length: 10 }, (_, i) => ({ id: 100 + i, width: 10, height: 10 })) };
    const be = fakeBe({ memo: ten });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    const button = screen.getByRole("button", { name: copy.photos.button });
    expect(button).toHaveAttribute("aria-disabled", "true");
    const clicked = vi.spyOn(fileInput(), "click");
    await userEvent.click(button);
    expect(clicked).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(copy.photos.memoLimit);
    expect(be.order).toEqual([]);
  });
});

describe("photo row and viewer of a saved memo (SP10 7.1, 7.3)", () => {
  const WITH = { ...MEMO, photos: [{ id: 3, width: 2048, height: 1536 }, { id: 4, width: 1536, height: 2048 }] };

  it("opens with the memo's photos as small ones; a press shows it big, left and right go through them", async () => {
    const be = fakeBe({ memo: WITH });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    const strip = await screen.findByRole("list", { name: copy.photos.strip });
    expect(within(strip).getAllByRole("button")).toHaveLength(2);
    await waitFor(() => expect(be.gets).toEqual(expect.arrayContaining(["3:thumb", "4:thumb"])));
    // A press on the row does not start writing.
    await userEvent.click(within(strip).getByRole("button", { name: copy.photos.photo(1, 2) }));
    expect(screen.queryByRole("textbox")).toBeNull();
    const viewer = screen.getByRole("dialog", { name: copy.photos.viewer });
    await waitFor(() => expect(be.gets).toContain("3:full"));
    await userEvent.click(within(viewer).getByRole("button", { name: copy.photos.next }));
    await waitFor(() => expect(be.gets).toContain("4:full"));
    expect(within(viewer).getByLabelText(copy.photos.photo(2, 2))).toBeInTheDocument();
    expect(within(viewer).queryByRole("button", { name: copy.photos.next })).toBeNull();
    await userEvent.keyboard("{ArrowLeft}");
    expect(within(viewer).getByLabelText(copy.photos.photo(1, 2))).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("메모에서 빼기 sends detach_photo and toasts with 되돌리기; the undo puts it back", async () => {
    let photos = WITH.photos;
    const be = fakeBe();
    server.use(
      http.get(`${BASE}/memos/:id`, () => HttpResponse.json({ ...WITH, photos })),
      http.post(`${BASE}/activity/:id/undo`, () => {
        photos = WITH.photos;
        return HttpResponse.json({ status: "undone", confirmation: "✓ 되돌렸어요" });
      }),
    );
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(within(await screen.findByRole("list", { name: copy.photos.strip })).getByRole("button", { name: copy.photos.photo(1, 2) }));
    const viewer = screen.getByRole("dialog", { name: copy.photos.viewer });
    photos = [WITH.photos[1]];
    await userEvent.click(within(viewer).getByRole("button", { name: copy.photos.detach }));
    await waitFor(() => expect(be.sent).toEqual([{ action: "detach_photo", args: { memo_id: 7, photo_id: 3 } }]));
    const toast = screen.getByRole("status");
    await waitFor(() => expect(toast).toHaveTextContent(copy.photos.detached));
    expect(within(screen.getByRole("list", { name: copy.photos.strip })).getAllByRole("button")).toHaveLength(1);
    await userEvent.click(within(toast).getByRole("button", { name: copy.activity.undo }));
    await waitFor(() => expect(within(screen.getByRole("list", { name: copy.photos.strip })).getAllByRole("button")).toHaveLength(2));
  });

  it("offline: the photos are grey cells and the viewer has no 메모에서 빼기", async () => {
    server.use(http.get(`${BASE}/memos/:id`, () => HttpResponse.json(WITH)), http.get(`${BASE}/photos/:id`, () => HttpResponse.error()));
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7", conn: "offline" });
    const strip = await screen.findByRole("list", { name: copy.photos.strip });
    await screen.findByText(copy.offline.lead);
    expect(strip.querySelectorAll("img")).toHaveLength(0);
    expect(strip.querySelectorAll("[data-photo]")).toHaveLength(2);
    await userEvent.click(within(strip).getByRole("button", { name: copy.photos.photo(1, 2) }));
    expect(within(screen.getByRole("dialog")).queryByRole("button", { name: copy.photos.detach })).toBeNull();
  });

  it("a memo with no photos has no row", async () => {
    fakeBe();
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await screen.findByText("읽을 책");
    expect(screen.queryByRole("list", { name: copy.photos.strip })).toBeNull();
  });
});

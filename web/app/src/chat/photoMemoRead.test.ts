import type { UIMessage } from "ai";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import type { Memo } from "../api/types.gen";
import { saveConn } from "../lib/connection";
import { copy } from "../lib/copy";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { fillPhotoMemo, photoMemoOf, readIntoPhotoMemo } from "./photoMemoRead";

// SP10 16장 "글자 읽기" 퀵 칩: 사진마다 읽고, 그 메모 본문 "사진" 자리에(고쳤으면 끝에 빈 줄 하나 뒤에)
// 넣어 update_memo(409면 다시 읽고 한 번 더).
const conn = { beUrl: TEST_BE_URL, token: TEST_TOKEN };

const memo = (over: Partial<Memo> = {}): Memo => ({
  id: 40,
  title: "사진",
  body: "사진",
  area: null,
  pinned: false,
  origin: "user",
  created_at: "2026-10-31T01:00:00Z",
  updated_at: "2026-10-31T01:00:00.000001Z",
  photos: [{ id: 12, width: 2048, height: 1536 }, { id: 13, width: 2048, height: 1536 }],
  ...over,
});

interface Sent {
  action: string;
  args: Record<string, unknown>;
}

/** GET /memos/40 (the given bodies in turn, the last repeats), the reads, and /actions (the given answers in turn). */
function be(opts: {
  memos?: Memo[];
  reads?: Record<number, () => Response>;
  actions?: ((n: number, s: Sent) => Response | undefined)[];
} = {}) {
  const sent: Sent[] = [];
  const reads: number[] = [];
  let gets = 0;
  server.use(
    http.get(`${BASE}/memos/:id`, () => {
      const list = opts.memos ?? [memo()];
      return HttpResponse.json(list[Math.min(gets++, list.length - 1)]);
    }),
    http.post(`${BASE}/photos/:id/read`, ({ params }) => {
      const id = Number(params.id);
      reads.push(id);
      return opts.reads?.[id]?.() ?? HttpResponse.json({ text: `글${id}`, unreadable: false });
    }),
    http.post(`${BASE}/actions`, async ({ request }) => {
      const b = (await request.json()) as Sent;
      sent.push({ action: b.action, args: b.args });
      const custom = opts.actions?.[sent.length - 1]?.(sent.length, b);
      if (custom) return custom;
      const body = String(b.args.body);
      const title = body.split("\n")[0];
      return HttpResponse.json({
        status: "applied",
        activity_id: 900 + sent.length,
        undo_id: null,
        result: { id: 40, title, area: null, pinned: false, updated_at: "2026-10-31T01:05:00Z" },
        confirmation: copy.memos.confirm.updated(title),
      });
    }),
  );
  return { sent, reads, gets: () => gets };
}

const conflict = () => HttpResponse.json({ error: { code: "memo_conflict", message: "x" } }, { status: 409 });

beforeEach(() => saveConn(conn));

describe("fillPhotoMemo", () => {
  it("the body 사진 as it is: the read text takes its place", () => {
    expect(fillPhotoMemo(copy.photos.defaultBody, "글1\n\n글2")).toEqual({ body: "글1\n\n글2", cut: false, noRoom: false });
  });

  it("a body changed: the read text goes at the end after one blank line", () => {
    expect(fillPhotoMemo("사진 영수증", "글1")).toEqual({ body: "사진 영수증\n\n글1", cut: false, noRoom: false });
    expect(fillPhotoMemo("사진\n", "글1")).toEqual({ body: "사진\n\n글1", cut: false, noRoom: false });
  });

  it("over 20,000 code points: the rest is left out (cut)", () => {
    const body = "가".repeat(19_995);
    expect(fillPhotoMemo(body, "0123456789")).toEqual({ body: `${body}\n\n012`, cut: true, noRoom: false });
    // Code points, not UTF-16 units: an emoji counts once.
    const emoji = "😀".repeat(19_990);
    expect(fillPhotoMemo(emoji, "0123456789")).toEqual({ body: `${emoji}\n\n01234567`, cut: true, noRoom: false });
    expect(fillPhotoMemo("가".repeat(20_000), "글")).toEqual({ body: "가".repeat(20_000), cut: true, noRoom: true });
  });
});

describe("photoMemoOf", () => {
  const msg = (parts: UIMessage["parts"]): UIMessage => ({ id: "m", role: "assistant", parts });

  it("reads the data-photo-memo part of an answer", () => {
    expect(photoMemoOf(msg([{ type: "data-photo-memo", data: { memo_id: 40, photo_ids: [12, 13] } }]))).toEqual({ memoId: 40, photoIds: [12, 13] });
  });

  it("null without one, or with a part not shaped so", () => {
    expect(photoMemoOf(msg([{ type: "text", text: "x" }]))).toBeNull();
    expect(photoMemoOf(msg([{ type: "data-photo-memo", data: { memo_id: "40", photo_ids: [12] } }]))).toBeNull();
    expect(photoMemoOf(msg([{ type: "data-photo-memo", data: { memo_id: 40, photo_ids: [] } }]))).toBeNull();
  });
});

describe("readIntoPhotoMemo", () => {
  it("reads each photo in order, joins the texts with a blank line and puts them in place of 사진", async () => {
    const b = be();
    const r = await readIntoPhotoMemo(conn, 40, [12, 13]);
    expect(b.reads).toEqual([12, 13]);
    expect(b.sent).toEqual([{ action: "update_memo", args: { id: 40, body: "글12\n\n글13", updated_at: "2026-10-31T01:00:00.000001Z" } }]);
    expect(r).toEqual({ done: true, text: copy.photos.readInto("글12") });
  });

  it("a body changed by hand: the text goes after it, and the toast's title is its first 20", async () => {
    const title = "이십자가넘는아주긴제목입니다정말로길어요요요";
    const b = be({ memos: [memo({ body: `${title}\n메모`, title })] });
    const r = await readIntoPhotoMemo(conn, 40, [12]);
    expect(b.sent[0].args.body).toBe(`${title}\n메모\n\n글12`);
    expect(r).toEqual({ done: true, text: copy.photos.readInto(Array.from(title).slice(0, 20).join("")) });
  });

  it("409 memo_conflict: reads the memo again and tries once more on what is there now", async () => {
    const b = be({
      memos: [memo(), memo({ body: "고친 본문", updated_at: "2026-10-31T01:03:00Z" })],
      actions: [() => conflict()],
    });
    const r = await readIntoPhotoMemo(conn, 40, [12]);
    expect(b.gets()).toBe(2);
    expect(b.sent.map((s) => s.args)).toEqual([
      { id: 40, body: "글12", updated_at: "2026-10-31T01:00:00.000001Z" },
      { id: 40, body: "고친 본문\n\n글12", updated_at: "2026-10-31T01:03:00Z" },
    ]);
    expect(r.done).toBe(true);
    // The photos are read once only.
    expect(b.reads).toEqual([12]);
  });

  it("409 twice: not done (the chip stays), and no third try", async () => {
    const b = be({ actions: [() => conflict(), () => conflict()] });
    const r = await readIntoPhotoMemo(conn, 40, [12]);
    expect(b.sent).toHaveLength(2);
    expect(r).toEqual({ done: false, text: copy.actions.failed });
  });

  it("all unreadable: nothing is written, and the unreadable sentence", async () => {
    const unreadable = () => HttpResponse.json({ text: "", unreadable: true });
    const b = be({ reads: { 12: unreadable, 13: unreadable } });
    const r = await readIntoPhotoMemo(conn, 40, [12, 13]);
    expect(b.sent).toEqual([]);
    expect(r).toEqual({ done: true, text: copy.photos.unreadable });
  });

  it("one of two unreadable: the other's text goes in alone", async () => {
    const b = be({ reads: { 12: () => HttpResponse.json({ text: "", unreadable: true }) } });
    await readIntoPhotoMemo(conn, 40, [12, 13]);
    expect(b.sent[0].args.body).toBe("글13");
  });

  it("a read that does not go through: nothing is written, not done", async () => {
    const b = be({ reads: { 13: () => HttpResponse.json({ error: { code: "unavailable", message: "x" } }, { status: 503 }) } });
    const r = await readIntoPhotoMemo(conn, 40, [12, 13]);
    expect(b.sent).toEqual([]);
    expect(r).toEqual({ done: false, text: copy.actions.failed });
  });

  it("429 photo_read_limit: its own sentence, not done", async () => {
    be({ reads: { 12: () => HttpResponse.json({ error: { code: "photo_read_limit", message: "x" } }, { status: 429 }) } });
    expect(await readIntoPhotoMemo(conn, 40, [12])).toEqual({ done: false, text: copy.photos.readLimit });
  });

  it("over 20,000: what fits goes in, and the cap sentence", async () => {
    const body = "가".repeat(19_995);
    const b = be({ memos: [memo({ body })], reads: { 12: () => HttpResponse.json({ text: "0123456789", unreadable: false }) } });
    const r = await readIntoPhotoMemo(conn, 40, [12]);
    expect(b.sent[0].args.body).toBe(`${body}\n\n012`);
    expect(r).toEqual({ done: true, text: copy.photos.cut });
  });

  it("the text already in the memo (an earlier save applied though its answer was lost): no second update_memo, done", async () => {
    const b = be({ memos: [memo({ body: "영수증\n\n글12\n\n글13", title: "영수증" })] });
    const r = await readIntoPhotoMemo(conn, 40, [12, 13]);
    expect(b.sent).toEqual([]);
    expect(r).toEqual({ done: true, text: copy.photos.readInto("영수증") });
  });

  it("the memo gone (undone): nothing is written, and it says so", async () => {
    const b = be();
    server.use(http.get(`${BASE}/memos/:id`, () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 })));
    const r = await readIntoPhotoMemo(conn, 40, [12]);
    expect(b.sent).toEqual([]);
    expect(r).toEqual({ done: true, text: copy.memos.errors.notFound });
  });
});

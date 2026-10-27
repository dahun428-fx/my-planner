import "fake-indexeddb/auto";
import { keys } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { subscribeResults } from "../lib/connection";
import { clearPhotoCache, holdPhoto, PHOTO_CACHE_MAX, peekPhoto, photoCacheSize, photoKey, putPhoto } from "../lib/photoCache";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { dropLocalPhoto, keepLocalPhoto, photoBlobUrl, readLimitText, readPhoto, uploadFailureText, uploadPhoto } from "./photos";
import type { ApiResult } from "./client";

const conn = { beUrl: TEST_BE_URL, token: TEST_TOKEN };
const jpeg = (n: number) => new Blob([new Uint8Array(n)], { type: "image/jpeg" });
/** Part name → its text, or "file <type>" for a file part. */
function multipart(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  const CRLF = "\r\n";
  const boundary = body.slice(0, body.indexOf(CRLF));
  for (const chunk of body.split(boundary)) {
    const [head, ...rest] = chunk.split(CRLF + CRLF);
    const name = head.match(/name="([^"]+)"/)?.[1];
    if (!name) continue;
    const type = head.match(/Content-Type: (\S+)/i)?.[1];
    const text = rest.join(CRLF + CRLF);
    out[name] = /filename=/.test(head) ? `file ${type}` : text.endsWith(CRLF) ? text.slice(0, -2) : text;
  }
  return out;
}
const err = (status: number, code: string) => HttpResponse.json({ error: { code, message: "x" } }, { status });

afterEach(() => {
  clearPhotoCache();
  vi.restoreAllMocks();
});

describe("uploadPhoto (spec 5.3)", () => {
  it("sends image, thumb, origin and client_msg_id as multipart with the key in the header", async () => {
    const got: { auth: string | null; type: string | null; parts: Record<string, string> }[] = [];
    server.use(
      http.post(`${BASE}/photos`, async ({ request }) => {
        const type = request.headers.get("content-type");
        got.push({ auth: request.headers.get("authorization"), type, parts: multipart(await request.text()) });
        return HttpResponse.json({ id: 12, width: 2048, height: 1536, bytes: 300 }, { status: 201 });
      }),
    );
    const r = await uploadPhoto(conn, { image: jpeg(300), thumb: jpeg(40), origin: "memo", clientMsgId: "c-1" });
    expect(r).toEqual({ kind: "ok", data: { id: 12, width: 2048, height: 1536, bytes: 300 } });
    expect(got).toHaveLength(1);
    expect(got[0].auth).toBe(`Bearer ${TEST_TOKEN}`);
    expect(got[0].type).toMatch(/^multipart\/form-data; boundary=/);
    // (jsdom's Blob reaches Node's fetch without its bytes, so only the part's type is checked here.)
    expect(got[0].parts).toEqual({ image: "file image/jpeg", thumb: "file image/jpeg", origin: "memo", client_msg_id: "c-1" });
  });

  it("a network failure is tried once more with the same client_msg_id", async () => {
    const ids: string[] = [];
    server.use(
      http.post(`${BASE}/photos`, async ({ request }) => {
        ids.push(multipart(await request.text()).client_msg_id);
        return ids.length === 1 ? HttpResponse.error() : HttpResponse.json({ id: 3, width: 10, height: 10, bytes: 9 }, { status: 201 });
      }),
    );
    const r = await uploadPhoto(conn, { image: jpeg(9), thumb: jpeg(3), origin: "memo", clientMsgId: "same" });
    expect(r.kind).toBe("ok");
    expect(ids).toEqual(["same", "same"]);
  });

  it("429 photo_limit is that route's limit: an error with its code, and the connection stays as it is", async () => {
    server.use(http.post(`${BASE}/photos`, () => err(429, "photo_limit")));
    const seen: ApiResult<unknown>[] = [];
    const stop = subscribeResults((r) => seen.push(r));
    const r = await uploadPhoto(conn, { image: jpeg(9), thumb: jpeg(3), origin: "memo", clientMsgId: "c" });
    stop();
    expect(r).toMatchObject({ kind: "error", status: 429, code: "photo_limit" });
    expect(seen.map((s) => s.kind)).toEqual(["error"]);
  });

  it("a 429 of the auth limit is still rate_limited", async () => {
    server.use(http.post(`${BASE}/photos`, () => err(429, "too_many_auth_failures")));
    expect((await uploadPhoto(conn, { image: jpeg(9), thumb: jpeg(3), origin: "memo", clientMsgId: "c" })).kind).toBe("rate_limited");
  });
});

describe("readPhoto (spec 5.4)", () => {
  it("answers text and unreadable", async () => {
    server.use(http.post(`${BASE}/photos/5/read`, () => HttpResponse.json({ text: "책 한 쪽", unreadable: false })));
    expect(await readPhoto(conn, 5)).toEqual({ kind: "ok", data: { text: "책 한 쪽", unreadable: false } });
  });

  it("429 photo_read_limit comes back with its code", async () => {
    server.use(http.post(`${BASE}/photos/5/read`, () => err(429, "photo_read_limit")));
    const r = await readPhoto(conn, 5);
    expect(r).toMatchObject({ kind: "error", status: 429, code: "photo_read_limit" });
    expect(readLimitText(r)).toBe(copy.photos.readLimit);
    expect(readLimitText({ kind: "error", status: 503, code: "unavailable" })).toBeNull();
  });
});

describe("8장 응답 → 문구 (upload)", () => {
  const e = (status: number, code: string): ApiResult<unknown> => ({ kind: "error", status, code });
  it.each([
    [e(413, "photo_too_large"), copy.photos.tooLarge],
    [e(415, "photo_not_jpeg"), copy.photos.cannotOpen],
    [e(422, "photo_unreadable"), copy.photos.cannotOpen],
    [e(429, "photo_limit"), copy.photos.dailyLimit],
    [e(507, "disk_full"), copy.photos.diskFull],
    [e(500, "internal"), copy.photos.uploadFailed],
    [e(0, "timeout"), copy.photos.uploadFailed],
    [{ kind: "offline" } as ApiResult<unknown>, copy.actions.offline],
    [{ kind: "unauthorized" } as ApiResult<unknown>, copy.status.unauthorized],
  ])("%o → %s", (r, text) => {
    expect(uploadFailureText(r)).toBe(text);
  });
});

describe("photoBlobUrl and the memory cache (spec 7.3)", () => {
  const bytes = () => new HttpResponse(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), { headers: { "Content-Type": "image/jpeg", "Cache-Control": "private, no-store" } });
  const tk = (id: number) => photoKey(TEST_BE_URL, id, "thumb");
  const fk = (id: number) => photoKey(TEST_BE_URL, id, "full");

  it("fetches with the Authorization header, no-store, and hands a held blob: address; a second ask is the cache", async () => {
    const asks: { size: string | null; auth: string | null }[] = [];
    server.use(
      http.get(`${BASE}/photos/:id`, ({ request }) => {
        asks.push({ size: new URL(request.url).searchParams.get("size"), auth: request.headers.get("authorization") });
        return bytes();
      }),
    );
    const a = await photoBlobUrl(conn, 9, "thumb");
    expect(a?.url).toMatch(/^blob:/);
    const b = await photoBlobUrl(conn, 9, "thumb");
    expect(b?.url).toBe(a?.url);
    expect(asks).toEqual([{ size: "thumb", auth: `Bearer ${TEST_TOKEN}` }]);
  });

  it("a photo the BE does not give (404) or a network failure is null, and not kept", async () => {
    server.use(http.get(`${BASE}/photos/:id`, ({ params }) => (params.id === "1" ? err(404, "not_found") : HttpResponse.error())));
    expect(await photoBlobUrl(conn, 1, "thumb")).toBeNull();
    expect(await photoBlobUrl(conn, 2, "full")).toBeNull();
    expect(photoCacheSize()).toBe(0);
  });

  it("a full-size photo is revoked as soon as no screen shows it (the viewer closes or moves on)", async () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    server.use(http.get(`${BASE}/photos/:id`, () => bytes()));
    const one = await photoBlobUrl(conn, 5, "full");
    const two = await photoBlobUrl(conn, 5, "full");
    expect(two?.url).toBe(one?.url);
    one!.release();
    expect(revoke).not.toHaveBeenCalled();
    two!.release();
    expect(revoke).toHaveBeenCalledWith(one!.url);
    expect(peekPhoto(fk(5))).toBeNull();
    // A thumbnail let go stays (one of the 60).
    const t = await photoBlobUrl(conn, 5, "thumb");
    t!.release();
    expect(peekPhoto(tk(5))).toBe(t!.url);
  });

  it("only thumbnails count toward the 60", () => {
    for (let i = 0; i < PHOTO_CACHE_MAX; i++) putPhoto(tk(i), jpeg(1));
    const full = holdPhoto((putPhoto(fk(500), jpeg(1)), fk(500)))!;
    expect(peekPhoto(tk(0))).not.toBeNull();
    expect(photoCacheSize()).toBe(PHOTO_CACHE_MAX + 1);
    full.release();
    expect(photoCacheSize()).toBe(PHOTO_CACHE_MAX);
  });

  it("a just-uploaded photo's own bytes are pinned until it is attached, then the full one goes", async () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    keepLocalPhoto(conn, 40, jpeg(100), jpeg(10));
    const full = await photoBlobUrl(conn, 40, "full");
    const thumb = await photoBlobUrl(conn, 40, "thumb");
    expect(full?.url).toMatch(/^blob:/);
    expect(thumb?.url).toMatch(/^blob:/);
    full!.release();
    thumb!.release();
    // Pinned: the viewer closing does not drop it, nor do 60 newer thumbnails.
    for (let i = 0; i < PHOTO_CACHE_MAX + 5; i++) putPhoto(tk(i + 100), jpeg(1));
    expect(peekPhoto(fk(40))).toBe(full!.url);
    expect(peekPhoto(tk(40))).toBe(thumb!.url);
    expect(revoke).not.toHaveBeenCalledWith(full!.url);
    dropLocalPhoto(conn, 40);
    expect(revoke).toHaveBeenCalledWith(full!.url);
    expect(peekPhoto(fk(40))).toBeNull();
  });

  it("keeps the latest 60 thumbnails: the oldest goes and its address is revoked", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const urls = Array.from({ length: PHOTO_CACHE_MAX + 1 }, (_, i) => putPhoto(tk(i), jpeg(1)));
    expect(photoCacheSize()).toBe(PHOTO_CACHE_MAX);
    expect(revoke).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith(urls[0]);
    expect(peekPhoto(tk(0))).toBeNull();
  });

  it("one a screen still shows is not revoked until that screen lets it go", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const first = putPhoto(tk(0), jpeg(1));
    const held = holdPhoto(tk(0))!;
    for (let i = 1; i <= PHOTO_CACHE_MAX; i++) putPhoto(tk(i), jpeg(1));
    expect(revoke).not.toHaveBeenCalledWith(first);
    expect(revoke).toHaveBeenCalledTimes(1); // the next oldest went instead
    held.release();
    putPhoto(tk(99), jpeg(1));
    expect(revoke).toHaveBeenCalledWith(first);
  });

  it("a replaced entry starts with no screens: the old address goes when its screen lets go, the new one stays", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const old = putPhoto(fk(7), jpeg(1));
    const held = holdPhoto(fk(7))!;
    const fresh = putPhoto(fk(7), jpeg(2));
    expect(revoke).not.toHaveBeenCalled();
    held.release();
    expect(revoke).toHaveBeenCalledWith(old);
    expect(revoke).not.toHaveBeenCalledWith(fresh);
    // The new entry was not counted as shown: held and let go once, it goes (full size).
    holdPhoto(fk(7))!.release();
    expect(revoke).toHaveBeenCalledWith(fresh);
  });

  it("an address that went (cleared) is fetched again, and held", async () => {
    let gets = 0;
    server.use(
      http.get(`${BASE}/photos/:id`, () => {
        gets++;
        return bytes();
      }),
    );
    (await photoBlobUrl(conn, 77, "thumb"))!.release();
    clearPhotoCache();
    expect(holdPhoto(tk(77))).toBeNull();
    const again = await photoBlobUrl(conn, 77, "thumb");
    expect(again?.url).toMatch(/^blob:/);
    expect(gets).toBe(2);
  });

  it("photos stay in memory only: nothing goes to IndexedDB (the offline copy, ADR 0009) or localStorage", async () => {
    server.use(http.get(`${BASE}/photos/:id`, () => bytes()));
    (await photoBlobUrl(conn, 5, "thumb"))?.release();
    (await photoBlobUrl(conn, 5, "full"))?.release();
    keepLocalPhoto(conn, 6, jpeg(10), jpeg(2));
    expect(await keys()).toEqual([]);
    expect(localStorage.length).toBe(0);
  });

  it("clearPhotoCache revokes every address", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    putPhoto("a|1|thumb", jpeg(1));
    putPhoto("b|1|thumb", jpeg(1));
    clearPhotoCache();
    expect(revoke).toHaveBeenCalledTimes(2);
    expect(photoCacheSize()).toBe(0);
  });
});

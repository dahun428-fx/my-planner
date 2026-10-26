import "fake-indexeddb/auto";
import { keys } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { subscribeResults } from "../lib/connection";
import { clearPhotoCache, PHOTO_CACHE_MAX, cachedPhoto, holdPhoto, photoCacheSize, photoKey, putPhoto } from "../lib/photoCache";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { keepLocalPhoto, photoBlobUrl, readLimitText, readPhoto, uploadFailureText, uploadPhoto } from "./photos";
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
  it("fetches with the Authorization header, no-store, and hands a blob: address; a second ask is the cache", async () => {
    const asks: { size: string | null; auth: string | null }[] = [];
    server.use(
      http.get(`${BASE}/photos/:id`, ({ request }) => {
        asks.push({ size: new URL(request.url).searchParams.get("size"), auth: request.headers.get("authorization") });
        return new HttpResponse(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), { headers: { "Content-Type": "image/jpeg", "Cache-Control": "private, no-store" } });
      }),
    );
    const url = await photoBlobUrl(conn, 9, "thumb");
    expect(url).toMatch(/^blob:/);
    expect(await photoBlobUrl(conn, 9, "thumb")).toBe(url);
    expect(asks).toEqual([{ size: "thumb", auth: `Bearer ${TEST_TOKEN}` }]);
  });

  it("a photo the BE does not give (404) or a network failure is null, and not kept", async () => {
    server.use(http.get(`${BASE}/photos/:id`, ({ params }) => (params.id === "1" ? err(404, "not_found") : HttpResponse.error())));
    expect(await photoBlobUrl(conn, 1, "thumb")).toBeNull();
    expect(await photoBlobUrl(conn, 2, "full")).toBeNull();
    expect(photoCacheSize()).toBe(0);
  });

  it("a photo just uploaded is shown from its own bytes (no request)", async () => {
    keepLocalPhoto(conn, 40, jpeg(100), jpeg(10));
    expect(await photoBlobUrl(conn, 40, "thumb")).toMatch(/^blob:/);
    expect(await photoBlobUrl(conn, 40, "full")).toMatch(/^blob:/);
  });

  it("keeps the latest 60: the oldest goes and its address is revoked", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const urls = Array.from({ length: PHOTO_CACHE_MAX + 1 }, (_, i) => putPhoto(photoKey(TEST_BE_URL, i, "thumb"), jpeg(1)));
    expect(photoCacheSize()).toBe(PHOTO_CACHE_MAX);
    expect(revoke).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith(urls[0]);
    expect(cachedPhoto(photoKey(TEST_BE_URL, 0, "thumb"))).toBeNull();
  });

  it("one a screen still shows is not revoked until that screen lets it go", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const first = putPhoto(photoKey(TEST_BE_URL, 0, "thumb"), jpeg(1));
    const release = holdPhoto(photoKey(TEST_BE_URL, 0, "thumb"));
    for (let i = 1; i <= PHOTO_CACHE_MAX; i++) putPhoto(photoKey(TEST_BE_URL, i, "thumb"), jpeg(1));
    expect(revoke).not.toHaveBeenCalledWith(first);
    // the next oldest went instead
    expect(revoke).toHaveBeenCalledTimes(1);
    release();
    putPhoto(photoKey(TEST_BE_URL, 99, "thumb"), jpeg(1));
    expect(revoke).toHaveBeenCalledWith(first);
  });

  it("photos stay in memory only: nothing goes to IndexedDB (the offline copy, ADR 0009) or localStorage", async () => {
    server.use(http.get(`${BASE}/photos/:id`, () => new HttpResponse(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), { headers: { "Content-Type": "image/jpeg" } })));
    await photoBlobUrl(conn, 5, "thumb");
    await photoBlobUrl(conn, 5, "full");
    keepLocalPhoto(conn, 6, jpeg(10), jpeg(2));
    expect(await keys()).toEqual([]);
    expect(localStorage.length).toBe(0);
  });

  it("clearPhotoCache revokes every address", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    putPhoto("a", jpeg(1));
    putPhoto("b", jpeg(1));
    clearPhotoCache();
    expect(revoke).toHaveBeenCalledTimes(2);
    expect(photoCacheSize()).toBe(0);
  });
});

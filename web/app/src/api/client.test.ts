import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveConn, subscribeResults } from "../lib/connection";
import health from "../test/fixtures/health.json";
import { BASE, server } from "../test/server";
import { apiFetch, apiGet, getHealth, type ApiResult } from "./client";

const TOKEN = "tok-SECRET-1234567890";

beforeEach(() => saveConn({ beUrl: "https://gp76.example.ts.net", token: TOKEN }));
afterEach(() => vi.restoreAllMocks());

describe("apiFetch", () => {
  it("adds bearer token", async () => {
    let auth: string | null = null;
    server.use(
      http.get(`${BASE}/ping`, ({ request }) => {
        auth = request.headers.get("authorization");
        return HttpResponse.json({ a: 1 });
      }),
    );
    const r = await apiFetch<{ a: number }>("GET", "/ping");
    expect(auth).toBe(`Bearer ${TOKEN}`);
    expect(r).toEqual({ kind: "ok", data: { a: 1 } });
  });

  it("sends a JSON body", async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/echo`, async ({ request }) => {
        body = await request.json();
        expect(request.headers.get("content-type")).toContain("application/json");
        return HttpResponse.json({});
      }),
    );
    await apiFetch("POST", "/echo", { body: { x: 1 } });
    expect(body).toEqual({ x: 1 });
  });

  it("returns data null on 204", async () => {
    server.use(http.delete(`${BASE}/thing/1`, () => new HttpResponse(null, { status: 204 })));
    expect(await apiFetch("DELETE", "/thing/1")).toEqual({ kind: "ok", data: null });
  });

  it("401/429/503/500 mapping", async () => {
    const err = (status: number, code: string) => HttpResponse.json({ error: { code, message: "m" } }, { status });
    server.use(
      http.get(`${BASE}/a`, () => err(401, "unauthorized")),
      http.get(`${BASE}/b`, () => err(429, "too_many_auth_failures")),
      http.get(`${BASE}/c`, () => err(503, "safe_mode")),
      http.get(`${BASE}/d`, () => err(500, "internal")),
      http.get(`${BASE}/e`, () => err(422, "rejected")),
      http.get(`${BASE}/f`, () => new HttpResponse("<html>", { status: 502 })),
    );
    expect(await apiFetch("GET", "/a")).toEqual({ kind: "unauthorized" });
    expect(await apiFetch("GET", "/b")).toEqual({ kind: "rate_limited" });
    expect(await apiFetch("GET", "/c")).toEqual({ kind: "safe_mode" });
    expect(await apiFetch("GET", "/d")).toEqual({ kind: "error", status: 500, code: "internal", message: "m" });
    expect(await apiFetch("GET", "/e")).toEqual({ kind: "error", status: 422, code: "rejected", message: "m" });
    expect(await apiFetch("GET", "/f")).toMatchObject({ kind: "error", status: 502 });
  });

  it("shape error when model fails", async () => {
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json({ status: "ok" })));
    expect(await apiGet("/health", "Health")).toEqual({ kind: "error", status: 200, code: "shape" });
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json(health)));
    expect(await apiGet("/health", "Health")).toMatchObject({ kind: "ok" });
  });

  it("network error is offline", async () => {
    server.use(http.get(`${BASE}/x`, () => HttpResponse.error()));
    expect(await apiFetch("GET", "/x")).toEqual({ kind: "offline" });
  });

  it("10s timeout is offline", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal(
        "fetch",
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      );
      const p = apiFetch("GET", "/slow");
      await vi.advanceTimersByTimeAsync(9_999);
      let settled = false;
      void p.then(() => (settled = true));
      await Promise.resolve();
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(2);
      expect(await p).toEqual({ kind: "offline" });
    } finally {
      vi.unstubAllGlobals();
      vi.useRealTimers();
    }
  });

  it("a longer timeout of its own: waits that long, and running out does not report offline", async () => {
    vi.useFakeTimers();
    const seen: string[] = [];
    const off = subscribeResults((r) => seen.push(r.kind));
    try {
      vi.stubGlobal(
        "fetch",
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      );
      const p = apiFetch("POST", "/push/test", { timeoutMs: 30_000 });
      let settled = false;
      void p.then(() => (settled = true));
      await vi.advanceTimersByTimeAsync(29_999);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(2);
      expect(await p).toEqual({ kind: "offline" });
      expect(seen).toEqual([]);
    } finally {
      off();
      vi.unstubAllGlobals();
      vi.useRealTimers();
    }
  });

  it("caller abort is not offline", async () => {
    const seen: ApiResult<unknown>[] = [];
    const off = subscribeResults((r) => seen.push(r));
    const ac = new AbortController();
    server.use(http.get(`${BASE}/y`, () => new Promise(() => {})));
    const p = apiFetch("GET", "/y", { signal: ac.signal });
    ac.abort();
    expect(await p).toMatchObject({ kind: "error", code: "aborted" });
    off();
    expect(seen).toEqual([]);
  });

  it("without a connection nothing is sent", async () => {
    localStorage.clear();
    expect(await apiFetch("GET", "/health")).toMatchObject({ kind: "error", code: "no_connection" });
  });

  it("reports results to subscribers", async () => {
    const seen: string[] = [];
    const off = subscribeResults((r) => seen.push(r.kind));
    server.use(http.get(`${BASE}/z`, () => HttpResponse.error()));
    await apiFetch("GET", "/z");
    off();
    expect(seen).toEqual(["offline"]);
  });

  it("never logs token", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    server.use(
      http.get(`${BASE}/n`, () => HttpResponse.error()),
      http.get(`${BASE}/u`, () => HttpResponse.json({ error: { code: "unauthorized", message: "no" } }, { status: 401 })),
    );
    await apiFetch("GET", "/n");
    await apiFetch("GET", "/u");
    const logged = JSON.stringify(spies.flatMap((s) => s.mock.calls));
    expect(logged).not.toContain(TOKEN);
  });
});

describe("getHealth", () => {
  it("reads ok, and safe_mode as its own result", async () => {
    expect(await getHealth()).toMatchObject({ kind: "ok" });
    server.use(
      http.get(`${BASE}/health`, () =>
        HttpResponse.json({ status: "safe_mode", version: health.version, now: health.now }),
      ),
    );
    expect(await getHealth()).toEqual({ kind: "safe_mode" });
    server.use(http.get(`${BASE}/health`, () => HttpResponse.json({ status: "ok" })));
    expect(await getHealth()).toEqual({ kind: "error", status: 200, code: "shape" });
  });

  it("can try a connection that is not saved yet, without reporting", async () => {
    localStorage.clear();
    const seen: string[] = [];
    const off = subscribeResults((r) => seen.push(r.kind));
    const r = await getHealth({ beUrl: "https://gp76.example.ts.net", token: "other" });
    off();
    expect(r.kind).toBe("ok");
    expect(seen).toEqual([]);
  });
});

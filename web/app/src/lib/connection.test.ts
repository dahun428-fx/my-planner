import { afterEach, describe, expect, it, vi } from "vitest";
import health from "../test/fixtures/health.json";
import degraded from "../test/fixtures/health-degraded.json";
import safeMode from "../test/fixtures/health-safe-mode.json";
import type { ApiResult } from "../api/client";
import type { Health } from "../api/types.gen";
import {
  deriveState,
  loadConn,
  loadLastHealthOk,
  normalizeBeUrl,
  normalizeToken,
  saveConn,
  saveLastHealthOk,
} from "./connection";
import { copy } from "./copy";

const ALLOWED = "https://*.example.ts.net";
const ok = (data: unknown): ApiResult<Health> => ({ kind: "ok", data: data as Health });

describe("normalizeBeUrl", () => {
  it("normalizes pasted BE URLs", () => {
    expect(normalizeBeUrl("  https://GP76.Example.ts.net/api/v1/ \n", ALLOWED)).toEqual({
      ok: true,
      url: "https://gp76.example.ts.net",
    });
    expect(normalizeBeUrl("https://gp76.example.ts.net/", ALLOWED)).toEqual({ ok: true, url: "https://gp76.example.ts.net" });
    expect(normalizeBeUrl("https://gp76.example.ts.net/api/v1", ALLOWED)).toEqual({ ok: true, url: "https://gp76.example.ts.net" });
    expect(normalizeBeUrl("http://gp76.example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "not_https" });
    expect(normalizeBeUrl("https://evil.com", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://a.b.example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://gp76.example.ts.net.evil.com", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://user@gp76.example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
    expect(normalizeBeUrl("없음", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
    expect(normalizeBeUrl("", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
  });

  it("accepts several allowed sources and defaults to the build value", () => {
    const many = "https://*.one.ts.net https://*.two.ts.net";
    expect(normalizeBeUrl("https://x.two.ts.net", many)).toEqual({ ok: true, url: "https://x.two.ts.net" });
    expect(normalizeBeUrl("https://gp76.example.ts.net")).toEqual({ ok: true, url: "https://gp76.example.ts.net" });
  });
});

describe("normalizeToken", () => {
  it("trims token", () => {
    expect(normalizeToken(" abc\n")).toBe("abc");
  });
});

describe("storage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("round trips", () => {
    expect(loadConn()).toBeNull();
    saveConn({ beUrl: "https://gp76.example.ts.net", token: "t" });
    expect(loadConn()).toEqual({ beUrl: "https://gp76.example.ts.net", token: "t" });
    expect(loadLastHealthOk()).toBeNull();
    saveLastHealthOk("2026-10-24T08:00:05Z");
    expect(loadLastHealthOk()).toBe("2026-10-24T08:00:05Z");
  });

  it("blocked storage returns null", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadConn()).toBeNull();
    expect(loadLastHealthOk()).toBeNull();
    expect(() => saveConn({ beUrl: "https://a.example.ts.net", token: "t" })).not.toThrow();
    expect(() => saveLastHealthOk("x")).not.toThrow();
  });
});

describe("deriveState", () => {
  const lastOk = "2026-10-24T07:00:00Z";

  it("derives state table", () => {
    expect(deriveState(ok(health), lastOk)).toEqual({ kind: "online", health, degraded: null });
    expect(deriveState({ kind: "offline" }, lastOk)).toEqual({ kind: "offline", lastOk });
    expect(deriveState({ kind: "unauthorized" }, lastOk)).toEqual({ kind: "unauthorized" });
    expect(deriveState({ kind: "rate_limited" }, lastOk)).toEqual({ kind: "rate_limited" });
    expect(deriveState(ok(safeMode), lastOk)).toEqual({ kind: "safe_mode" });
    expect(deriveState({ kind: "safe_mode" }, lastOk)).toEqual({ kind: "safe_mode" });

    const login = { ...health, status: "degraded", brain: { ...health.brain, auth: "login" } };
    expect(deriveState(ok(login), lastOk)).toMatchObject({ kind: "online", degraded: copy.status.relogin });
    const billing = { ...login, brain: { ...login.brain, auth: "billing" } };
    expect(deriveState(ok(billing), lastOk)).toMatchObject({ degraded: copy.status.relogin });

    // fixture: limited_until 09:30Z (= 18:30 KST) is after health.now (08:00:05Z)
    expect(deriveState(ok(degraded), lastOk)).toMatchObject({ kind: "online", degraded: "비서가 18:30까지 답을 쉬어요" });

    const pollingOnly = {
      ...health,
      status: "degraded",
      polling: "down",
    };
    expect(deriveState(ok(pollingOnly), lastOk)).toMatchObject({ kind: "online", degraded: null });
  });

  it("ignores a limited_until in the past", () => {
    const past = { ...degraded, brain: { ...degraded.brain, limited_until: "2026-10-24T07:00:00Z" } };
    expect(deriveState(ok(past), lastOk)).toMatchObject({ degraded: null });
  });

  it("maps other errors to offline", () => {
    expect(deriveState({ kind: "error", status: 500, code: "internal" }, null)).toEqual({ kind: "offline", lastOk: null });
  });
});

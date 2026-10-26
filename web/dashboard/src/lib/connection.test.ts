import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearConnection,
  defaultBeUrl,
  loadConnection,
  loadLastHealthOk,
  normalizeBeUrl,
  saveConnection,
  saveLastHealthOk,
} from "./connection";

const ALLOWED = "https://*.example.ts.net";

describe("connection", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("normalizes and rejects BE URLs", () => {
    // The live BE is reached at a tailnet host, usually pasted with its /api/v1 path.
    expect(normalizeBeUrl("https://desk.example.ts.net/api/v1", ALLOWED)).toEqual({ ok: true, url: "https://desk.example.ts.net" });
    expect(normalizeBeUrl("  https://Desk.Example.ts.net/api/v1/ \n", ALLOWED)).toEqual({ ok: true, url: "https://desk.example.ts.net" });
    expect(normalizeBeUrl("https://desk.example.ts.net", ALLOWED)).toEqual({ ok: true, url: "https://desk.example.ts.net" });
    expect(normalizeBeUrl("https://desk.example.ts.net/", ALLOWED)).toEqual({ ok: true, url: "https://desk.example.ts.net" });

    expect(normalizeBeUrl("http://desk.example.ts.net/api/v1", ALLOWED)).toEqual({ ok: false, reason: "not_https" });
    expect(normalizeBeUrl("https://evil.example.com/api/v1", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://a.b.example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://desk.example.ts.net.evil.com", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://desk.example.ts.net:8443/api/v1", ALLOWED)).toEqual({ ok: false, reason: "out_of_range" });
    // Staging BE behind `tailscale serve --https=8443` (release flow spec 5.1): the port must match the source
    const STAGING = "https://*.example.ts.net:8443";
    expect(normalizeBeUrl("https://desk.example.ts.net:8443/api/v1", STAGING)).toEqual({ ok: true, url: "https://desk.example.ts.net:8443" });
    expect(normalizeBeUrl("https://desk.example.ts.net/api/v1", STAGING)).toEqual({ ok: false, reason: "out_of_range" });
    expect(normalizeBeUrl("https://desk.example.ts.net:9443/api/v1", STAGING)).toEqual({ ok: false, reason: "out_of_range" });

    expect(normalizeBeUrl("https://user:pw@desk.example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
    expect(normalizeBeUrl("https://desk.example.ts.net/api/v1?token=x", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
    expect(normalizeBeUrl("https://desk.example.ts.net/other", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
    expect(normalizeBeUrl("ftp://desk.example.ts.net", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
    expect(normalizeBeUrl("주소 아님", ALLOWED)).toEqual({ ok: false, reason: "invalid" });
    expect(normalizeBeUrl("", ALLOWED)).toEqual({ ok: false, reason: "invalid" });

    // Several allowed sources; the default is the build constant.
    expect(normalizeBeUrl("https://x.two.ts.net", "https://*.one.ts.net https://*.two.ts.net")).toEqual({ ok: true, url: "https://x.two.ts.net" });
    expect(normalizeBeUrl("https://desk.example.ts.net/api/v1")).toEqual({ ok: true, url: "https://desk.example.ts.net" });
    expect(normalizeBeUrl("https://desk.example.ts.net", "")).toEqual({ ok: false, reason: "out_of_range" });
  });

  it("round trips connection and last answer", () => {
    expect(loadConnection()).toBeNull();
    saveConnection({ beUrl: "https://desk.example.ts.net", token: "fake-token-abc" });
    expect(loadConnection()).toEqual({ beUrl: "https://desk.example.ts.net", token: "fake-token-abc", kind: "api" });
    expect(JSON.parse(localStorage.getItem("mp.connection") ?? "null")).toEqual({ beUrl: "https://desk.example.ts.net", token: "fake-token-abc", kind: "api" });

    expect(loadLastHealthOk()).toBeNull();
    saveLastHealthOk({ at: "2026-10-24T08:00:05Z", lastTickAt: "2026-10-24T08:00:00Z" });
    expect(loadLastHealthOk()).toEqual({ at: "2026-10-24T08:00:05Z", lastTickAt: "2026-10-24T08:00:00Z" });
  });

  it("keeps a device token's id, and reads a value saved before pairing as an API token", () => {
    saveConnection({ beUrl: "https://desk.example.ts.net", token: "fake-device-token", kind: "device", deviceId: 7 });
    expect(loadConnection()).toEqual({ beUrl: "https://desk.example.ts.net", token: "fake-device-token", kind: "device", deviceId: 7 });

    // what the dashboard saved before device pairing: no kind
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: "https://desk.example.ts.net", token: "fake-token-abc" }));
    expect(loadConnection()).toEqual({ beUrl: "https://desk.example.ts.net", token: "fake-token-abc", kind: "api" });
    // a device kind without a usable id cannot be revoked: a plain token
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: "https://desk.example.ts.net", token: "t", kind: "device", deviceId: "7" }));
    expect(loadConnection()).toEqual({ beUrl: "https://desk.example.ts.net", token: "t", kind: "api" });

    clearConnection();
    expect(loadConnection()).toBeNull();
  });

  it("takes the default BE address only when it passes the check (device pairing spec 6.1)", () => {
    expect(defaultBeUrl("https://desk.example.ts.net/api/v1")).toBe("https://desk.example.ts.net");
    expect(defaultBeUrl(undefined)).toBeNull();
    expect(defaultBeUrl("  ")).toBeNull();
    expect(defaultBeUrl("http://desk.example.ts.net")).toBeNull();
    expect(defaultBeUrl("https://desk.example.com")).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_DEFAULT_BE_URL", "https://desk.example.ts.net");
    expect(defaultBeUrl()).toBe("https://desk.example.ts.net");
    vi.unstubAllEnvs();
    expect(defaultBeUrl()).toBeNull();
  });

  it("reads damaged values as nothing", () => {
    localStorage.setItem("mp.connection", "{not json");
    localStorage.setItem("mp.lastHealthOk", JSON.stringify({ at: 5 }));
    expect(loadConnection()).toBeNull();
    expect(loadLastHealthOk()).toBeNull();
    localStorage.setItem("mp.connection", JSON.stringify({ beUrl: "https://desk.example.ts.net", token: "" }));
    expect(loadConnection()).toBeNull();
  });

  it("blocked localStorage returns null", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadConnection()).toBeNull();
    expect(loadLastHealthOk()).toBeNull();
    expect(() => saveConnection({ beUrl: "https://desk.example.ts.net", token: "t" })).not.toThrow();
    expect(() => saveLastHealthOk({ at: "2026-10-24T08:00:05Z", lastTickAt: null })).not.toThrow();
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => clearConnection()).not.toThrow();
  });
});

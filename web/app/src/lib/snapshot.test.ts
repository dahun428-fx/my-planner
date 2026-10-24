import "fake-indexeddb/auto";
import { clear, get, set } from "idb-keyval";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearDeviceData, loadSnap, saveSnap } from "./snapshot";

const A = "https://gp76.example.ts.net";
const B = "https://other.example.ts.net";
const NOW = Date.parse("2026-10-24T08:00:00Z");
const DAY = 86_400_000;

afterEach(async () => {
  vi.restoreAllMocks();
  vi.doUnmock("idb-keyval");
  await clear();
});

describe("snapshot", () => {
  it("saves and loads with savedAt", async () => {
    await saveSnap("today", { date: "2026-10-24" }, A, NOW);
    const got = await loadSnap<{ date: string }>("today", A, NOW + 1000);
    expect(got).toEqual({ data: { date: "2026-10-24" }, savedAt: new Date(NOW).toISOString() });
    expect(await get("snap:today")).toMatchObject({ beUrl: A });
  });

  it("expires after 7 days", async () => {
    await saveSnap("today", { x: 1 }, A, NOW);
    expect(await loadSnap("today", A, NOW + 7 * DAY)).not.toBeNull();
    expect(await loadSnap("today", A, NOW + 7 * DAY + 1000)).toBeNull();
    expect(await get("snap:today")).toBeUndefined();
  });

  it("ignores snapshot of another BE", async () => {
    await saveSnap("today", { x: 1 }, A, NOW);
    expect(await loadSnap("today", B, NOW)).toBeNull();
    expect(await get("snap:today")).toBeUndefined();
  });

  it("clearDeviceData removes all", async () => {
    await saveSnap("today", { x: 1 }, A, NOW);
    await saveSnap("week", { x: 1 }, A, NOW);
    await set("parts:abc", [1]);
    await set("catalog", { v: 1 });
    localStorage.setItem("mp.beUrl", A);
    localStorage.setItem("mp.token", "t");
    localStorage.setItem("other", "keep");
    await clearDeviceData();
    expect(await get("snap:today")).toBeUndefined();
    expect(await get("snap:week")).toBeUndefined();
    expect(await get("parts:abc")).toBeUndefined();
    expect(await get("catalog")).toBeUndefined();
    expect(localStorage.getItem("mp.beUrl")).toBeNull();
    expect(localStorage.getItem("mp.token")).toBeNull();
    expect(localStorage.getItem("other")).toBe("keep");
  });

  it("blocked indexeddb returns null", async () => {
    const blocked = () => Promise.reject(new DOMException("blocked", "SecurityError"));
    vi.doMock("idb-keyval", () => ({ get: blocked, set: blocked, del: blocked, keys: blocked }));
    vi.resetModules();
    const fresh = await import("./snapshot");
    await expect(fresh.saveSnap("today", { x: 1 }, A, NOW)).resolves.toBeUndefined();
    await expect(fresh.loadSnap("today", A, NOW)).resolves.toBeNull();
    await expect(fresh.clearDeviceData()).resolves.toBeUndefined();
  });
});

import { describe, expect, it, vi } from "vitest";
import type { ClientErrorBody } from "../api/types.gen";
import { ErrorReporter, normalizeRoute, stripHash } from "./errorReport";

const FRAME = /^[A-Za-z0-9_-][A-Za-z0-9_.\-/[\]]*\.js:\d+:\d+$/;
const NOW = Date.parse("2026-10-26T09:00:00Z");

function make(opts: { fail?: boolean } = {}) {
  const sent: ClientErrorBody[] = [];
  let t = NOW;
  const send = vi.fn(async (body: ClientErrorBody) => {
    sent.push(body);
    if (opts.fail) throw new Error("network");
  });
  const r = new ErrorReporter(send, () => t);
  return { r, sent, send, advance: (ms: number) => (t += ms) };
}

describe("normalizeRoute", () => {
  it("replaces ids and drops query and hash", () => {
    expect(normalizeRoute("/checkin/42")).toBe("/checkin/[id]");
    expect(normalizeRoute("/today?x=1#a")).toBe("/today");
    expect(normalizeRoute("/todos/123e4567-e89b-12d3-a456-426614174000")).toBe("/todos/[id]");
    expect(normalizeRoute("/todos/[id]")).toBe("/todos/[id]");
    expect(normalizeRoute("/")).toBe("/");
  });
});

describe("stripHash", () => {
  it("maps own chunks to hashless names", () => {
    expect(stripHash("/_next/static/chunks/pages/today-3f9a1c2b.js:1:2345")).toBe("pages/today.js:1:2345");
    expect(stripHash("/_next/static/chunks/281-a1b2c3d4.js:1:9")).toBe("281.js:1:9");
    // real Next 15 build names
    expect(stripHash("/_next/static/chunks/pages/settings-26b19e66cdda912c.js:3:40")).toBe("pages/settings.js:3:40");
    expect(stripHash("/_next/static/chunks/740.d83888322fffbe52.js:1:2")).toBe("740.js:1:2");
    expect(stripHash("/_next/static/chunks/039d370b.d59f6be0926794e6.js:1:2")).toBe("039d370b.js:1:2");
    expect(stripHash("/_next/static/chunks/framework-28b60818f5cffd83.js:1:2")).toBe("framework.js:1:2");
  });
  it("accepts same-origin absolute urls and drops query strings", () => {
    expect(stripHash("https://my.app/_next/static/chunks/pages/today-3f9a1c2b.js?v=1:4:5", "https://my.app")).toBe("pages/today.js:4:5");
    expect(stripHash("https://evil.example/_next/static/chunks/pages/today-3f9a1c2b.js:4:5", "https://my.app")).toBeNull();
  });
  it("returns null for foreign code", () => {
    expect(stripHash("https://cdn.example/x.js:1:1")).toBeNull();
    expect(stripHash("/_next/static/media/font.woff2:1:1")).toBeNull();
    expect(stripHash("")).toBeNull();
  });
  it("decodes encoded dynamic segments and never emits a frame the BE would reject", () => {
    expect(stripHash("/_next/static/chunks/pages/todos/%5Bid%5D-3f9a1c2b.js:1:2")).toBe("pages/todos/[id].js:1:2");
    for (const bad of [
      "/_next/static/chunks/pages/to%20do-3f9a1c2b.js:1:2",
      "/_next/static/chunks/pages/%E3%81%82-3f9a1c2b.js:1:2",
      "/_next/static/chunks/pages/%zz-3f9a1c2b.js:1:2",
      "/_next/static/chunks/.hidden-3f9a1c2b.js:1:2",
      `/_next/static/chunks/${"a".repeat(200)}-3f9a1c2b.js:1:2`,
      "/_next/static/chunks/a.css:1:2",
      "/_next/static/chunks/a.js:x:2",
    ]) {
      const out = stripHash(bad);
      if (out !== null) expect(out).toMatch(FRAME);
      expect(out === null || out.length <= 160).toBe(true);
    }
    expect(stripHash("/_next/static/chunks/pages/to%20do-3f9a1c2b.js:1:2")).toBeNull();
  });
});

describe("ErrorReporter", () => {
  it("report never sends message", async () => {
    const { r, sent } = make();
    const err = new Error("할 일 제목");
    err.stack = `Error: 할 일 제목\n    at f (/_next/static/chunks/pages/today-3f9a1c2b.js:1:2345)\n    at https://x.example/a.js:1:1`;
    r.report(err, "/today");
    await Promise.resolve();
    expect(sent).toHaveLength(1);
    const body = sent[0];
    expect(JSON.stringify(body)).not.toContain("할 일 제목");
    expect(Object.keys(body).sort()).toEqual(["app", "at", "frames", "name", "route", "version"]);
    expect(body).toMatchObject({ app: "app", route: "/today", name: "Error", frames: ["pages/today.js:1:2345"] });
    expect(body.at).toBe("2026-10-26T09:00:00.000Z");
    expect(body.version).toMatch(/^[A-Za-z0-9._+-]+$/);
  });

  it("uses a safe name and parses safari style stacks", () => {
    const { r, sent } = make();
    const odd = Object.assign(new Error("x"), { name: "할 일 오류" });
    odd.stack = "f@/_next/static/chunks/281-a1b2c3d4.js:1:9\nnative code";
    r.report(odd, "/checkin/[id]");
    r.report("a string", "/other");
    r.report(null, "/null");
    expect(sent[0]).toMatchObject({ name: "Error", frames: ["281.js:1:9"] });
    expect(sent[1]).toMatchObject({ name: "Error", frames: [] });
    expect(sent[2]).toMatchObject({ name: "Error", frames: [] });
    const named = new TypeError("m");
    r.report(named, "/typed");
    expect(sent[3]).toMatchObject({ name: "TypeError" });
  });

  it("dedupe and rate limit", () => {
    const { r, sent } = make();
    for (let i = 0; i < 3; i++) r.report(new Error("same"), "/today");
    expect(sent).toHaveLength(1);

    const { r: r2, sent: sent2 } = make();
    for (let i = 0; i < 7; i++) {
      const e = new Error("x");
      e.name = `E${i}`;
      r2.report(e, "/today");
    }
    expect(sent2).toHaveLength(5);
  });

  it("rate limit frees up after a minute", () => {
    const { r, sent, advance } = make();
    const fire = (i: number) => {
      const e = new Error("x");
      e.name = `E${i}`;
      r.report(e, "/today");
    };
    for (let i = 0; i < 5; i++) fire(i);
    fire(5);
    expect(sent).toHaveLength(5);
    advance(60_001);
    fire(5);
    expect(sent).toHaveLength(6);
  });

  it("offline drops", () => {
    const { r, sent } = make();
    const spy = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    r.report(new Error("x"), "/today");
    expect(sent).toHaveLength(0);
    spy.mockReturnValue(true);
    r.report(new Error("x"), "/today");
    expect(sent).toHaveLength(1);
    spy.mockRestore();
  });

  it("send failure does not throw or re-report", async () => {
    const { r, send } = make({ fail: true });
    expect(() => r.report(new Error("x"), "/today")).not.toThrow();
    await new Promise((res) => setTimeout(res, 0));
    expect(send).toHaveBeenCalledTimes(1);

    const sync = new ErrorReporter(() => {
      throw new Error("sync");
    }, () => NOW);
    expect(() => sync.report(new Error("x"), "/today")).not.toThrow();
  });
});

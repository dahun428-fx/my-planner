import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it, vi } from "vitest";

// public/sw.js is a classic script with no imports; run it against a fake worker scope.
const SRC = readFileSync(join(import.meta.dirname, "../../public/sw.js"), "utf8");

type Listener = (event: unknown) => void;

function boot(openWindows: { url: string; focus: () => Promise<void>; postMessage: (m: unknown) => void }[] = []) {
  const listeners: Record<string, Listener> = {};
  const shown: { title: string; options: { body: string; tag: string; data: { url: string } } }[] = [];
  const opened: string[] = [];
  const self = {
    location: { origin: "https://app.example.ts.net" },
    addEventListener: (type: string, fn: Listener) => (listeners[type] = fn),
    registration: { showNotification: async (title: string, options: never) => void shown.push({ title, options }) },
    clients: {
      matchAll: async () => openWindows,
      openWindow: async (url: string) => void opened.push(url),
      claim: async () => undefined,
    },
  };
  new Function("self", SRC)(self);
  const run = async (type: string, event: Record<string, unknown>) => {
    const waits: Promise<unknown>[] = [];
    listeners[type]({ ...event, waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
  };
  return { shown, opened, run };
}

describe("sw.js reminder notifications", () => {
  it("shows a reminder with its own title, body and schedule url", async () => {
    const sw = boot();
    const data = { type: "reminder", title: "치과", body: "14:00 (10분 뒤)", url: "/schedule/?date=2026-10-26" };
    await sw.run("push", { data: { json: () => data } });
    expect(sw.shown).toHaveLength(1);
    expect(sw.shown[0].title).toBe("치과");
    expect(sw.shown[0].options.body).toBe("14:00 (10분 뒤)");
    expect(sw.shown[0].options.data.url).toBe("/schedule/?date=2026-10-26");
    expect(sw.shown[0].options.tag).toMatch(/^reminder:/);
  });

  it("two reminders on the same day get different tags, so neither replaces the other", async () => {
    const sw = boot();
    for (const event_id of [3, 4]) {
      const data = { type: "reminder", title: "t", body: "b", url: "/schedule/?date=2026-10-26", event_id };
      await sw.run("push", { data: { json: () => data } });
    }
    expect(new Set(sw.shown.map((n) => n.options.tag)).size).toBe(2);
  });

  it("tapping a reminder opens data.url (a new window when none is open)", async () => {
    const sw = boot();
    const close = vi.fn();
    await sw.run("notificationclick", {
      notification: { close, data: { url: "/schedule/?date=2026-10-26" } },
    });
    expect(close).toHaveBeenCalled();
    expect(sw.opened).toEqual(["/schedule/?date=2026-10-26"]);
  });

  it("tapping a reminder moves an open window there", async () => {
    const posted: unknown[] = [];
    const win = {
      url: "https://app.example.ts.net/",
      focus: async () => undefined,
      postMessage: (m: unknown) => void posted.push(m),
    };
    const sw = boot([win]);
    await sw.run("notificationclick", {
      notification: { close: () => undefined, data: { url: "/schedule/?date=2026-10-26" } },
    });
    expect(posted).toEqual([{ navigate: "/schedule/?date=2026-10-26" }]);
    expect(sw.opened).toEqual([]);
  });

  it("a reminder url off this origin falls back to the root", async () => {
    const sw = boot();
    await sw.run("push", { data: { json: () => ({ type: "reminder", title: "x", url: "https://evil.invalid/a" }) } });
    expect(sw.shown[0].options.data.url).toBe("/");
  });
});

// Every page of the static export must be in the install-time SHELL: a full page load (a push tap
// with the app closed, weak signal) falls back to the cached shell, and a missing page lands on "/".
describe("sw.js shell", () => {
  const pagesDir = join(import.meta.dirname, "../pages");
  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      return statSync(path).isDirectory() ? walk(path) : [path];
    });
  const routes = walk(pagesDir)
    .map((p) => relative(pagesDir, p).split("\\").join("/").replace(/\.tsx$/, ""))
    .filter((r) => !r.startsWith("_") && r !== "404")
    .map((r) => (r === "index" ? "/" : `/${r.replace(/\/index$/, "")}/`))
    .sort();
  const shell = JSON.parse(SRC.match(/^const SHELL = (\[[^\]]*\]);$/m)![1].replace(/,\s*\]$/, "]")) as string[];

  it("lists every page route", () => {
    expect(routes).toContain("/schedule/");
    expect(routes).toContain("/memos/view/");
    expect([...shell].sort()).toEqual(routes);
  });
});

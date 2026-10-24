import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import { describe, expect, it, vi } from "vitest";

// public/sw.js is a classic script with no imports. It runs here in a vm context whose global is a
// made-up `self`: listeners are collected and fired by hand, caches and clients are fakes.
const ORIGIN = "https://app.example.test";
const SOURCE = readFileSync(join(__dirname, "sw.js"), "utf8");

type Listener = (e: unknown) => void;

function fakeCaches(seed: Record<string, Record<string, string>> = {}) {
  const store = new Map<string, Map<string, Response>>();
  for (const [name, entries] of Object.entries(seed)) {
    store.set(name, new Map(Object.entries(entries).map(([k, v]) => [k, new Response(v)])));
  }
  const keyOf = (r: Request | string) => new URL(typeof r === "string" ? r : r.url, ORIGIN).href;
  const open = async (name: string) => {
    if (!store.has(name)) store.set(name, new Map());
    const m = store.get(name)!;
    return {
      put: async (r: Request | string, res: Response) => void m.set(keyOf(r), res),
      addAll: async (list: string[]) => list.forEach((u) => m.set(keyOf(u), new Response(`cached ${u}`))),
      match: async (r: Request | string) => m.get(keyOf(r))?.clone(),
    };
  };
  return {
    store,
    api: {
      open,
      keys: async () => [...store.keys()],
      has: async (name: string) => store.has(name),
      delete: async (name: string) => store.delete(name),
      match: async (r: Request | string, opts?: { ignoreSearch?: boolean }) => {
        for (const m of store.values()) {
          for (const [k, v] of m) {
            const want = new URL(keyOf(r));
            const have = new URL(k);
            if (k === want.href || (opts?.ignoreSearch && have.origin + have.pathname === want.origin + want.pathname)) return v.clone();
          }
        }
        return undefined;
      },
    },
  };
}

interface Win {
  url: string;
  focus: ReturnType<typeof vi.fn>;
  postMessage: ReturnType<typeof vi.fn>;
}

function load(opts: { buildId?: string; windows?: Win[]; fetch?: (r: Request) => Promise<Response>; caches?: ReturnType<typeof fakeCaches> } = {}) {
  const listeners: Record<string, Listener[]> = {};
  const windows = opts.windows ?? [];
  const caches = opts.caches ?? fakeCaches();
  const sandbox: Record<string, unknown> = {
    URL,
    Request,
    Response,
    Promise,
    JSON,
    setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
    clearTimeout: (id: ReturnType<typeof setTimeout>) => clearTimeout(id),
    location: { origin: ORIGIN },
    addEventListener: (type: string, fn: Listener) => (listeners[type] ??= []).push(fn),
    registration: { showNotification: vi.fn(async () => undefined) },
    clients: {
      matchAll: vi.fn(async () => windows),
      openWindow: vi.fn(async () => null),
      claim: vi.fn(async () => undefined),
    },
    caches: caches.api,
    fetch: vi.fn(opts.fetch ?? (async () => new Response("network"))),
  };
  sandbox.self = sandbox;
  const source = opts.buildId ? SOURCE.replace(/^const BUILD_ID = "dev";/, `const BUILD_ID = "${opts.buildId}";`) : SOURCE;
  vm.runInNewContext(source, sandbox);
  const fire = (type: string, event: object) => listeners[type]?.forEach((l) => l(event));
  return { sandbox, fire, caches, windows };
}

function extendable() {
  const waits: Promise<unknown>[] = [];
  return { waits, waitUntil: vi.fn((p: Promise<unknown>) => void waits.push(p)) };
}

function pushEvent(payload: unknown) {
  return { ...extendable(), data: { json: () => payload } };
}

function clickEvent(url: string) {
  return { ...extendable(), notification: { data: { url }, close: vi.fn() } };
}

function fetchEvent(url: string, init: { method?: string; mode?: string } = {}) {
  let responded: Promise<Response> | null = null;
  return {
    request: { url, method: init.method ?? "GET", mode: init.mode ?? "cors" },
    respondWith: vi.fn((p: Promise<Response>) => {
      responded = p;
    }),
    get responded() {
      return responded;
    },
  };
}

const win = (url = `${ORIGIN}/`): Win => ({ url, focus: vi.fn(async () => undefined), postMessage: vi.fn() });

describe("sw.js", () => {
  it("first line is the build id placeholder", () => {
    expect(SOURCE.split("\n")[0]).toBe('const BUILD_ID = "dev";');
  });

  it("maps push url", () => {
    const { sandbox } = load();
    const map = sandbox.mapPushUrl as (u: unknown) => string;
    expect(map("/checkins/341")).toBe("/checkin/?id=341");
    expect(map(undefined)).toBe("/");
    expect(map("")).toBe("/");
    expect(map("https://evil.com/x")).toBe("/");
    expect(map("//evil.com/x")).toBe("/");
    expect(map("/")).toBe("/");
    expect(map("/todos/?tab=week")).toBe("/todos/?tab=week");
  });

  it("shows notification with run tag", async () => {
    const open = win();
    const { sandbox, fire } = load({ windows: [open] });
    const e = pushEvent({ type: "checkin", checkin_id: 341, title: "Evening", body: "fake body", url: "/checkins/341" });
    fire("push", e);
    await Promise.all(e.waits);
    const show = (sandbox.registration as { showNotification: ReturnType<typeof vi.fn> }).showNotification;
    expect(show).toHaveBeenCalledWith("Evening", { body: "fake body", tag: "run-341", data: { url: "/checkin/?id=341" } });
    expect(open.postMessage).toHaveBeenCalledWith({ refresh: "today" });
  });

  it("notice tag for notice type", async () => {
    const { sandbox, fire } = load();
    const e = pushEvent({ type: "notice", checkin_id: null, title: "Notice", body: "fake notice", url: "/" });
    fire("push", e);
    await Promise.all(e.waits);
    const show = (sandbox.registration as { showNotification: ReturnType<typeof vi.fn> }).showNotification;
    expect(show).toHaveBeenCalledWith("Notice", { body: "fake notice", tag: "notice", data: { url: "/" } });
  });

  it("shows a notification even for a payload it cannot read", async () => {
    const { sandbox, fire } = load();
    const e = { ...extendable(), data: { json: () => { throw new SyntaxError("bad"); } } };
    fire("push", e);
    await Promise.all(e.waits);
    const show = (sandbox.registration as { showNotification: ReturnType<typeof vi.fn> }).showNotification;
    expect(show).toHaveBeenCalledOnce();
    expect(show.mock.calls[0][1]).toMatchObject({ tag: "notice", data: { url: "/" } });
  });

  it("click focuses open window and posts navigate", async () => {
    const open = win(`${ORIGIN}/todos/`);
    const { sandbox, fire } = load({ windows: [open] });
    const e = clickEvent("/checkin/?id=341");
    fire("notificationclick", e);
    await Promise.all(e.waits);
    expect(e.notification.close).toHaveBeenCalled();
    expect(open.focus).toHaveBeenCalled();
    expect(open.postMessage).toHaveBeenCalledWith({ navigate: "/checkin/?id=341" });
    expect((sandbox.clients as { openWindow: ReturnType<typeof vi.fn> }).openWindow).not.toHaveBeenCalled();
  });

  it("click opens window when none", async () => {
    const { sandbox, fire } = load({ windows: [] });
    const e = clickEvent("/checkins/341");
    fire("notificationclick", e);
    await Promise.all(e.waits);
    expect((sandbox.clients as { openWindow: ReturnType<typeof vi.fn> }).openWindow).toHaveBeenCalledWith("/checkin/?id=341");
  });

  it("uses waitUntil for push and click", async () => {
    const { sandbox, fire } = load({ windows: [win()] });
    const show = (sandbox.registration as { showNotification: ReturnType<typeof vi.fn> }).showNotification;
    let release!: () => void;
    show.mockImplementation(() => new Promise<void>((r) => (release = r)));
    const p = pushEvent({ type: "notice", checkin_id: null, title: "t", body: "b", url: "/" });
    fire("push", p);
    expect(p.waitUntil).toHaveBeenCalledOnce();
    let settled = false;
    void Promise.all(p.waits).then(() => (settled = true));
    await new Promise((r) => setTimeout(r, 0));
    expect(settled).toBe(false); // the push is not over until the notification is shown
    release();
    await Promise.all(p.waits);
    expect(settled).toBe(true);
    const c = clickEvent("/");
    fire("notificationclick", c);
    expect(c.waitUntil).toHaveBeenCalledOnce();
    await Promise.all(c.waits);
  });

  it("does not cache BE requests", () => {
    const { fire } = load({ buildId: "b1" });
    for (const url of ["https://gp76.example.ts.net/api/v1/today", "https://gp76.example.ts.net/_next/static/x.js"]) {
      const e = fetchEvent(url);
      fire("fetch", e);
      expect(e.respondWith).not.toHaveBeenCalled();
    }
    const post = fetchEvent(`${ORIGIN}/_next/static/a.js`, { method: "POST" });
    fire("fetch", post);
    expect(post.respondWith).not.toHaveBeenCalled();
  });

  it("static files are cache first", async () => {
    const caches = fakeCaches({ "app-b1": { [`${ORIGIN}/_next/static/chunks/a.js`]: "cached a" } });
    const { fire, sandbox } = load({ buildId: "b1", caches });
    const e = fetchEvent(`${ORIGIN}/_next/static/chunks/a.js`);
    fire("fetch", e);
    expect(await (await e.responded!).text()).toBe("cached a");
    expect(sandbox.fetch).not.toHaveBeenCalled();
  });

  it("navigation is network first", async () => {
    const caches = fakeCaches({ "app-b1": { [`${ORIGIN}/checkin/`]: "cached shell" } });
    let up = true;
    const { fire } = load({
      buildId: "b1",
      caches,
      fetch: async () => {
        if (!up) throw new TypeError("offline");
        return new Response("fresh page");
      },
    });
    const online = fetchEvent(`${ORIGIN}/checkin/?id=341`, { mode: "navigate" });
    fire("fetch", online);
    expect(await (await online.responded!).text()).toBe("fresh page");
    up = false;
    const offline = fetchEvent(`${ORIGIN}/checkin/?id=341`, { mode: "navigate" });
    fire("fetch", offline);
    expect(await (await offline.responded!).text()).toBe("cached shell");
  });

  it("a page load that hangs on a weak signal gets the cached shell", async () => {
    vi.useFakeTimers();
    try {
      const caches = fakeCaches({ "app-b1": { [`${ORIGIN}/`]: "cached root" } });
      const { fire } = load({ buildId: "b1", caches, fetch: () => new Promise<Response>(() => undefined) });
      const nav = fetchEvent(`${ORIGIN}/todos/`, { mode: "navigate" });
      fire("fetch", nav);
      let settled = false;
      void nav.responded!.then(() => (settled = true));
      await vi.advanceTimersByTimeAsync(2499);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(await (await nav.responded!).text()).toBe("cached root");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a slow page load with nothing cached still waits for the network", async () => {
    vi.useFakeTimers();
    try {
      let answer!: (r: Response) => void;
      const { fire } = load({ buildId: "b1", fetch: () => new Promise<Response>((r) => (answer = r)) });
      const nav = fetchEvent(`${ORIGIN}/todos/`, { mode: "navigate" });
      fire("fetch", nav);
      await vi.advanceTimersByTimeAsync(3000);
      answer(new Response("late page"));
      expect(await (await nav.responded!).text()).toBe("late page");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a fetch that fails after the timeout keeps the cached shell answer", async () => {
    vi.useFakeTimers();
    try {
      let fail!: (e: Error) => void;
      const caches = fakeCaches({ "app-b1": { [`${ORIGIN}/`]: "cached root" } });
      const { fire } = load({ buildId: "b1", caches, fetch: () => new Promise<Response>((_, r) => (fail = r)) });
      const nav = fetchEvent(`${ORIGIN}/todos/`, { mode: "navigate" });
      fire("fetch", nav);
      await vi.advanceTimersByTimeAsync(2500);
      fail(new TypeError("offline"));
      expect(await (await nav.responded!).text()).toBe("cached root");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a fetch that fails after the timeout with nothing cached fails the page load", async () => {
    vi.useFakeTimers();
    try {
      let fail!: (e: Error) => void;
      const { fire } = load({ buildId: "b1", fetch: () => new Promise<Response>((_, r) => (fail = r)) });
      const nav = fetchEvent(`${ORIGIN}/todos/`, { mode: "navigate" });
      fire("fetch", nav);
      await vi.advanceTimersByTimeAsync(3000);
      fail(new TypeError("offline"));
      await expect(nav.responded!).rejects.toThrow("offline");
    } finally {
      vi.useRealTimers();
    }
  });

  it("dev build does not cache", () => {
    const { fire } = load();
    const e = fetchEvent(`${ORIGIN}/_next/static/chunks/a.js`);
    fire("fetch", e);
    expect(e.respondWith).not.toHaveBeenCalled();
  });

  it("install caches the shell and the build's static files", async () => {
    const { fire, caches } = load({
      buildId: "b1",
      fetch: async () => new Response(JSON.stringify({ buildId: "b1", files: ["/_next/static/chunks/a.js"] })),
    });
    const e = extendable();
    fire("install", e);
    await Promise.all(e.waits);
    const cached = [...caches.store.get("app-b1")!.keys()].map((k) => new URL(k).pathname).sort();
    expect(cached).toEqual(["/", "/_next/static/chunks/a.js", "/activity/", "/checkin/", "/connect/", "/settings/", "/todos/"]);
  });

  it("install still succeeds when the shell cannot be cached (push must keep working)", async () => {
    const { fire } = load({ buildId: "b1", fetch: async () => { throw new TypeError("offline"); } });
    const e = extendable();
    fire("install", e);
    await expect(Promise.all(e.waits)).resolves.toBeDefined();
  });

  it("a failed install keeps the last good cache", async () => {
    const caches = fakeCaches({ "app-old": { [`${ORIGIN}/`]: "old shell" } });
    let up = true;
    const { fire } = load({
      buildId: "b1",
      caches,
      fetch: async () => {
        if (!up) throw new TypeError("offline");
        throw new TypeError("offline during install");
      },
    });
    const install = extendable();
    fire("install", install);
    await Promise.all(install.waits);
    const activate = extendable();
    fire("activate", activate);
    await Promise.all(activate.waits);
    expect(caches.store.has("app-old")).toBe(true);
    up = false;
    const nav = fetchEvent(`${ORIGIN}/todos/`, { mode: "navigate" });
    fire("fetch", nav);
    expect(await (await nav.responded!).text()).toBe("old shell");
  });

  it("old caches removed on activate", async () => {
    const caches = fakeCaches({ "app-old": {}, "app-b1": { [`${ORIGIN}/`]: "shell" }, other: {} });
    const { fire, sandbox } = load({ buildId: "b1", caches });
    const e = extendable();
    fire("activate", e);
    await Promise.all(e.waits);
    expect([...caches.store.keys()]).toEqual(["app-b1"]);
    expect((sandbox.clients as { claim: ReturnType<typeof vi.fn> }).claim).toHaveBeenCalled();
  });
});

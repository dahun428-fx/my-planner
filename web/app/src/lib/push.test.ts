import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveConn } from "./connection";
import { copy } from "./copy";
import {
  ensurePushSubscription,
  onTodayRefresh,
  pushSupport,
  registerServiceWorker,
  subscribePush,
  unsubscribePush,
} from "./push";
import { device, FAKE_AUTH, FAKE_ENDPOINT, FAKE_P256DH, FAKE_VAPID, fakeSub, installPush, IPHONE_UA, type PushEnv, resetDevice } from "../test/push";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";

let env: PushEnv | null = null;
const install = (...a: Parameters<typeof installPush>) => (env = installPush(...a));

beforeEach(() => saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN }));
afterEach(() => {
  env?.restore();
  env = null;
  resetDevice();
});

function serveBe() {
  const posted: unknown[] = [];
  const deleted: string[] = [];
  server.use(
    http.get(`${BASE}/push/vapid-public-key`, () => HttpResponse.json({ public_key: FAKE_VAPID })),
    http.post(`${BASE}/push/subscriptions`, async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json({ id: 3 }, { status: 201 });
    }),
    http.delete(`${BASE}/push/subscriptions/:id`, ({ params }) => {
      deleted.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return { posted, deleted };
}

describe("pushSupport", () => {
  it("support needs home screen on iOS tab", () => {
    install();
    device(IPHONE_UA, { standalone: false });
    expect(pushSupport()).toBe("needs_home_screen");
    device(IPHONE_UA, { standalone: true });
    expect(pushSupport()).toBe("ok");
  });

  it("unsupported without PushManager", () => {
    install({ withPushManager: false });
    expect(pushSupport()).toBe("unsupported");
    env?.restore();
    expect(pushSupport()).toBe("unsupported");
  });
});

describe("subscribePush", () => {
  it("subscribe flow posts subscription with label", async () => {
    install();
    const be = serveBe();
    await expect(subscribePush()).resolves.toEqual({ kind: "subscribed", id: 3 });
    expect(env?.requestPermission).toHaveBeenCalledOnce();
    const opts = env?.subscribe.mock.calls[0][0] as PushSubscriptionOptionsInit;
    expect(opts.userVisibleOnly).toBe(true);
    const key = opts.applicationServerKey as Uint8Array;
    expect(key).toBeInstanceOf(Uint8Array);
    expect(key.length).toBe(65);
    expect(key[0]).toBe(4);
    expect(Buffer.from(key).toString("base64url")).toBe(FAKE_VAPID);
    expect(be.posted).toEqual([{ endpoint: FAKE_ENDPOINT, keys: { p256dh: FAKE_P256DH, auth: FAKE_AUTH }, label: copy.settings.deviceLabel }]);
    expect(copy.settings.deviceLabel).toBe("폰");
    expect(localStorage.getItem("mp.pushId")).toBe("3");
  });

  it("denied returns denied and does not post", async () => {
    install({ answer: "denied" });
    const be = serveBe();
    await expect(subscribePush()).resolves.toEqual({ kind: "denied" });
    expect(env?.subscribe).not.toHaveBeenCalled();
    expect(be.posted).toEqual([]);
    expect(localStorage.getItem("mp.pushId")).toBeNull();
  });

  it("unsupported on an iOS tab without asking", async () => {
    install();
    device(IPHONE_UA, { standalone: false });
    await expect(subscribePush()).resolves.toEqual({ kind: "unsupported" });
    expect(env?.requestPermission).not.toHaveBeenCalled();
  });

  it("unavailable when the BE has no VAPID key", async () => {
    install();
    server.use(http.get(`${BASE}/push/vapid-public-key`, () => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 })));
    await expect(subscribePush()).resolves.toEqual({ kind: "unavailable" });
    expect(env?.subscribe).not.toHaveBeenCalled();
  });

  it("failed when the BE refuses the subscription", async () => {
    install();
    server.use(
      http.get(`${BASE}/push/vapid-public-key`, () => HttpResponse.json({ public_key: FAKE_VAPID })),
      http.post(`${BASE}/push/subscriptions`, () => HttpResponse.json({ error: { code: "invalid_request", message: "x" } }, { status: 400 })),
    );
    await expect(subscribePush()).resolves.toEqual({ kind: "failed" });
    expect(localStorage.getItem("mp.pushId")).toBeNull();
  });

  it("failed when the browser cannot subscribe", async () => {
    install({ subscribeError: new DOMException("push service down", "AbortError") });
    serveBe();
    await expect(subscribePush()).resolves.toEqual({ kind: "failed" });
  });
});

describe("ensurePushSubscription", () => {
  it("re-subscribes when iOS dropped it", async () => {
    install({ permission: "granted", existing: null });
    localStorage.setItem("mp.pushId", "3");
    const be = serveBe();
    await expect(ensurePushSubscription()).resolves.toBe("ok");
    expect(env?.requestPermission).not.toHaveBeenCalled();
    expect(env?.subscribe).toHaveBeenCalledOnce();
    expect(be.posted).toHaveLength(1);
    expect(localStorage.getItem("mp.pushId")).toBe("3");
  });

  it("leaves a live subscription alone", async () => {
    install({ permission: "granted", existing: fakeSub() });
    localStorage.setItem("mp.pushId", "3");
    const be = serveBe();
    await expect(ensurePushSubscription()).resolves.toBe("ok");
    expect(env?.subscribe).not.toHaveBeenCalled();
    expect(be.posted).toEqual([]);
  });

  it("does nothing when this device never subscribed", async () => {
    install({ permission: "granted" });
    await expect(ensurePushSubscription()).resolves.toBe("ok");
    expect(env?.subscribe).not.toHaveBeenCalled();
  });

  it("needs tap when resubscribe is refused", async () => {
    install({ permission: "granted", subscribeError: new DOMException("no gesture", "NotAllowedError") });
    localStorage.setItem("mp.pushId", "3");
    serveBe();
    await expect(ensurePushSubscription()).resolves.toBe("needs_tap");
  });

  it("needs tap when permission is no longer granted", async () => {
    install({ permission: "default" });
    localStorage.setItem("mp.pushId", "3");
    await expect(ensurePushSubscription()).resolves.toBe("needs_tap");
    expect(env?.requestPermission).not.toHaveBeenCalled();
  });
});

describe("unsubscribePush", () => {
  it("unsubscribe deletes then clears", async () => {
    const sub = fakeSub();
    install({ permission: "granted", existing: sub });
    localStorage.setItem("mp.pushId", "3");
    const be = serveBe();
    await unsubscribePush();
    expect(be.deleted).toEqual(["3"]);
    expect(sub.unsubscribe).toHaveBeenCalledOnce();
    expect(localStorage.getItem("mp.pushId")).toBeNull();
  });

  it("still clears when the BE cannot be reached", async () => {
    const sub = fakeSub();
    install({ permission: "granted", existing: sub });
    localStorage.setItem("mp.pushId", "3");
    server.use(http.delete(`${BASE}/push/subscriptions/:id`, () => HttpResponse.error()));
    await expect(unsubscribePush()).resolves.toBeUndefined();
    expect(sub.unsubscribe).toHaveBeenCalledOnce();
    expect(localStorage.getItem("mp.pushId")).toBeNull();
  });
});

describe("registerServiceWorker", () => {
  it("registers sw.js and follows navigate and refresh messages", async () => {
    install();
    const go = vi.fn();
    await registerServiceWorker(go);
    expect(env?.register).toHaveBeenCalledWith("/sw.js", { scope: "/" });
    const refreshed = vi.fn();
    const off = onTodayRefresh(refreshed);
    env?.emit({ navigate: "/checkin/?id=341" });
    env?.emit({ navigate: "https://evil.example/x" });
    env?.emit({ navigate: "//evil.example/x" });
    env?.emit({ refresh: "today" });
    off();
    env?.emit({ refresh: "today" });
    expect(go.mock.calls).toEqual([["/checkin/?id=341"]]);
    expect(refreshed).toHaveBeenCalledOnce();
  });

  it("does nothing without service workers", async () => {
    await expect(registerServiceWorker(vi.fn())).resolves.toBeUndefined();
  });
});

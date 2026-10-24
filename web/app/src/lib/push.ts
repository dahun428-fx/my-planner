import { apiFetch } from "../api/client";
import type { PushSubscribed, VapidPublicKey } from "../api/types.gen";
import { copy } from "./copy";
import { isIos, isStandalone } from "./platform";

// Web push on this device (spec F7, 4.7 `mp.pushId`). Browser only; call from effects and handlers.
// Nothing here logs: the subscription endpoint and keys are treated like secrets (SP3-4 14장).

const K_PUSH_ID = "mp.pushId";
const READY_MS = 10_000;

export type PushSupport = "ok" | "needs_home_screen" | "unsupported";

export type SubscribeResult =
  | { kind: "subscribed"; id: number }
  | { kind: "denied" }
  | { kind: "unsupported" }
  /** The BE has no VAPID key configured (`/push/*` answer 404): it only sends by Telegram. */
  | { kind: "unavailable" }
  | { kind: "failed" };

export function pushSupport(): PushSupport {
  if (isIos() && !isStandalone()) return "needs_home_screen";
  if (typeof window === "undefined" || typeof navigator === "undefined") return "unsupported";
  if (!("serviceWorker" in navigator) || !navigator.serviceWorker) return "unsupported";
  if (!("PushManager" in window) || !("Notification" in window)) return "unsupported";
  return "ok";
}

export function permission(): NotificationPermission {
  try {
    return Notification.permission;
  } catch {
    return "denied";
  }
}

export function loadPushId(): string | null {
  try {
    return localStorage.getItem(K_PUSH_ID);
  } catch {
    return null;
  }
}

function savePushId(id: number): void {
  try {
    localStorage.setItem(K_PUSH_ID, String(id));
  } catch {
    // blocked storage: the subscription works, it just is not re-made when iOS drops it
  }
}

function clearPushId(): void {
  try {
    localStorage.removeItem(K_PUSH_ID);
  } catch {
    // blocked storage
  }
}

/** base64url (the VAPID public key) -> bytes for `applicationServerKey`. */
export function base64UrlToBytes(s: string): Uint8Array<ArrayBuffer> {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), ms);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e: unknown) => {
        clearTimeout(t);
        reject(e instanceof Error ? e : new Error("rejected"));
      },
    );
  });
}

// An active worker is needed to subscribe; register (idempotent) so the connect screen does not
// depend on _app having done it first.
async function readyRegistration(): Promise<ServiceWorkerRegistration> {
  await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  return withTimeout(navigator.serviceWorker.ready, READY_MS);
}

async function currentSubscription(): Promise<PushSubscription | null> {
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    return reg ? await reg.pushManager.getSubscription() : null;
  } catch {
    return null;
  }
}

/** Whether this device holds a live push subscription that the BE knows (`mp.pushId`). */
export async function hasLiveSubscription(): Promise<boolean> {
  if (pushSupport() !== "ok" || permission() !== "granted" || !loadPushId()) return false;
  return (await currentSubscription()) !== null;
}

type Made = SubscribeResult | { kind: "not_allowed" };

// VAPID key -> pushManager.subscribe -> POST /push/subscriptions -> mp.pushId (F7, after permission).
async function makeSubscription(): Promise<Made> {
  const key = await apiFetch<VapidPublicKey>("GET", "/push/vapid-public-key", { model: "VapidPublicKey" });
  if (key.kind === "error" && key.status === 404) return { kind: "unavailable" };
  if (key.kind !== "ok") return { kind: "failed" };

  let sub: PushSubscription;
  try {
    const reg = await readyRegistration();
    const options = { userVisibleOnly: true, applicationServerKey: base64UrlToBytes(key.data.public_key) };
    try {
      sub = await reg.pushManager.subscribe(options);
    } catch (e) {
      // A subscription made with another BE's key: drop it and subscribe once more.
      if (!(e instanceof DOMException) || e.name !== "InvalidStateError") throw e;
      await (await reg.pushManager.getSubscription())?.unsubscribe();
      sub = await reg.pushManager.subscribe(options);
    }
  } catch (e) {
    return e instanceof DOMException && e.name === "NotAllowedError" ? { kind: "not_allowed" } : { kind: "failed" };
  }

  const json = sub.toJSON();
  const p256dh = json.keys?.p256dh;
  const auth = json.keys?.auth;
  if (!json.endpoint || !p256dh || !auth) return { kind: "failed" };
  const r = await apiFetch<PushSubscribed>("POST", "/push/subscriptions", {
    body: { endpoint: json.endpoint, keys: { p256dh, auth }, label: copy.settings.deviceLabel },
    model: "PushSubscribed",
  });
  if (r.kind === "error" && r.status === 404) return { kind: "unavailable" };
  if (r.kind !== "ok") return { kind: "failed" };
  savePushId(r.data.id);
  return { kind: "subscribed", id: r.data.id };
}

/** Ask for notification permission. Call it straight from the tap (iOS wants a user gesture). */
export function askPermission(): Promise<NotificationPermission> {
  try {
    return Notification.requestPermission().catch((): NotificationPermission => "denied");
  } catch {
    return Promise.resolve("denied");
  }
}

/**
 * F7 from a tap: ask permission first (it must be the first await on iOS), then subscribe.
 * `asked` is a permission request already started by the same tap (the connect screen asks
 * before its /health check so the gesture is not used up by the wait).
 */
export async function subscribePush(asked?: Promise<NotificationPermission>): Promise<SubscribeResult> {
  if (pushSupport() !== "ok") return { kind: "unsupported" };
  const answer = await (asked ?? askPermission());
  if (answer !== "granted") return { kind: "denied" };
  const made = await makeSubscription();
  return made.kind === "not_allowed" ? { kind: "denied" } : made;
}

/**
 * On app open (F7): iPhone may drop a subscription; when it is gone but `mp.pushId` says this
 * device had one, subscribe again (the same endpoint gets the same id). Without a tap the browser
 * may refuse: then "needs_tap", and the settings row offers "허용하기".
 */
export async function ensurePushSubscription(): Promise<"ok" | "needs_tap"> {
  if (pushSupport() !== "ok" || !loadPushId()) return "ok";
  if ((await currentSubscription()) !== null) return "ok";
  if (permission() !== "granted") return "needs_tap";
  const made = await makeSubscription();
  return made.kind === "subscribed" || made.kind === "unavailable" ? "ok" : "needs_tap";
}

/** "이 기기 연결 해제": tell the BE, drop the browser subscription, forget the id. Never throws. */
export async function unsubscribePush(): Promise<void> {
  const id = loadPushId();
  if (id && /^\d+$/.test(id)) await apiFetch("DELETE", `/push/subscriptions/${id}`);
  if (typeof navigator !== "undefined" && "serviceWorker" in navigator && navigator.serviceWorker) {
    try {
      await (await currentSubscription())?.unsubscribe();
    } catch {
      // the browser may already have dropped it
    }
  }
  clearPushId();
}

// ---- service worker messages ----------------------------------------------------------------

const TODAY_REFRESH = "mp:refresh-today";
let navigateTo: ((url: string) => void) | null = null;
let listeningOn: ServiceWorkerContainer | null = null;

/** A path inside this app ("/x", never "//host" or a full URL). */
const inApp = (url: unknown): url is string => typeof url === "string" && url.startsWith("/") && !url.startsWith("//") && !url.startsWith("/\\");

function onMessage(e: MessageEvent): void {
  const data = e.data as { navigate?: unknown; refresh?: unknown } | null;
  if (!data || typeof data !== "object") return;
  if (inApp(data.navigate)) navigateTo?.(data.navigate);
  if (data.refresh === "today") window.dispatchEvent(new Event(TODAY_REFRESH));
}

/** A push came while the app was open: the today screen reads again. Returns an unsubscribe function. */
export function onTodayRefresh(cb: () => void): () => void {
  window.addEventListener(TODAY_REFRESH, cb);
  return () => window.removeEventListener(TODAY_REFRESH, cb);
}

/** Registers /sw.js and follows its messages: `{navigate}` moves the router, `{refresh: "today"}` reads today again. */
export async function registerServiceWorker(onNavigate: (url: string) => void): Promise<void> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator) || !navigator.serviceWorker) return;
  navigateTo = onNavigate;
  if (listeningOn !== navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener("message", onMessage);
    listeningOn = navigator.serviceWorker;
  }
  try {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch {
    // no worker (private mode, a failed fetch): the app works, only offline start and push do not
  }
}

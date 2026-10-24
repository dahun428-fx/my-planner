import { apiFetch } from "../api/client";
import type { PushSubscribed, VapidPublicKey } from "../api/types.gen";
import { loadConn } from "./connection";
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

// `mp.pushId` is `{"beUrl": ..., "id": n}`: the id only means something to the BE that gave it.
// An older plain id ("3") does not say which BE it came from, so it is read as unknown and cleared.
type PushRecord = { beUrl: string; id: number };

function loadPushRecord(): PushRecord | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(K_PUSH_ID);
  } catch {
    return null;
  }
  if (raw === null) return null;
  try {
    const v = JSON.parse(raw) as Partial<PushRecord> | null;
    if (v && typeof v === "object" && typeof v.beUrl === "string" && Number.isSafeInteger(v.id)) return { beUrl: v.beUrl, id: v.id as number };
  } catch {
    // not JSON: the old plain form
  }
  clearPushId();
  return null;
}

/** This device's subscription id at the BE it is connected to now, or null (none, or another BE's). */
export function loadPushId(): number | null {
  const rec = loadPushRecord();
  const beUrl = loadConn()?.beUrl;
  return rec && beUrl && rec.beUrl === beUrl ? rec.id : null;
}

function savePushId(beUrl: string, id: number): void {
  try {
    localStorage.setItem(K_PUSH_ID, JSON.stringify({ beUrl, id }));
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

async function dropBrowserSubscription(): Promise<void> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator) || !navigator.serviceWorker) return;
  try {
    await (await currentSubscription())?.unsubscribe();
  } catch {
    // the browser may already have dropped it
  }
}

/**
 * Before another BE address is saved (connect screen): the browser subscription and its id belong
 * to the old BE, so both go. The old BE is not asked to delete it (its id means nothing to the new
 * one, and the old one drops the endpoint when the push service answers 410).
 */
export async function forgetPushForOtherBe(newBeUrl: string): Promise<void> {
  const rec = loadPushRecord();
  const oldBeUrl = loadConn()?.beUrl;
  if ((rec && rec.beUrl !== newBeUrl) || (oldBeUrl && oldBeUrl !== newBeUrl)) {
    await dropBrowserSubscription();
    clearPushId();
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
  if (pushSupport() !== "ok" || permission() !== "granted" || loadPushId() === null) return false;
  return (await currentSubscription()) !== null;
}

type Made = SubscribeResult | { kind: "not_allowed" };

// VAPID key -> pushManager.subscribe -> POST /push/subscriptions -> mp.pushId (F7, after permission).
async function makeSubscription(): Promise<Made> {
  const beUrl = loadConn()?.beUrl;
  if (!beUrl) return { kind: "failed" };
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
  if (loadConn()?.beUrl !== beUrl) return { kind: "failed" }; // the connection changed meanwhile
  savePushId(beUrl, r.data.id);
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
  if (pushSupport() !== "ok") return "ok";
  const rec = loadPushRecord();
  if (!rec) return "ok";
  if (rec.beUrl !== loadConn()?.beUrl) {
    // Made for another BE: nothing to restore here; settings offers "허용하기" for this one.
    await dropBrowserSubscription();
    clearPushId();
    return "ok";
  }
  if ((await currentSubscription()) !== null) return "ok";
  if (permission() !== "granted") return "needs_tap";
  const made = await makeSubscription();
  return made.kind === "subscribed" || made.kind === "unavailable" ? "ok" : "needs_tap";
}

/** "이 기기 연결 해제": tell the BE (only the one that gave the id), drop the browser subscription, forget the id. Never throws. */
export async function unsubscribePush(): Promise<void> {
  const id = loadPushId();
  if (id !== null) await apiFetch("DELETE", `/push/subscriptions/${id}`);
  await dropBrowserSubscription();
  clearPushId();
}

// ---- service worker messages ----------------------------------------------------------------

const TODAY_REFRESH = "mp:refresh-today";
let navigateTo: ((url: string) => void) | null = null;
let listeningOn: ServiceWorkerContainer | null = null;

/** The in-app path (pathname + search) of a URL on this origin, or null for anything else. */
function inAppPath(url: unknown): string | null {
  if (typeof url !== "string") return null;
  let u: URL;
  try {
    u = new URL(url, window.location.origin);
  } catch {
    return null;
  }
  if (u.origin !== window.location.origin || u.pathname.startsWith("//")) return null;
  return u.pathname + u.search;
}

function onMessage(e: MessageEvent): void {
  const data = e.data as { navigate?: unknown; refresh?: unknown } | null;
  if (!data || typeof data !== "object") return;
  const path = inAppPath(data.navigate);
  if (path !== null) navigateTo?.(path);
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

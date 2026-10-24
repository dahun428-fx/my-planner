import { vi } from "vitest";

// A made-up browser push stack for jsdom (no real endpoint, keys or push service).
export const FAKE_ENDPOINT = "https://push.example.test/send/fake-subscription";
const b64url = (bytes: Uint8Array) => Buffer.from(bytes).toString("base64url");
export const FAKE_P256DH = b64url(Uint8Array.from({ length: 65 }, (_, i) => (i === 0 ? 4 : i)));
export const FAKE_AUTH = b64url(Uint8Array.from({ length: 16 }, (_, i) => i + 1));
export const FAKE_VAPID = b64url(Uint8Array.from({ length: 65 }, (_, i) => (i === 0 ? 4 : 200 - i)));

export interface FakeSub {
  endpoint: string;
  toJSON(): { endpoint: string; expirationTime: null; keys: { p256dh: string; auth: string } };
  unsubscribe: ReturnType<typeof vi.fn>;
}

export function fakeSub(): FakeSub {
  return {
    endpoint: FAKE_ENDPOINT,
    toJSON: () => ({ endpoint: FAKE_ENDPOINT, expirationTime: null, keys: { p256dh: FAKE_P256DH, auth: FAKE_AUTH } }),
    unsubscribe: vi.fn(async () => true),
  };
}

export interface PushEnvOptions {
  permission?: NotificationPermission;
  /** What the permission prompt answers. */
  answer?: NotificationPermission;
  /** The subscription the browser already holds. */
  existing?: FakeSub | null;
  /** subscribe() throws this instead of subscribing. */
  subscribeError?: Error;
  withPushManager?: boolean;
}

export interface PushEnv {
  requestPermission: ReturnType<typeof vi.fn>;
  subscribe: ReturnType<typeof vi.fn>;
  getSubscription: ReturnType<typeof vi.fn>;
  register: ReturnType<typeof vi.fn>;
  current(): FakeSub | null;
  /** Message listeners added on navigator.serviceWorker. */
  emit(data: unknown): void;
  restore(): void;
}

export function installPush(opts: PushEnvOptions = {}): PushEnv {
  let permission: NotificationPermission = opts.permission ?? "default";
  let sub: FakeSub | null = opts.existing ?? null;
  const listeners = new Set<(e: MessageEvent) => void>();
  const requestPermission = vi.fn(async () => {
    if (permission === "default") permission = opts.answer ?? "granted";
    return permission;
  });
  const subscribe = vi.fn(async () => {
    if (opts.subscribeError) throw opts.subscribeError;
    sub = sub ?? fakeSub();
    return sub;
  });
  const getSubscription = vi.fn(async () => sub);
  const registration = { pushManager: { subscribe, getSubscription } };
  const register = vi.fn(async () => registration);
  const container = {
    register,
    ready: Promise.resolve(registration),
    getRegistration: vi.fn(async () => registration),
    addEventListener: (type: string, l: (e: MessageEvent) => void) => {
      if (type === "message") listeners.add(l);
    },
    removeEventListener: (_: string, l: (e: MessageEvent) => void) => listeners.delete(l),
  };
  class FakeNotification {
    static get permission() {
      return permission;
    }
    static requestPermission = requestPermission;
  }
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: container });
  Object.defineProperty(window, "Notification", { configurable: true, writable: true, value: FakeNotification });
  if (opts.withPushManager !== false) Object.defineProperty(window, "PushManager", { configurable: true, writable: true, value: class {} });
  return {
    requestPermission,
    subscribe,
    getSubscription,
    register,
    current: () => sub,
    emit: (data) => listeners.forEach((l) => l(new MessageEvent("message", { data }))),
    restore: () => {
      Reflect.deleteProperty(navigator, "serviceWorker");
      Reflect.deleteProperty(window, "Notification");
      Reflect.deleteProperty(window, "PushManager");
    },
  };
}

/** `mp.pushId` as push.ts keeps it: the id and the BE it belongs to. */
export function storePushId(id: number, beUrl = "https://gp76.example.ts.net"): void {
  localStorage.setItem("mp.pushId", JSON.stringify({ beUrl, id }));
}

export function storedPushId(): unknown {
  const raw = localStorage.getItem("mp.pushId");
  return raw === null ? null : JSON.parse(raw);
}

const originalUa = navigator.userAgent;
export const IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15";

export function device(ua: string, opts: { standalone?: boolean } = {}) {
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: ua });
  Object.defineProperty(navigator, "standalone", { configurable: true, value: opts.standalone });
}

export function resetDevice() {
  Object.defineProperty(navigator, "userAgent", { configurable: true, value: originalUa });
  Reflect.deleteProperty(navigator, "standalone");
}

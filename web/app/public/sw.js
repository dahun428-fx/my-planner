const BUILD_ID = "dev";
// ^ The first line must stay exactly as it is: scripts/sw-manifest.mjs swaps in the build id after
// `next build`, so every deploy has different sw.js bytes and the browser installs the new worker.
//
// Service worker for the app (spec 4.5, F7, F9). A classic script with no imports.
// - push: always shows a notification inside event.waitUntil (iOS drops subscriptions whose pushes
//   end without one), and tells open windows to read today again.
// - notificationclick: focus an open window and post {navigate}; otherwise open one.
// - fetch: only same-origin GET. Page loads are network first (the shell cache when offline);
//   /_next/static is cache first. Requests to the BE (another origin) are never touched.

const CACHE = "app-" + BUILD_ID;
const SHELL = ["/", "/todos/", "/activity/", "/settings/", "/checkin/", "/connect/"];
const DEFAULT_TITLE = "비서"; // the app name, as in manifest.webmanifest

// The push payload `url` (SP3-4 6.4.8) as a path inside this app: /checkins/<n> is the static
// export's /checkin/?id=<n>; empty or anything off this origin is "/".
function mapPushUrl(url) {
  if (typeof url !== "string" || url === "") return "/";
  let u;
  try {
    u = new URL(url, self.location.origin);
  } catch (_) {
    return "/";
  }
  if (u.origin !== self.location.origin || u.pathname.startsWith("//")) return "/";
  const m = u.pathname.match(/^\/checkins\/(\d+)\/?$/);
  if (m) return "/checkin/?id=" + m[1];
  return u.pathname + u.search;
}

async function handlePush(event) {
  let p = {};
  try {
    p = (event.data && event.data.json()) || {};
  } catch (_) {
    p = {};
  }
  const title = typeof p.title === "string" && p.title ? p.title : DEFAULT_TITLE;
  const body = typeof p.body === "string" ? p.body : "";
  const tag = p.checkin_id ? "run-" + p.checkin_id : "notice";
  await self.registration.showNotification(title, { body: body, tag: tag, data: { url: mapPushUrl(p.url) } });
  const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  for (const w of wins) w.postMessage({ refresh: "today" });
}

async function openOrFocus(url) {
  const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  const win = wins.find(function (w) {
    try {
      return new URL(w.url).origin === self.location.origin;
    } catch (_) {
      return false;
    }
  });
  if (!win) {
    await self.clients.openWindow(url);
    return;
  }
  try {
    await win.focus();
  } catch (_) {
    // focus can be refused; the app still moves
  }
  // The app router moves; WindowClient.navigate is not relied on (iOS).
  win.postMessage({ navigate: url });
}

self.addEventListener("push", function (event) {
  event.waitUntil(handlePush(event));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const data = event.notification.data || {};
  event.waitUntil(openOrFocus(mapPushUrl(data.url)));
});

// ---- app shell cache (not in `next dev`, whose files change under the same names) -------------

async function install() {
  if (BUILD_ID === "dev") return;
  try {
    const res = await self.fetch("/sw-manifest.json", { cache: "no-store" });
    const manifest = await res.json();
    const files = Array.isArray(manifest.files) ? manifest.files : [];
    const cache = await self.caches.open(CACHE);
    await cache.addAll(SHELL.concat(files));
  } catch (_) {
    // A shell that cannot be cached (offline, a deploy in between) must not stop the worker from
    // installing: push depends on it. Pages then simply load from the network.
  }
}

// This build's cache holds the shell only if its install got that far.
async function populated() {
  if (!(await self.caches.has(CACHE))) return false;
  const cache = await self.caches.open(CACHE);
  return Boolean(await cache.match("/"));
}

async function activate() {
  // Older caches go only once this build's is filled; after a failed install the last good shell
  // stays and still answers offline page loads.
  if (await populated()) {
    const names = await self.caches.keys();
    await Promise.all(names.filter((n) => n !== CACHE).map((n) => self.caches.delete(n)));
  }
  await self.clients.claim();
}

async function networkFirst(request) {
  try {
    return await self.fetch(request);
  } catch (err) {
    const hit = (await self.caches.match(request, { ignoreSearch: true })) || (await self.caches.match("/"));
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request) {
  const hit = await self.caches.match(request);
  if (hit) return hit;
  const res = await self.fetch(request);
  if (res.ok) {
    const cache = await self.caches.open(CACHE);
    await cache.put(request, res.clone());
  }
  return res;
}

self.addEventListener("install", function (event) {
  event.waitUntil(install());
});

self.addEventListener("activate", function (event) {
  event.waitUntil(activate());
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (BUILD_ID === "dev" || request.method !== "GET") return;
  let url;
  try {
    url = new URL(request.url);
  } catch (_) {
    return;
  }
  if (url.origin !== self.location.origin) return; // the BE and anything else: the browser's own way
  if (request.mode === "navigate") event.respondWith(networkFirst(request));
  else if (url.pathname.startsWith("/_next/static/")) event.respondWith(cacheFirst(request));
});

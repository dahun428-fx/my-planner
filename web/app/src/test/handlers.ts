import { http, HttpResponse } from "msw";
import health from "./fixtures/health.json";
import catalog from "./fixtures/catalog.json";
import checkin341 from "./fixtures/checkin-341.json";
import checkinTimes from "./fixtures/checkin-times.json";
import digestSettings from "./fixtures/digest-settings.json";
import safeModeHealth from "./fixtures/health-safe-mode.json";

// BE base used by screen tests (fixture tailnet name, not a real host).
export const BASE = "https://gp76.example.ts.net/api/v1";

// Answers other tests swap in with server.use(...) to put the connection in a state (spec 5.4).
export const healthAnswers = {
  unauthorized: () => http.get(`${BASE}/health`, () => HttpResponse.json({ error: { code: "unauthorized", message: "x" } }, { status: 401 })),
  tooMany: () => http.get(`${BASE}/health`, () => HttpResponse.json({ error: { code: "too_many_auth_failures", message: "x" } }, { status: 429 })),
  safeMode: () => http.get(`${BASE}/health`, () => HttpResponse.json(safeModeHealth)),
  unreachable: () => http.get(`${BASE}/health`, () => HttpResponse.error()),
};

// Defaults for what every screen asks on the side: the part catalog, and a check-in with no cards.
export const handlers = [
  http.get(`${BASE}/health`, () => HttpResponse.json(health)),
  http.get(`${BASE}/ui/catalog`, () => HttpResponse.json(catalog)),
  http.get(`${BASE}/checkins/:id`, () => HttpResponse.json({ ...checkin341, cards: [] })),
  http.get(`${BASE}/settings/checkin-times`, () => HttpResponse.json(checkinTimes)), // SP9 9.7, Settings
  http.get(`${BASE}/settings/digests`, () => HttpResponse.json(digestSettings)), // SP9b 5장, Settings
  http.get(`${BASE}/settings/calendar`, () => HttpResponse.json({ url: null })), // SP9 9.7, Settings
];

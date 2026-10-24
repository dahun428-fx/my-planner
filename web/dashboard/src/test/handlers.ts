import { delay, http, HttpResponse } from "msw";
import conditions from "./fixtures/conditions.json";
import health from "./fixtures/health.json";
import safeMode from "./fixtures/health-safe-mode.json";
import status from "./fixtures/status.json";
import today from "./fixtures/today.json";
import week from "./fixtures/week.json";

// Fixture tailnet host (invented, not a real machine). Tests save ORIGIN as the BE URL.
export const ORIGIN = "https://desk.example.ts.net";
export const BASE = `${ORIGIN}/api/v1`;

const error = (status: number, code: string) => HttpResponse.json({ error: { code, message: "꾸민 오류" } }, { status });

// Answers a test swaps in with server.use(...) to put /health in one of the states of spec 13.1.
export const healthAnswers = {
  ok: (body: object = health) => http.get(`${BASE}/health`, () => HttpResponse.json(body as Record<string, unknown>)),
  unauthorized: () => http.get(`${BASE}/health`, () => error(401, "unauthorized")),
  tooMany: () => http.get(`${BASE}/health`, () => error(429, "too_many_auth_failures")),
  safeMode: () => http.get(`${BASE}/health`, () => HttpResponse.json(safeMode)),
  internal: () => http.get(`${BASE}/health`, () => error(500, "internal")),
  unreachable: () => http.get(`${BASE}/health`, () => HttpResponse.error()),
  silent: () =>
    http.get(`${BASE}/health`, async () => {
      await delay("infinite");
      return HttpResponse.json(health);
    }),
};

// The same states for a screen's own GET (`/today`, `/week`, `/conditions`, `/status`).
export function answersFor(path: string, fixture: object) {
  const url = `${BASE}${path}`;
  return {
    ok: (body: object = fixture) => http.get(url, () => HttpResponse.json(body as Record<string, unknown>)),
    unauthorized: () => http.get(url, () => error(401, "unauthorized")),
    tooMany: () => http.get(url, () => error(429, "too_many_auth_failures")),
    safeMode: () => http.get(url, () => error(503, "safe_mode")),
    internal: () => http.get(url, () => error(500, "internal")),
    unreachable: () => http.get(url, () => HttpResponse.error()),
  };
}

export const todayAnswers = answersFor("/today", today);
export const weekAnswers = answersFor("/week", week);
export const conditionsAnswers = answersFor("/conditions", conditions);
export const statusAnswers = answersFor("/status", status);

export const handlers = [healthAnswers.ok(), todayAnswers.ok(), weekAnswers.ok(), conditionsAnswers.ok(), statusAnswers.ok()];

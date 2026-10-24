import { delay, http, HttpResponse } from "msw";
import health from "./fixtures/health.json";
import safeMode from "./fixtures/health-safe-mode.json";

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

export const handlers = [healthAnswers.ok()];

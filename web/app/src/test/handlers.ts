import { http, HttpResponse } from "msw";
import health from "./fixtures/health.json";
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

export const handlers = [http.get(`${BASE}/health`, () => HttpResponse.json(health))];

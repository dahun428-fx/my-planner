import { http, HttpResponse } from "msw";
import health from "./fixtures/health.json";

// BE base used by screen tests (fixture tailnet name, not a real host).
export const BASE = "https://gp76.example.ts.net/api/v1";

export const handlers = [http.get(`${BASE}/health`, () => HttpResponse.json(health))];

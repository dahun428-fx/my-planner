import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import health from "../test/fixtures/health.json";
import degraded from "../test/fixtures/health-degraded.json";
import quiet from "../test/fixtures/health-quiet.json";
import safeMode from "../test/fixtures/health-safe-mode.json";
import { BASE, ORIGIN } from "../test/handlers";
import { healthAnswers } from "../test/handlers";
import { server } from "../test/server";
import conditionsEmpty from "../test/fixtures/conditions-empty.json";
import conditions from "../test/fixtures/conditions.json";
import statusEmpty from "../test/fixtures/status-empty.json";
import status from "../test/fixtures/status.json";
import todayEmpty from "../test/fixtures/today-empty.json";
import today from "../test/fixtures/today.json";
import week from "../test/fixtures/week.json";
import curveDay from "../test/fixtures/curve-day.json";
import curveEmpty from "../test/fixtures/curve-empty.json";
import curveMonth from "../test/fixtures/curve-month.json";
import curveSensitive from "../test/fixtures/curve-month-sensitive.json";
import curveQuarter from "../test/fixtures/curve-quarter.json";
import curveWeek from "../test/fixtures/curve-week.json";
import curveYear from "../test/fixtures/curve-year.json";
import { fetchApi, getHealth, isConditions, isCurve, isHealth, isSafeModeHealth, isStatus, isToday, isWeek } from "./api";

const conn = { beUrl: ORIGIN, token: "fake-token-abc" };

describe("api", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends the token as a bearer header to /api/v1", async () => {
    let auth: string | null = null;
    server.use(
      http.get(`${BASE}/health`, ({ request }) => {
        auth = request.headers.get("authorization");
        return HttpResponse.json(health);
      }),
    );
    const r = await getHealth(conn);
    expect(r).toEqual({ kind: "ok", data: health });
    expect(auth).toBe("Bearer fake-token-abc");
  });

  it("maps 401, 429 and 503 safe_mode", async () => {
    server.use(healthAnswers.unauthorized());
    expect(await getHealth(conn)).toEqual({ kind: "unauthorized" });
    server.use(healthAnswers.tooMany());
    expect(await getHealth(conn)).toEqual({ kind: "rate_limited" });
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json({ error: { code: "safe_mode", message: "x" } }, { status: 503 })));
    expect(await fetchApi(conn, "/today", (v): v is unknown => true)).toEqual({ kind: "safe_mode" });
  });

  it("reads the safe mode /health body as safe_mode", async () => {
    server.use(healthAnswers.safeMode());
    expect(await getHealth(conn)).toEqual({ kind: "safe_mode" });
  });

  it("maps 500 to broken(internal) and other errors to their code", async () => {
    server.use(healthAnswers.internal());
    expect(await getHealth(conn)).toEqual({ kind: "broken", code: "internal" });
    server.use(http.get(`${BASE}/health`, () => new HttpResponse("bad gateway", { status: 502 })));
    expect(await getHealth(conn)).toEqual({ kind: "broken", code: "http_502" });
  });

  it("maps a 200 with a missing field to broken(shape)", async () => {
    const { brain: _brain, ...missing } = health;
    server.use(healthAnswers.ok(missing));
    expect(await getHealth(conn)).toEqual({ kind: "broken", code: "shape" });
    server.use(http.get(`${BASE}/health`, () => new HttpResponse("not json", { status: 200 })));
    expect(await getHealth(conn)).toEqual({ kind: "broken", code: "shape" });
  });

  it("maps a network error to offline", async () => {
    server.use(healthAnswers.unreachable());
    expect(await getHealth(conn)).toEqual({ kind: "offline" });
  });

  it("maps 10 seconds without an answer to offline", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    server.use(healthAnswers.silent());
    const pending = getHealth(conn);
    await vi.advanceTimersByTimeAsync(9_999);
    let settled = false;
    void pending.then(() => (settled = true));
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toEqual({ kind: "offline" });
  });

  it("maps a body that stops arriving for 10 seconds to offline", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    // Headers came; json() rejects once the request's signal aborts (Fetch standard).
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
      const signal = (init as RequestInit).signal as AbortSignal;
      const res = new Response(null, { status: 200, headers: { "content-type": "application/json" } });
      Object.defineProperty(res, "json", {
        value: () =>
          new Promise((_resolve, reject) =>
            signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
          ),
      });
      return res;
    });
    const pending = getHealth(conn);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(await pending).toEqual({ kind: "offline" });
    vi.restoreAllMocks();
  });

  it("returns offline at once for a signal already aborted", async () => {
    const ac = new AbortController();
    ac.abort();
    expect(await getHealth(conn, { signal: ac.signal })).toEqual({ kind: "offline" });
  });

  it("checks fixtures by hand, ignoring fields added later", () => {
    for (const f of [health, degraded, quiet]) expect(isHealth(f)).toBe(true);
    expect(isHealth({ ...health, added_later: { x: 1 } })).toBe(true);
    expect(isHealth({ ...health, runs_today: [{ ...health.runs_today[0], added_later: 1 }] })).toBe(true);
    expect(isHealth(safeMode)).toBe(false);
    expect(isSafeModeHealth(safeMode)).toBe(true);
    expect(isSafeModeHealth(health)).toBe(false);
    expect(isHealth({ ...health, brain: { ...health.brain, calls_today: "23" } })).toBe(false);
    expect(isHealth({ ...health, errors: { ...health.errors, by_event: { x: "1" } } })).toBe(false);
    expect(isHealth({ ...health, runs_today: [{ ...health.runs_today[0], delivered_via: "app" }] })).toBe(false);
    expect(isHealth(null)).toBe(false);
  });
});

describe("screen shapes", () => {
  it("accept the BE fixtures and refuse a missing field", () => {
    const fx = { today, todayEmpty, week, conditions, conditionsEmpty, status, statusEmpty };
    expect([isToday(fx.today), isToday(fx.todayEmpty), isWeek(fx.week)]).toEqual([true, true, true]);
    expect([isConditions(fx.conditions), isConditions(fx.conditionsEmpty)]).toEqual([true, true]);
    expect([isStatus(fx.status), isStatus(fx.statusEmpty)]).toEqual([true, true]);
    expect(isToday({ ...fx.today, todos: [{ group: "later", todo: fx.today.todos[0].todo }] })).toBe(false);
    expect(isWeek({ ...fx.week, days: [{ date: "2026-10-19" }] })).toBe(false);
    expect(isConditions({ ...fx.conditions, items: [{ date: "2026-10-01", score: "4", note: null }] })).toBe(false);
    expect(isStatus({ ...fx.status, xp_into_level: undefined })).toBe(false);
    expect(isStatus({ ...fx.status, extra_field_added_later: 1 })).toBe(true);
  });

  it("accept every curve fixture and refuse a wrong field", () => {
    const all = [curveDay, curveWeek, curveMonth, curveSensitive, curveQuarter, curveYear, curveEmpty];
    expect(all.map(isCurve)).toEqual(all.map(() => true));
    expect(isCurve({ ...curveMonth, zoom: "decade" })).toBe(false);
    expect(isCurve({ ...curveMonth, ladder: [{ period: "2026-10", now: "6", future: null }] })).toBe(false);
    expect(isCurve({ ...curveMonth, milestones: [{ ...curveMonth.milestones[0], kind: "peak" }] })).toBe(false);
    expect(isCurve({ ...curveMonth, reassurance: undefined })).toBe(false);
  });
});

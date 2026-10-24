import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import curveDay from "../test/fixtures/curve-day.json";
import curveEmpty from "../test/fixtures/curve-empty.json";
import curveMonth from "../test/fixtures/curve-month.json";
import curveSensitive from "../test/fixtures/curve-month-sensitive.json";
import curveQuarter from "../test/fixtures/curve-quarter.json";
import curveWeek from "../test/fixtures/curve-week.json";
import curveYear from "../test/fixtures/curve-year.json";
import { BASE, ORIGIN, curveAnswers } from "../test/handlers";
import { server } from "../test/server";
import { CurveScreen, curvePath, resetCurveMemory } from "./CurveScreen";

const BY_ZOOM: Record<string, object> = { day: curveDay, week: curveWeek, month: curveMonth, quarter: curveQuarter, year: curveYear };

/** Answers each `/curve` with the fixture of its zoom (and the sensitive one when asked) and records the queries. */
function recordCurve() {
  const seen: string[] = [];
  server.use(
    http.get(`${BASE}/curve`, ({ request }) => {
      const q = new URL(request.url).searchParams;
      seen.push(q.toString());
      const zoom = q.get("zoom") ?? "month";
      const body = q.get("include_sensitive") === "true" ? curveSensitive : BY_ZOOM[zoom];
      return HttpResponse.json(body as Record<string, unknown>);
    }),
  );
  return seen;
}

function renderScreen() {
  localStorage.setItem("mp.connection", JSON.stringify({ beUrl: ORIGIN, token: "fake-token-abc" }));
  return render(
    <ConnectionProvider>
      <CurveScreen />
    </ConnectionProvider>,
  );
}

const WIDE = "zoom=year&from=1900-01-01";
const notWide = (seen: string[]) => seen.filter((q) => q !== WIDE);

/** A pointer tap at the centre of a marker's glyph: it lands on the lane's tap layer, as on a phone. */
function tap(marker: HTMLElement) {
  const layer = document.querySelector(".curve-tap")!;
  fireEvent.click(layer, { clientX: Number(marker.dataset.cx), clientY: Number(marker.dataset.cy) });
}

const text = () => document.body.textContent ?? "";
const firstMarker = () => screen.findByRole("button", { name: "고점 2025년 9월 꾸민 첫 전시" });

beforeEach(() => resetCurveMemory());

/** Freeze only the clock (MSW and waitFor keep real timers): 2026-10-24 12:00 in Korea unless told otherwise. */
function today(iso = "2026-10-24T03:00:00Z") {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(iso));
}
afterEach(() => vi.useRealTimers());

const FIRST_LADDER = "11월 29일(일) 월말 회고에서 첫 사다리 점수를 여쭤볼게요.";
const AREAS_DAY = "12월 27일(일) 분기 회고에서 영역 점수를 함께 정해요.";

describe("CurveScreen", () => {
  it("zoom buttons request each zoom", async () => {
    const seen = recordCurve();
    const user = userEvent.setup();
    renderScreen();
    await firstMarker();
    const group = screen.getByRole("group", { name: "확대" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["일", "주", "월", "분기", "년"]);
    expect(within(group).getByRole("button", { name: "월" })).toHaveAttribute("aria-pressed", "true");

    for (const [label, zoom] of [["일", "day"], ["주", "week"], ["분기", "quarter"], ["년", "year"], ["월", "month"]] as const) {
      await user.click(within(group).getByRole("button", { name: label }));
      if (zoom !== "year") await waitFor(() => expect(seen.at(-1)).toContain(`zoom=${zoom}`));
      expect(within(group).getByRole("button", { name: label })).toHaveAttribute("aria-pressed", "true");
      // each answer is drawn once it is in: the figure covers that zoom's visible range
      const fx = BY_ZOOM[zoom] as { from: string; to: string };
      const from = zoom === "year" ? "2019-01-01" : fx.from;
      expect(await screen.findByRole("figure", { name: `인생곡선 ${from}~${fx.to}` })).toBeInTheDocument();
    }
    // the year zoom is the wide request the radar already made: it is reused, not asked again
    expect(notWide(seen)).toEqual(["zoom=month", "zoom=day", "zoom=week", "zoom=quarter", "zoom=month"]);
    expect(seen.filter((q) => q === WIDE)).toHaveLength(1);
  });

  it("asks the year zoom from 1900 so an event older than every chapter stays", async () => {
    expect(curvePath("year", false)).toBe("/curve?zoom=year&from=1900-01-01");
    expect(curvePath("month", true)).toBe("/curve?zoom=month&include_sensitive=true");
    recordCurve();
    const user = userEvent.setup();
    renderScreen();
    await firstMarker();
    await user.click(screen.getByRole("button", { name: "년" }));
    expect(await screen.findByRole("button", { name: "고점 2019년 꾸민 첫 자전거" })).toBeInTheDocument();
  });

  it("sensitive toggle refetches and is not persisted", async () => {
    const seen = recordCurve();
    const user = userEvent.setup();
    const before = Object.keys(localStorage).sort();
    const view = renderScreen();
    await firstMarker();
    expect(screen.queryByRole("button", { name: /꾸민 조용한 겨울/ })).toBeNull();

    const toggle = screen.getByRole("checkbox", { name: "민감한 사건 보기" });
    expect(toggle).not.toBeChecked();
    await user.click(toggle);
    const marker = await screen.findByRole("button", { name: "저점 2025년 12월 꾸민 조용한 겨울" });
    expect(notWide(seen)).toEqual(["zoom=month", "zoom=month&include_sensitive=true"]);
    tap(marker);
    expect(within(screen.getByRole("dialog")).getByText(/민감한 사건/)).toBeInTheDocument();

    // nothing written to the browser: only the connection that was there before
    const allowed = new Set([...before, "mp.connection", "mp.lastHealthOk"]);
    expect(Object.keys(localStorage).filter((k) => !allowed.has(k))).toEqual([]);
    expect(Object.values(localStorage).join("")).not.toContain("sensitive");
    expect(sessionStorage.length).toBe(0);

    // still on when this tab comes back to the screen, off in a fresh tab
    view.unmount();
    const again = renderScreen();
    expect(await screen.findByRole("checkbox", { name: "민감한 사건 보기" })).toBeChecked();
    await screen.findByRole("button", { name: "저점 2025년 12월 꾸민 조용한 겨울" });
    again.unmount();
    resetCurveMemory();
    renderScreen();
    expect(await screen.findByRole("checkbox", { name: "민감한 사건 보기" })).not.toBeChecked();
  });

  it("milestone tap shows details", async () => {
    const user = userEvent.setup();
    renderScreen();
    const marker = await firstMarker();
    expect(screen.queryByRole("dialog")).toBeNull();
    tap(marker);
    const dialog = screen.getByRole("dialog", { name: "꾸민 첫 전시" });
    expect(dialog.textContent).toContain("2025년 9월 · 고점");
    expect(dialog.textContent).toContain("꾸민 메모: 작은 카페 벽에 세 점");
    expect(marker).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "꾸민 첫 전시" })).toHaveFocus();

    tap(screen.getByRole("button", { name: "전환점 2026년 2월 14일 꾸민 이사 결정" }));
    const next = screen.getByRole("dialog", { name: "꾸민 이사 결정" });
    expect(next.textContent).toContain("2026년 2월 14일 · 전환점");
    expect(next.textContent).not.toContain("메모");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "전환점 2026년 2월 14일 꾸민 이사 결정" })).toHaveFocus();

    const low = screen.getByRole("button", { name: "저점 2026년 6월 꾸민 긴 감기" });
    low.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog", { name: "꾸민 긴 감기" })).toBeInTheDocument();
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(low).toHaveFocus();
  });

  it("the middle of each glyph opens its own milestone, even crowded on the year zoom", async () => {
    // the seeded year answer plus the sensitive 2025-12 one: four milestones within ten months
    const quiet = curveSensitive.milestones.find((m) => m.sensitive)!;
    const year = { ...curveYear, milestones: [...curveYear.milestones, quiet] };
    server.use(
      http.get(`${BASE}/curve`, ({ request }) =>
        HttpResponse.json((new URL(request.url).searchParams.get("zoom") === "year" ? year : curveMonth) as Record<string, unknown>),
      ),
    );
    const user = userEvent.setup();
    renderScreen();
    await firstMarker();
    await user.click(screen.getByRole("button", { name: "년" }));
    await screen.findByRole("button", { name: "고점 2019년 꾸민 첫 자전거" });
    const markers = Array.from(document.querySelectorAll<HTMLElement>(".curve-marker"));
    expect(markers).toHaveLength(5);
    // at this width the 2025–26 centres are closer together than a fingertip
    const xs = markers.map((m) => Number(m.dataset.cx)).sort((a, b) => a - b);
    expect(Math.min(...xs.slice(1).map((x, i) => x - xs[i]))).toBeLessThan(16);
    for (const m of markers) {
      tap(m);
      const title = year.milestones.find((x) => String(x.id) === m.dataset.milestoneId)!.title;
      expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
    }
  });

  it("radar marks down vertex", async () => {
    renderScreen();
    const radar = await screen.findByRole("region", { name: "영역 (2026-Q4, 점선 Q3)" });
    const ticks = Array.from(radar.querySelectorAll("text.radar-tick"));
    expect(ticks.map((t) => t.textContent)).toEqual(["커리어 6", "경제 5", "건강 4 ↓", "관계 7", "배움 6", "삶의 질 5"]);
    expect(radar.querySelectorAll("[data-down]")).toHaveLength(1);
    expect(radar.querySelector("[data-down]")!.textContent).toContain("건강");
    expect(within(radar).getByText("건강 4 (Q3 6) ↓")).toBeInTheDocument();
    expect(radar.querySelector(".radar-now")).not.toBeNull();
    expect(radar.querySelector(".radar-prev")).not.toBeNull(); // the quarter before, dashed by CSS
  });

  it("takes the radar from the wide request, whatever the zoom's own areas are", async () => {
    // e.g. 11/20 on the day zoom: the range is in Q4, which has no scores yet, but Q3 and Q2 do
    const wideAreas = [
      { period: "2026-Q2", scores: { ...curveMonth.areas[0].scores, health: 7 } },
      { period: "2026-Q3", scores: curveMonth.areas[0].scores },
    ];
    const seen: string[] = [];
    server.use(
      http.get(`${BASE}/curve`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        seen.push(q.toString());
        const body = q.get("zoom") === "year" ? { ...curveYear, areas: wideAreas } : { ...curveDay, areas: [] };
        return HttpResponse.json(body as Record<string, unknown>);
      }),
    );
    const user = userEvent.setup();
    renderScreen();
    await user.click(await screen.findByRole("button", { name: "일" }));
    await waitFor(() => expect(seen.at(-1)).toBe("zoom=day"));
    const radar = await screen.findByRole("region", { name: "영역 (2026-Q3, 점선 Q2)" });
    expect(within(radar).getByText("건강 6 (Q2 7) ↓")).toBeInTheDocument();
    expect(document.querySelector(".radar-panel .empty")).toBeNull();
    expect(seen).toContain(WIDE);
  });

  it("draws the ladder, conditions and chapters it got, and nothing for an empty month", async () => {
    renderScreen();
    const fig = await screen.findByRole("figure", { name: "인생곡선 2024-11-01~2026-10-31" });
    expect(fig.querySelectorAll(".curve-now .recharts-line-curve, .curve-now path.recharts-curve").length).toBeGreaterThan(0);
    expect(fig.querySelectorAll(".curve-future").length).toBeGreaterThan(0);
    const list = screen.getByRole("list", { name: "곡선의 값" });
    const rows = within(list).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows).toContain("사다리 2026-10 · 지금 6 · 5년 뒤 8");
    expect(rows).toContain("사다리 2026-03 · 5년 뒤 7");
    expect(rows.some((r) => r?.startsWith("사다리 2026-04"))).toBe(false);
    expect(rows).toContain("챕터 꾸민 새 출발 (2025-03~지금)");
    expect(rows).toContain("컨디션 2026-08 평균 4.5 · 12일 기록");
    expect(screen.getAllByRole("button", { name: /^(고점|저점|전환점) / })).toHaveLength(3);
  });

  it("shows the reassurance view with the 8.3 copy, newest month first", async () => {
    renderScreen();
    const panel = await screen.findByRole("region", { name: "안심 보기" });
    const items = within(panel).getAllByRole("listitem");
    expect(items.slice(0, 4).map((li) => li.textContent)).toEqual([
      "10월 기억 6 · 하루하루 6.8기억과 하루하루가 비슷했던 달이에요",
      "9월 기억 6이 달은 컨디션 기록이 적어서 비교하지 않았어요",
      "8월 기억 5 · 하루하루 8.8기억보다 하루하루가 괜찮았던 달이에요",
      "7월 기억 7 · 하루하루 3.8하루하루는 버거웠지만 한 달을 좋게 기억하는 달이에요",
    ]);
    expect(within(panel).getByText("지난 달 4개 더 보기")).toBeInTheDocument();
    expect(panel.textContent).toContain("2025년 11월 기억 4");
  });

  it("four empty states, with the dated reviews to come (DU-05)", async () => {
    today();
    server.use(curveAnswers.ok(curveEmpty));
    renderScreen();
    expect(await screen.findByText("시드를 가져오거나 대화에서 사건을 남기면 여기에 그려져요.")).toBeInTheDocument();
    const curve = screen.getByRole("region", { name: "인생곡선" });
    const marks = within(curve).getByRole("list", { name: "곧 그려질 것" });
    expect(within(marks).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["11월 29일(일)첫 사다리", "12월 27일(일)영역 점수"]);
    expect(within(marks).getAllByRole("listitem").map((li) => li.querySelector("time")?.getAttribute("datetime"))).toEqual(["2026-11-29", "2026-12-27"]);
    expect(within(curve).getByText(FIRST_LADDER)).toBeInTheDocument();
    const radar = screen.getByRole("region", { name: "영역" });
    expect(within(radar).getByText(AREAS_DAY)).toBeInTheDocument();
    expect(screen.getByText("사다리 점수와 컨디션 기록이 한 달 쌓이면 비교해 드릴게요.")).toBeInTheDocument();
    expect(screen.queryByRole("figure")).toBeNull();
    // no percentages, countdowns or days-left counts
    expect(text()).not.toMatch(/%|D-[0-9]|남은|일 남/);
  });

  it("works the review days out from the logical date in Korea (04:00 turn)", async () => {
    today("2026-11-29T19:00:00Z"); // 11/30 04:00 in Korea: the day after November's review
    server.use(curveAnswers.ok(curveEmpty));
    const view = renderScreen();
    expect(await screen.findByText("12월 27일(일) 월말 회고에서 첫 사다리 점수를 여쭤볼게요.")).toBeInTheDocument();
    expect(screen.getByText(AREAS_DAY)).toBeInTheDocument();
    view.unmount();

    today("2026-11-29T18:59:00Z"); // 11/30 03:59 in Korea: still the review day's logical date
    renderScreen();
    expect(await screen.findByText(FIRST_LADDER)).toBeInTheDocument();
  });

  it("never promises a ladder before 11/29 (11.2), and moves on after it", async () => {
    today("2026-12-05T03:00:00Z");
    server.use(curveAnswers.ok(curveEmpty));
    renderScreen();
    const marks = await screen.findByRole("list", { name: "곧 그려질 것" });
    expect(within(marks).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["12월 27일(일)첫 사다리", "12월 27일(일)영역 점수"]);
  });

  it("the review day itself is still the day", async () => {
    today("2026-12-26T19:00:00Z"); // 12/27 04:00 in Korea: monthly and quarterly reviews on one Sunday
    server.use(curveAnswers.ok(curveEmpty));
    renderScreen();
    const marks = await screen.findByRole("list", { name: "곧 그려질 것" });
    expect(within(marks).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["12월 27일(일)첫 사다리", "12월 27일(일)영역 점수"]);
  });

  it("keeps a milestone the BE sent even when its middle is outside the range, at the edge", async () => {
    const early = { ...curveMonth.milestones[0], id: 99, date: "2024", precision: "year", title: "꾸민 이른 해" };
    server.use(curveAnswers.ok({ ...curveMonth, milestones: [...curveMonth.milestones, early] }));
    renderScreen();
    const marker = await screen.findByRole("button", { name: "고점 2024년 꾸민 이른 해" });
    const xs = Array.from(document.querySelectorAll<HTMLElement>(".curve-marker")).map((m) => Number(m.dataset.cx));
    expect(Number(marker.dataset.cx)).toBe(Math.min(...xs));
  });

  it("says there is no ladder score when only five-years-ahead scores exist", async () => {
    today();
    const ladder = [{ period: "2026-10", now: null, future: 8, note: null }];
    server.use(curveAnswers.ok({ ...curveMonth, ladder }));
    renderScreen();
    expect(await screen.findByText(FIRST_LADDER)).toBeInTheDocument();
    expect(screen.getByRole("figure")).toBeInTheDocument();
    // the areas are scored: only the ladder is to come
    const marks = screen.getByRole("list", { name: "곧 그려질 것" });
    expect(within(marks).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["11월 29일(일)첫 사다리"]);
  });

  it("does not call it the first ladder when the wide request has an earlier one", async () => {
    today();
    const earlier = curveYear.ladder.filter((l) => l.period !== "2026-10");
    server.use(
      http.get(`${BASE}/curve`, ({ request }) => {
        const zoom = new URL(request.url).searchParams.get("zoom");
        const body = zoom === "year" ? { ...curveYear, ladder: earlier } : { ...curveMonth, ladder: [] };
        return HttpResponse.json(body as Record<string, unknown>);
      }),
    );
    renderScreen();
    expect(await screen.findByText("11월 29일(일) 월말 회고에서 사다리 점수를 여쭤볼게요.")).toBeInTheDocument();
    const marks = screen.getByRole("list", { name: "곧 그려질 것" });
    expect(within(marks).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["11월 29일(일)사다리"]);
    expect(screen.queryByText(FIRST_LADDER)).toBeNull();
  });

  it("promises nothing when this month's ladder is already in and only the zoom is empty (11.1)", async () => {
    today();
    expect(curveYear.ladder.some((l) => l.period === "2026-10" && l.now !== null)).toBe(true);
    server.use(
      http.get(`${BASE}/curve`, ({ request }) => {
        const zoom = new URL(request.url).searchParams.get("zoom");
        const body = zoom === "year" ? curveYear : { ...curveMonth, ladder: [] };
        return HttpResponse.json(body as Record<string, unknown>);
      }),
    );
    renderScreen();
    await screen.findByRole("figure");
    await waitFor(() => expect(screen.queryByRole("list", { name: "곧 그려질 것" })).toBeNull());
    expect(text()).not.toContain("월말 회고에서");
  });

  it("lists the reassurance months of the wide request, whatever the zoom (B2)", async () => {
    const seen = recordCurve();
    const user = userEvent.setup();
    renderScreen();
    await user.click(await screen.findByRole("button", { name: "일" }));
    await waitFor(() => expect(seen.at(-1)).toBe("zoom=day"));
    await screen.findByRole("figure");
    const panel = screen.getByRole("region", { name: "안심 보기" });
    // the day zoom alone has 2026-09 and 2026-10; the wide answer has all ten months
    const periods = () => Array.from(document.querySelectorAll<HTMLElement>(".reassure")).map((li) => li.dataset.period);
    expect(panel).toBeInTheDocument();
    expect(periods()).toHaveLength(curveYear.reassurance.length);
    expect(periods()).toContain("2025-11");
  });

  it("keeps the chart when only the ladder is missing, and has nothing to compare without a counted month", async () => {
    const reassurance = curveMonth.reassurance.map((r) => ({ ...r, condition_average: null, condition_scaled: null, gap: null }));
    server.use(curveAnswers.ok({ ...curveMonth, ladder: [], reassurance }));
    renderScreen();
    expect(await screen.findByText(/월말 회고에서 (첫 )?사다리 점수를 여쭤볼게요\.$/)).toBeInTheDocument();
    expect(screen.getByRole("figure")).toBeInTheDocument();
    expect(screen.queryByText("시드를 가져오거나 대화에서 사건을 남기면 여기에 그려져요.")).toBeNull();
    expect(screen.getByText("사다리 점수와 컨디션 기록이 한 달 쌓이면 비교해 드릴게요.")).toBeInTheDocument();
  });

  it("offline and 401 states", async () => {
    server.use(curveAnswers.unreachable());
    const view = renderScreen();
    expect(await screen.findByText("BE가 켜지면 다시 보여 드릴게요.")).toBeInTheDocument();
    expect(screen.queryByRole("figure")).toBeNull();
    expect(screen.queryByRole("region", { name: "안심 보기" })).toBeNull();
    view.unmount();

    server.use(curveAnswers.unauthorized());
    renderScreen();
    expect(await screen.findByText("토큰이 맞지 않아요. 설정에서 다시 넣어 주세요.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "설정 열기" })).toBeInTheDocument();
    expect(screen.queryByRole("figure")).toBeNull();
  });

  it("shows a shape error and the other common states", async () => {
    for (const [answer, words] of [
      [curveAnswers.tooMany(), "잠시 뒤에 다시 시도해 주세요."],
      [curveAnswers.safeMode(), "데이터베이스 점검이 필요해요. PC에서 README의 복구 절차를 따라 주세요."],
      [curveAnswers.internal(), "BE가 응답했지만 이 화면을 그리지 못했어요 (internal)."],
      [curveAnswers.ok({ ...curveMonth, ladder: "x" }), "BE가 응답했지만 이 화면을 그리지 못했어요 (shape)."],
    ] as const) {
      server.use(answer);
      const view = renderScreen();
      expect(await screen.findByText(words)).toBeInTheDocument();
      await act(async () => view.unmount());
    }
  });
});

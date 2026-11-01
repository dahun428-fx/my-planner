import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { LifeReportOut } from "../api/types.gen";
import { copyPanel } from "../lib/copyPanel";
import reportJson from "../test/fixtures/life_report.json";
import { SUGGESTION } from "../test/panel";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import ReportPage from "../pages/status/report";
import { LifeReport } from "./LifeReport";

// SP15 14장 T13 (1장 11): the life report screen, from a made-up report (no real values).
const report = reportJson as LifeReportOut;
const T = copyPanel.report;
const OLDER: LifeReportOut = {
  id: 1,
  created_at: "2026-08-02T11:00:00Z",
  report: { ...report.report, summary: { ...report.report.summary, line: "가짜 지난 진단 한 줄이에요." }, this_week: [] },
};

function serve(items = [{ id: report.id, created_at: report.created_at }, { id: OLDER.id, created_at: OLDER.created_at }]) {
  const reads: string[] = [];
  server.use(
    http.get(`${BASE}/life-reports`, () => (reads.push("list"), HttpResponse.json({ items }))),
    http.get(`${BASE}/life-reports/:id`, ({ params }) => {
      reads.push(`report ${String(params.id)}`);
      return HttpResponse.json(Number(params.id) === OLDER.id ? OLDER : report);
    }),
    http.get(`${BASE}/panel/suggestions`, () => (reads.push("suggestions"), HttpResponse.json({ items: [SUGGESTION] }))),
  );
  return reads;
}

const h2s = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
const sectionOf = (heading: string) => screen.getByRole("heading", { level: 2, name: heading }).closest("section") as HTMLElement;

describe("LifeReport (SP15 10장)", () => {
  it("shows the newest report, its eight sections in order, then the past list", async () => {
    const reads = serve();
    renderWithProviders(<LifeReport />, { route: "/status/report/" });
    expect(await screen.findByText(report.report.summary.line)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: T.title })).toBeInTheDocument();
    const s = T.sections;
    await screen.findByText(SUGGESTION.title);
    expect(h2s()).toEqual([s.summary, s.scores, s.levers, s.experts, s.scenario, s.roadmap, s.thisWeek, s.questions, T.past]);
    expect(reads.slice(0, 2)).toEqual(["list", "report 2"]);
    for (const p of report.report.summary.paths) expect(screen.getByText(p)).toBeInTheDocument();
  });

  it("score board: two dots per axis on six axes, low reliability faded, a six-axis radar", async () => {
    serve();
    const { container } = renderWithProviders(<LifeReport />, { route: "/status/report/" });
    await screen.findByText(report.report.summary.line);
    const board = sectionOf(T.sections.scores);
    const rows = board.querySelectorAll("li[data-axis]");
    expect([...rows].map((r) => r.getAttribute("data-axis"))).toEqual(["career", "money", "health", "looks", "relations", "intellect"]);
    for (const r of rows) {
      const axis = r.getAttribute("data-axis") as keyof typeof report.report.scores;
      const sc = report.report.scores[axis];
      expect(r.querySelectorAll('circle[data-cohort="national"]')).toHaveLength(sc.national === null ? 0 : 1);
      expect(r.querySelectorAll('circle[data-cohort="peer"]')).toHaveLength(sc.peer === null ? 0 : 1);
      expect(r.hasAttribute("data-faded")).toBe(sc.reliability === "low");
    }
    // Two dots each where both cohorts have a score (intellect has no peer score in the fixture).
    expect(board.querySelectorAll("circle[data-cohort]")).toHaveLength(11);
    // The stored copy of the numbers.
    expect(within(board.querySelector('[data-axis="career"]') as HTMLElement).getByText(/71/)).toBeInTheDocument();
    const radar = within(board).getByRole("img", { name: T.radarLabel });
    expect(radar.querySelectorAll("line[data-axis]")).toHaveLength(6);
    expect(radar.querySelector('[data-cohort="national"]')).not.toBeNull();
    expect(container.querySelector('[data-axis="height"]')).toBeNull();
  });

  it("lever map: a line per lever, its weight by strength", async () => {
    serve();
    renderWithProviders(<LifeReport />, { route: "/status/report/" });
    await screen.findByText(report.report.summary.line);
    const map = within(sectionOf(T.sections.levers)).getByRole("img", { name: T.leverLabel });
    const lines = [...map.querySelectorAll("line[data-strength]")];
    expect(lines.map((l) => l.getAttribute("data-strength"))).toEqual(report.report.levers.map((l) => l.strength));
    const width = (k: string) => Number(lines.find((l) => l.getAttribute("data-strength") === k)!.getAttribute("stroke-width"));
    expect(width("weak")).toBeLessThan(width("mid"));
    expect(width("mid")).toBeLessThan(width("strong"));
    // One action listed once, however many axes it moves.
    expect(within(sectionOf(T.sections.levers)).getAllByText(/가짜 행동: 아침 20분 걷기/)).toHaveLength(1);
  });

  it("experts are six folded details; scenario says estimate; roadmap bars and today line", async () => {
    serve();
    renderWithProviders(<LifeReport />, { route: "/status/report/" });
    await screen.findByText(report.report.summary.line);
    const experts = sectionOf(T.sections.experts).querySelectorAll("details");
    expect(experts).toHaveLength(6);
    expect([...experts].every((d) => !d.open)).toBe(true);
    expect(within(experts[2] as HTMLElement).getByText(copyPanel.experts.health)).toBeInTheDocument();
    expect(within(experts[2] as HTMLElement).getByText(T.avoid)).toBeInTheDocument();
    const scenario = sectionOf(T.sections.scenario);
    expect(within(scenario).getByText(T.doIt)).toBeInTheDocument();
    expect(within(scenario).getByText(T.dontDo)).toBeInTheDocument();
    expect(within(scenario).getByText(T.estimate)).toBeInTheDocument();
    const roadmap = sectionOf(T.sections.roadmap);
    expect(roadmap.querySelectorAll("rect[data-bar]")).toHaveLength(2);
    expect(within(roadmap).getByText("가짜 지표: 주 3번 걷기")).toBeInTheDocument();
  });

  it("this week names the suggestion titles it finds and drops the rest; the closing line ends it; no percent", async () => {
    serve();
    const { container } = renderWithProviders(<LifeReport />, { route: "/status/report/" });
    await screen.findByText(SUGGESTION.title);
    expect(within(sectionOf(T.sections.thisWeek)).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("이 숫자는 이번 분기 조건의 측정값이지 나 자신이 아니다.")).toBeInTheDocument();
    expect(container.textContent).not.toContain("%");
    expect(container.textContent).not.toContain("등수");
  });

  it("past reports: another date opens that report", async () => {
    const reads = serve();
    renderWithProviders(<LifeReport />, { route: "/status/report/" });
    await screen.findByText(report.report.summary.line);
    const past = sectionOf(T.past);
    const current = within(past).getByRole("button", { name: "2026.10.31" });
    expect(current).toHaveAttribute("aria-current", "true");
    await userEvent.setup().click(within(past).getByRole("button", { name: "2026.08.02" }));
    expect(await screen.findByText("가짜 지난 진단 한 줄이에요.")).toBeInTheDocument();
    expect(reads).toContain("report 1");
    expect(within(sectionOf(T.past)).getByRole("button", { name: "2026.08.02" })).toHaveAttribute("aria-current", "true");
    // That report's this_week is empty: no "이번 주" section.
    expect(screen.queryByRole("heading", { level: 2, name: T.sections.thisWeek })).toBeNull();
  });

  it("the page loads the screen as its own chunk", async () => {
    serve();
    renderWithProviders(<ReportPage />, { route: "/status/report/" });
    expect(await screen.findByRole("heading", { level: 1, name: T.title })).toBeInTheDocument();
    expect(await screen.findByText(report.report.summary.line)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "‹ 상태창" })).toHaveAttribute("href", "/status/");
  });

  it("no report yet: says so", async () => {
    const reads = serve([]);
    renderWithProviders(<LifeReport />, { route: "/status/report/" });
    expect(await screen.findByText(T.empty)).toBeInTheDocument();
    await waitFor(() => expect(reads).toEqual(["list"]));
  });
});

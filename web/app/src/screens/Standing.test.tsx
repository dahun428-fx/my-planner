import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Standing as StandingData, StandingMeasures } from "../api/types.gen";
import { copy } from "../lib/copy";
import { standingCopy } from "../lib/copyStanding";
import measuresJson from "../test/fixtures/standing-measures.json";
import standingJson from "../test/fixtures/standing.json";
import { serveActions } from "../test/parts";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { cohortPath, Standing } from "./Standing";

const standing = standingJson as StandingData;
const measures = measuresJson as StandingMeasures;

function serve(data: StandingData = standing, list: StandingMeasures = measures) {
  server.use(
    http.get(`${BASE}/standing`, () => HttpResponse.json(data)),
    http.get(`${BASE}/standing/measures`, () => HttpResponse.json(list)),
  );
}

const sectionOf = (heading: string) => screen.getByRole("heading", { level: 2, name: heading }).closest("section") as HTMLElement;

describe("Standing detail (SP13 10.3)", () => {
  it("two markets on top with the marriage note", async () => {
    serve();
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    expect(await screen.findByRole("heading", { level: 1, name: "객관적 위치" })).toBeInTheDocument();
    const markets = sectionOf("시장 점수");
    const rows = within(markets).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("결혼시장");
    expect(rows[0].textContent).toContain("전체 64");
    expect(rows[0].textContent).toContain("IT 60");
    expect(within(rows[0]).getByText("나이·성격·가치관이 빠진 서류 스펙 점수예요.")).toBeInTheDocument();
    expect(rows[1].textContent).toContain("직업시장");
    expect(rows[1].textContent).toContain("전체 70");
    expect(markets.textContent).not.toContain("빠짐");
  });

  it("a market with excluded axes names them", async () => {
    serve({ ...standing, markets: { ...standing.markets, marriage: { national: 61, peer: 58, excluded: ["looks", "family"] } } });
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    expect(await screen.findByText("빠짐: 외모, 집안")).toBeInTheDocument();
  });

  it("the radar has nine axes and two cohorts, drawn without style attributes", async () => {
    serve();
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    const radar = await screen.findByRole("img", { name: standingCopy.radarLabel });
    expect(radar.tagName.toLowerCase()).toBe("svg");
    expect(radar.querySelectorAll("line[data-axis]")).toHaveLength(9);
    expect(radar.querySelectorAll("path[data-cohort]")).toHaveLength(2);
    expect(radar.querySelector("path[data-cohort=national]")!.getAttribute("d")).toMatch(/Z$/); // all nine scored: closed
    expect(document.querySelector("[style]")).toBeNull();
  });

  it("an axis with no score is a gap in the radar line, not a point at the centre", () => {
    const d = cohortPath([50, 50, null, 50]);
    expect(d).not.toMatch(/Z/);
    expect(d.match(/M/g)).toHaveLength(2); // edges 3→0 and 0→1 only
    expect(d).not.toContain("160.0 160.0"); // never the centre
    expect(cohortPath([null, 50, null, null])).toMatch(/^M(\S+ \S+) L\1$/); // a lone axis keeps a dot
  });

  it("the nav row and the axis bars use different classes (review: one `.bar` was both)", async () => {
    serve();
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    const back = await screen.findByRole("link", { name: "‹ 상태창" });
    await screen.findByRole("heading", { level: 2, name: "축별 점수" });
    const bar = sectionOf("축별 점수").querySelector("svg")!;
    expect(back.closest("nav")!.className).not.toBe(bar.getAttribute("class"));
    const css = readFileSync(join(__dirname, "Standing.module.css"), "utf8");
    const selectors = [...css.matchAll(/^(\.[A-Za-z]+) \{/gm)].map((m) => m[1]);
    expect(selectors.filter((s, i) => selectors.indexOf(s) !== i)).toEqual([]);
  });

  it("nine axis bars with band, reliability, missing and date", async () => {
    serve();
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    await screen.findByRole("heading", { level: 2, name: "축별 점수" });
    const rows = within(sectionOf("축별 점수")).getAllByRole("listitem");
    expect(rows).toHaveLength(9);
    const health = rows.find((r) => r.dataset.axis === "health")!;
    expect(health.textContent).toContain("건강");
    expect(health.textContent).toContain("73");
    expect(health.textContent).toContain("65~81");
    expect(health.textContent).toContain("신뢰도 보통");
    expect(within(health).getByText("미입력: LDL 콜레스테롤, 건강검진 판정")).toBeInTheDocument();
    expect(within(health).getByText("빈 항목은 가정값으로 계산했어요.")).toBeInTheDocument();
    expect(health.textContent).toContain("측정일 10/1");
    const bar = health.querySelector("svg")!;
    expect(bar.querySelector("rect[data-part=band]")).toHaveAttribute("x", "65");
    expect(bar.querySelector("rect[data-part=fill]")).toHaveAttribute("width", "73");
    const career = rows.find((r) => r.dataset.axis === "career")!;
    expect(career.textContent).toContain("IT 63");
    expect(career.textContent).not.toContain("미입력");
  });

  it("measures list shows label, value, date and source", async () => {
    serve();
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    await screen.findByRole("heading", { level: 2, name: "측정값" });
    const rows = within(sectionOf("측정값")).getAllByRole("listitem");
    expect(rows).toHaveLength(measures.measures.length);
    const salary = rows.find((r) => r.dataset.metric === "salary_krw")!;
    expect(salary.textContent).toContain("연봉(세전)");
    expect(salary.textContent).toContain("6,200만 원");
    expect(salary.textContent).toContain("10/1 · 가져오기");
    const height = rows.find((r) => r.dataset.metric === "height_cm")!;
    expect(height.textContent).toContain("176cm");
    const smoking = rows.find((r) => r.dataset.metric === "smoking")!;
    expect(smoking.textContent).toContain("끊음");
  });

  it("delete calls delete_measure, offers undo and reads again", async () => {
    let gone = false;
    server.use(
      http.get(`${BASE}/standing`, () => HttpResponse.json(standing)),
      http.get(`${BASE}/standing/measures`, () =>
        HttpResponse.json(gone ? { measures: measures.measures.filter((m) => m.id !== 21) } : measures),
      ),
    );
    const bodies = serveActions(() => {
      gone = true;
      return HttpResponse.json({ status: "applied", activity_id: 77, undo_id: 77, result: { id: 21, deleted: true }, confirmation: "측정값 지움" });
    });
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    await userEvent.click(await screen.findByRole("button", { name: "연봉(세전) 지우기" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].action).toBe("delete_measure");
    expect(bodies[0].args).toEqual({ id: 21 });
    expect(await screen.findByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "연봉(세전) 지우기" })).toBeNull());
  });

  it("offline says what the status screen says", async () => {
    server.use(http.get(`${BASE}/standing`, () => HttpResponse.error()), http.get(`${BASE}/standing/measures`, () => HttpResponse.error()));
    renderWithProviders(<Standing />, { route: "/status/standing/", conn: "offline" });
    expect(await screen.findByText(copy.statusScreen.offline)).toBeInTheDocument();
  });

  it("back link is the status screen", async () => {
    serve();
    renderWithProviders(<Standing />, { route: "/status/standing/" });
    expect(await screen.findByRole("link", { name: "‹ 상태창" })).toHaveAttribute("href", "/status/");
  });

  it("money is shown in 만 원, rounded", () => {
    expect(standingCopy.krw(55_000_000)).toBe("5,500만 원");
    expect(standingCopy.krw(62_004_999)).toBe("6,200만 원");
    expect(standingCopy.krw(62_005_000)).toBe("6,201만 원");
    expect(standingCopy.krw(-3_000_000)).toBe("-300만 원");
  });

  it("only its stylesheet comes with _app (its code stays in the page chunk)", () => {
    const app = readFileSync(join(__dirname, "../pages/_app.tsx"), "utf8");
    expect(app).toMatch(/import "\.\.\/screens\/Standing\.module\.css";/);
    expect(app).not.toMatch(/import "\.\.\/screens\/Standing";/);
  });
});

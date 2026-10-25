import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CurveHistory } from "../api/types.gen";
import { GLANCE_BAND_H, GLANCE_PAD, glanceLayout } from "../lib/history";
import history from "../test/fixtures/curve-history.json";
import { GlanceStrip } from "./GlanceStrip";

const data = history as CurveHistory;
const TODAY = "2026-10-25";
const W = 328;

describe("glanceLayout and GlanceStrip", () => {
  it("ticks_first_decades_and_this_year", () => {
    expect(glanceLayout(data, W, TODAY).ticks.map((t) => t.label)).toEqual(["2019", "2020", "2026"]);
    const old: CurveHistory = { ...data, since_year: 1994 };
    const ticks = glanceLayout(old, 600, TODAY).ticks;
    expect(ticks.map((t) => t.label)).toEqual(["1994", "2000", "2010", "2020", "2026"]);
    expect(ticks[0].x).toBe(GLANCE_PAD);
    expect(ticks[4].x).toBeGreaterThan(ticks[3].x);
    // a decade right next to the first year is left out so the labels do not touch
    expect(glanceLayout({ ...data, since_year: 1999 }, 300, TODAY).ticks.map((t) => t.label)).not.toContain("2000");
  });

  it("estimate_band_dashed", () => {
    const { container } = render(<GlanceStrip history={data} width={W} today={TODAY} />);
    const dashed = glanceLayout(data, W, TODAY).bands.map((b) => b.dashed);
    expect(dashed).toEqual([true, false]); // 꾸민 새 출발 is an estimate
    const rects = container.querySelectorAll("rect.glance-band");
    expect(rects).toHaveLength(2);
    expect(rects[0].classList.contains("glance-band-dashed")).toBe(true);
    expect(rects[1].classList.contains("glance-band-dashed")).toBe(false);
    // an open chapter runs to today, at the right edge of the plot
    const first = glanceLayout(data, W, TODAY).bands[0];
    expect(first.x + first.w).toBeCloseTo(W - GLANCE_PAD, 5);
  });

  it("ladder_line_height_or_none", () => {
    const bands = glanceLayout(data, W, TODAY).bands;
    expect(bands[0].ladderY).toBeCloseTo(GLANCE_BAND_H * (1 - 5.1 / 10), 5);
    expect(bands[1].ladderY).toBeCloseTo(GLANCE_BAND_H * 0.4, 5); // 6.0
    const none: CurveHistory = { ...data, chapters: data.chapters.map((c) => ({ ...c, ladder: null })) };
    expect(glanceLayout(none, W, TODAY).bands.map((b) => b.ladderY)).toEqual([null, null]);
    const { container } = render(<GlanceStrip history={none} width={W} today={TODAY} />);
    expect(container.querySelectorAll("line.glance-ladder")).toHaveLength(0);
    const { container: withLadder } = render(<GlanceStrip history={data} width={W} today={TODAY} />);
    expect(withLadder.querySelectorAll("line.glance-ladder")).toHaveLength(2);
  });

  it("marks_have_labels_and_table_matches", () => {
    render(<GlanceStrip history={data} width={W} today={TODAY} />);
    const svg = screen.getByRole("group", { name: "한눈에 보는 지난 길" });
    const marks = within(svg).getAllByRole("img");
    expect(marks.map((m) => m.getAttribute("aria-label")).sort()).toEqual(
      ["높은 때 꾸민 첫 전시", "높은 때 꾸민 첫 자전거", "전환점 꾸민 이사 결정", "힘든 때 꾸민 긴 감기"].sort(),
    );
    expect(marks[0].getAttribute("width")).toBe("16");
    expect(svg.getAttribute("viewBox")).toBe(`0 0 ${W} ${svg.getAttribute("height")}`);
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").map((c) => c.textContent))).toEqual([
      ["2025 –", "5.1", "2"],
      ["2023 – 2025", "6", "0"],
      ["—", "없음", "2"], // the group with no chapter
    ]);
    expect(within(rows[0]).getByRole("rowheader").textContent).toBe("꾸민 새 출발");
  });

  it("hidden_events_not_drawn", () => {
    const hidden: CurveHistory = { ...data, unassigned: { events: [], hidden_sensitive: { count: 3, years: [2020] } } };
    const g = glanceLayout(hidden, W, TODAY);
    expect(g.marks.map((m) => m.eventId).sort()).toEqual([1, 2]);
    const { container } = render(<GlanceStrip history={hidden} width={W} today={TODAY} />);
    expect(container.querySelectorAll(".glance-mark")).toHaveLength(2);
    expect(container.textContent).not.toContain("긴 감기");
  });

  it("no_area_fill_or_area_under_curve", () => {
    const { container } = render(<GlanceStrip history={data} width={W} today={TODAY} />);
    expect(container.querySelectorAll("path")).toHaveLength(0);
    expect(container.querySelectorAll("polygon, polyline")).toHaveLength(0);
    expect(container.innerHTML).not.toMatch(/--area|data-area|style=/);
    for (const el of container.querySelectorAll("[fill]")) expect(el.getAttribute("fill")).toBe("none");
  });

  it("is_empty_without_chapters_or_a_start_year", () => {
    const empty: CurveHistory = { ...data, since_year: null, chapters: [], unassigned: { events: [], hidden_sensitive: { count: 0, years: [] } } };
    expect(glanceLayout(empty, W, TODAY)).toEqual({ ticks: [], bands: [], marks: [] });
  });
});

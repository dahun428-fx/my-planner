import { describe, expect, it } from "vitest";
import type { Curve } from "../api/types.gen";
import curveEmpty from "../test/fixtures/curve-empty.json";
import curveMonth from "../test/fixtures/curve-month.json";
import curveYear from "../test/fixtures/curve-year.json";
import {
  axisTicks,
  chapterBands,
  conditionSeries,
  dayStart,
  kstX,
  ladderSeries,
  ladderSteps,
  milestoneX,
  radarRows,
  reassuranceCopy,
  thinTicks,
  visibleRange,
} from "./curveLayout";

const ladder = (period: string, now: number | null, future: number | null) => ({ period, now, future, note: null });

describe("ladderSeries", () => {
  it("ladder point on the 15th", () => {
    const s = ladderSeries([ladder("2026-10", 6, 8)], "2026-10-01", "2026-10-31");
    expect(s).toHaveLength(1);
    // 15일 정오 한국 시각 = 03:00 UTC
    expect(new Date(s[0].x).toISOString()).toBe("2026-10-15T03:00:00.000Z");
    expect(s[0]).toMatchObject({ period: "2026-10", now: 6, future: 8 });
  });

  it("ladder breaks on missing month", () => {
    const s = ladderSeries([ladder("2026-03", null, 7), ladder("2026-05", 5, 7)], "2026-03-01", "2026-06-30");
    expect(s.map((p) => p.period)).toEqual(["2026-03", "2026-04", "2026-05", "2026-06"]);
    expect(s.map((p) => p.now)).toEqual([null, null, 5, null]);
    expect(s.map((p) => p.future)).toEqual([7, null, 7, null]);
    expect(s.every((p) => p.now !== 0 && p.future !== 0)).toBe(true);
  });

  it("covers the month of `from` even when `from` is mid-month", () => {
    const s = ladderSeries([ladder("2026-09", 6, 7)], "2026-09-25", "2026-10-24");
    expect(s.map((p) => p.period)).toEqual(["2026-09", "2026-10"]);
    expect(s[0].now).toBe(6);
  });
});

describe("ladderSteps", () => {
  it("holds each month flat from its first to its last day and keeps empty months as breaks", () => {
    const s = ladderSteps(ladderSeries([ladder("2026-08", 5, 7), ladder("2026-10", 6, 8)], "2026-08-01", "2026-10-31"));
    expect(s.map((p) => [p.period, p.now])).toEqual([
      ["2026-08", 5],
      ["2026-08", 5],
      ["2026-09", null],
      ["2026-10", 6],
      ["2026-10", 6],
    ]);
    expect(s[0].x).toBe(dayStart("2026-08-01"));
    expect(s[1].x).toBe(dayStart("2026-09-01") - 1);
  });
});

describe("reassuranceCopy", () => {
  it("reassurance copy thresholds", () => {
    expect(reassuranceCopy(1.0)).toBe("기억보다 하루하루가 괜찮았던 달이에요");
    expect(reassuranceCopy(3.8)).toBe("기억보다 하루하루가 괜찮았던 달이에요");
    expect(reassuranceCopy(0.99)).toBe("기억과 하루하루가 비슷했던 달이에요");
    expect(reassuranceCopy(0)).toBe("기억과 하루하루가 비슷했던 달이에요");
    expect(reassuranceCopy(-0.99)).toBe("기억과 하루하루가 비슷했던 달이에요");
    expect(reassuranceCopy(-1.0)).toBe("하루하루는 버거웠지만 한 달을 좋게 기억하는 달이에요");
    expect(reassuranceCopy(null)).toBe("이 달은 컨디션 기록이 적어서 비교하지 않았어요");
  });
});

describe("conditionSeries", () => {
  it("moves the 1~5 average to 0~10 and skips buckets with no record", () => {
    const s = conditionSeries([
      { bucket: "2026-10-01", start: "2026-10-01", end: "2026-10-01", average: 1, days_logged: 1 },
      { bucket: "2026-10-02", start: "2026-10-02", end: "2026-10-02", average: null, days_logged: 0 },
      { bucket: "2026-10-03", start: "2026-10-03", end: "2026-10-03", average: 3.4, days_logged: 1 },
      { bucket: "2026-10-04", start: "2026-10-04", end: "2026-10-04", average: 5, days_logged: 1 },
    ]);
    expect(s.map((p) => p.bucket)).toEqual(["2026-10-01", "2026-10-03", "2026-10-04"]);
    expect(s.map((p) => p.y)).toEqual([0, 6, 10]);
    expect(new Date(s[0].x).toISOString()).toBe("2026-10-01T03:00:00.000Z"); // a day sits at its noon
  });
});

describe("milestoneX", () => {
  it("puts a day at its noon, a month on the 15th and a year at 1 July", () => {
    expect(new Date(milestoneX("2026-02-14", "day")).toISOString()).toBe("2026-02-14T03:00:00.000Z");
    expect(milestoneX("2025-09", "month")).toBe(kstX(2025, 9, 15, 12));
    expect(milestoneX("2019", "year")).toBe(kstX(2019, 7, 1, 12));
  });
});

describe("chapterBands", () => {
  it("clips to the range and runs an open chapter to the end", () => {
    const c = curveMonth as Curve;
    const bands = chapterBands(c.chapters, c.from, c.to);
    expect(bands.map((b) => b.title)).toEqual(["꾸민 배움의 해", "꾸민 새 출발"]);
    expect(bands[0].x1).toBe(dayStart("2024-11-01"));
    expect(bands[0].x2).toBe(dayStart("2025-03-01"));
    expect(bands[1].x1).toBe(dayStart("2025-03-01"));
    expect(bands[1].x2).toBe(dayStart("2026-11-01"));
    expect(bands.map((b) => b.index)).toEqual([0, 1]);
  });

  it("drops a chapter outside the range", () => {
    const c = curveMonth as Curve;
    expect(chapterBands(c.chapters, "2026-09-25", "2026-10-24").map((b) => b.title)).toEqual(["꾸민 새 출발"]);
  });
});

describe("visibleRange", () => {
  it("is the API range, except the year zoom starts at its earliest data", () => {
    expect(visibleRange(curveMonth as Curve)).toEqual({ from: "2024-11-01", to: "2026-10-31" });
    expect(visibleRange(curveYear as Curve)).toEqual({ from: "2019-01-01", to: "2026-12-31" });
    expect(visibleRange({ ...(curveEmpty as Curve), zoom: "year", from: "1900-01-01", to: "2026-12-31" })).toEqual({
      from: "2026-01-01",
      to: "2026-12-31",
    });
  });
});

describe("axisTicks", () => {
  it("labels years on the year and quarter zooms and stays sparse", () => {
    const ticks = axisTicks("year", "2019-01-01", "2026-12-31");
    expect(ticks.map((t) => t.label)).toEqual(["2019", "2021", "2023", "2025"]);
    expect(axisTicks("quarter", "2022-01-01", "2026-12-31").map((t) => t.label)).toEqual(["2022", "2023", "2024", "2025", "2026"]);
  });

  it("labels quarter months on the month zoom with the year in January", () => {
    expect(axisTicks("month", "2024-11-01", "2026-10-31").map((t) => t.label)).toEqual([
      "2025",
      "4월",
      "7월",
      "10월",
      "2026",
      "4월",
      "7월",
      "10월",
    ]);
  });

  it("counts days back from the last day on the day zoom", () => {
    const ticks = axisTicks("day", "2026-09-25", "2026-10-24");
    expect(ticks.at(-1)!.label).toBe("10/24");
    expect(ticks.map((t) => t.label)).toEqual(["9/26", "10/3", "10/10", "10/17", "10/24"]);
  });
});

describe("thinTicks", () => {
  it("keeps at most `max` labels, from the first", () => {
    const ticks = axisTicks("month", "2024-11-01", "2026-10-31");
    expect(thinTicks(ticks, 10)).toBe(ticks);
    expect(thinTicks(ticks, 5).map((t) => t.label)).toEqual(["2025", "7월", "2026", "7월"]);
  });
});

describe("radarRows", () => {
  it("compares the latest quarter with the one right before and marks what went down", () => {
    const r = radarRows((curveMonth as Curve).areas);
    expect(r.latest).toBe("2026-Q4");
    expect(r.previous).toBe("2026-Q3");
    expect(r.rows.map((x) => x.area)).toEqual(["career", "finance", "health", "relationships", "learning", "quality_of_life"]);
    expect(r.rows.filter((x) => x.down).map((x) => x.area)).toEqual(["health"]);
    expect(r.rows.find((x) => x.area === "health")).toMatchObject({ label: "건강", now: 4, prev: 6 });
  });

  it("has no dashed quarter when the one right before is missing", () => {
    const r = radarRows([
      { period: "2026-Q2", scores: { health: 8 } },
      { period: "2026-Q4", scores: { health: 4 } },
    ]);
    expect(r.previous).toBeNull();
    expect(r.rows.every((x) => !x.down && x.prev === null)).toBe(true);
    expect(r.rows.find((x) => x.area === "career")!.now).toBeNull();
  });

  it("is empty without area scores", () => {
    expect(radarRows([])).toEqual({ latest: null, previous: null, rows: [] });
  });
});

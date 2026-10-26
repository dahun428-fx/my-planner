import { describe, expect, it } from "vitest";
import type { EventItem } from "../api/types.gen";
import { addMonths, clockOf, dayName, dayOrder, isDate, monthGrid, weekdayIndex, weekOf, whenOf } from "./schedule";

const ev = (id: number, start: string | null): EventItem => ({
  event_id: id,
  date: "2026-10-26",
  start,
  end: null,
  all_day: start === null,
  title: `e${id}`,
  area: null,
  remind_min: 10,
  repeat: "none",
  origin: "user",
});

describe("schedule dates", () => {
  it("weekOf gives Monday to Sunday", () => {
    expect(weekOf("2026-10-28")).toEqual(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]);
    expect(weekOf("2026-11-01")[0]).toBe("2026-10-26"); // Sunday belongs to the week before
    expect(weekOf("2026-10-26")[0]).toBe("2026-10-26");
  });

  it("weekdayIndex counts from Monday", () => {
    expect(weekdayIndex("2026-10-26")).toBe(0);
    expect(weekdayIndex("2026-11-01")).toBe(6);
  });

  it("monthGrid covers the month in whole Monday weeks", () => {
    const g = monthGrid("2026-10");
    expect(g[0][0]).toBe("2026-09-28");
    expect(g.at(-1)?.at(-1)).toBe("2026-11-01");
    expect(g).toHaveLength(5);
    expect(g.every((w) => w.length === 7)).toBe(true);
    expect(monthGrid("2027-02").flat()).toContain("2027-02-28");
  });

  it("addMonths crosses years", () => {
    expect(addMonths("2026-12", 1)).toBe("2027-01");
    expect(addMonths("2026-01", -1)).toBe("2025-12");
  });

  it("isDate takes real days only", () => {
    expect(isDate("2026-10-27")).toBe(true);
    expect(isDate("2026-02-30")).toBe(false);
    expect(isDate("2026-1-2")).toBe(false);
    expect(isDate(undefined)).toBe(false);
  });

  it("dayOrder: all-day first, then by start", () => {
    const out = dayOrder([ev(1, "2026-10-26T05:00:00Z"), ev(2, null), ev(3, "2026-10-26T01:00:00Z")]);
    expect(out.map((e) => e.event_id)).toEqual([2, 3, 1]);
  });

  it("labels: day name, clock in Seoul, 10장 일정 때", () => {
    expect(dayName("2026-10-27")).toBe("10월 27일 (화)");
    expect(clockOf(ev(1, "2026-10-26T05:00:00Z"))).toBe("14:00");
    expect(clockOf(ev(2, null))).toBe("하루 종일");
    const base = { date: "2026-10-26", time: "10:00", all_day: false, weekdays: null } as const;
    expect(whenOf({ ...base, repeat: "none" })).toBe("10/26 10:00");
    expect(whenOf({ ...base, time: null, all_day: true, repeat: "none" })).toBe("10/26 하루 종일");
    expect(whenOf({ ...base, repeat: "daily" })).toBe("매일 10:00");
    expect(whenOf({ ...base, repeat: "weekly", weekdays: ["wed", "mon"] })).toBe("매주 월·수 10:00");
    expect(whenOf({ ...base, date: "2027-01-31", repeat: "monthly" })).toBe("매달 31일 10:00");
  });
});

import { describe, expect, it } from "vitest";
import { makeTodo } from "../../test/parts";
import { candidateLabel, dayLabel, dayTitle, isoWeekOf, relativeDay, rowMeta, weekMonday, weekTitle, weekdayKo } from "./dates";

// Runs in the device zone and under `npm run test:tz` (America/Los_Angeles): a logical date has no zone.
const TODAY = "2026-10-24";

describe("dates", () => {
  it("weekday of logical date", () => {
    expect(weekdayKo("2026-10-24")).toBe("토");
    expect(weekdayKo("2026-11-01")).toBe("일");
    expect(dayLabel("2026-10-27")).toBe("10월 27일 (화)");
  });

  it("relative day", () => {
    expect(relativeDay("2026-10-24", TODAY)).toBe("today");
    expect(relativeDay("2026-10-25", TODAY)).toBe("tomorrow");
    expect(relativeDay("2026-10-23", TODAY)).toBe("yesterday");
    expect(relativeDay("2026-10-27", TODAY)).toBeNull();
    expect(relativeDay("2026-11-01", "2026-10-31")).toBe("tomorrow");
  });

  it("row meta", () => {
    const t = makeTodo(1, "회의");
    // 05:00Z is 14:00 in Seoul.
    expect(rowMeta({ ...t, scheduled_at: "2026-10-24T05:00:00Z" }, TODAY)).toBe("14:00");
    expect(rowMeta({ ...t, planned_for: "2026-10-27" }, TODAY)).toBe("10월 27일 (화)");
    expect(rowMeta({ ...t, planned_for: TODAY }, TODAY)).toBeNull();
    expect(rowMeta({ ...t, status: "dropped" }, TODAY)).toBe("뺌");
    expect(rowMeta({ ...t, planned_for: null }, TODAY)).toBeNull();
    // An older BE sends neither `today` nor the two fields.
    expect(rowMeta({ id: 1, title: "회의", status: "open" }, undefined)).toBeNull();
  });

  it("iso weeks", () => {
    expect(isoWeekOf("2026-10-24")).toBe("2026-W43");
    expect(isoWeekOf("2026-10-26")).toBe("2026-W44");
    expect(isoWeekOf("2026-01-01")).toBe("2026-W01");
    expect(isoWeekOf("2027-01-01")).toBe("2026-W53");
    expect(weekMonday("2026-W44")).toBe("2026-10-26");
    expect(weekMonday("2026-W01")).toBe("2025-12-29");
  });

  it("titles from data.today", () => {
    expect(dayTitle("2026-10-24", TODAY)).toBe("오늘");
    expect(dayTitle("2026-10-25", TODAY)).toBe("내일");
    expect(dayTitle("2026-10-23", TODAY)).toBe("어제");
    expect(dayTitle("2026-10-27", TODAY)).toBe("10월 27일 (화)");
    expect(weekTitle("2026-W43", TODAY)).toBe("이번 주");
    expect(weekTitle("2026-W44", TODAY)).toBe("다음 주");
    expect(weekTitle("2026-W42", TODAY)).toBe("지난주");
    expect(weekTitle("2026-W46", TODAY)).toBe("11월 9일 ~ 11월 15일");
    expect(weekTitle("2026-W44", undefined)).toBe("10월 26일 ~ 11월 1일");
    expect(candidateLabel("2026-10-24", TODAY)).toBe("오늘 · 10월 24일 (토)");
    expect(candidateLabel("2026-10-25", TODAY)).toBe("내일 · 10월 25일 (일)");
    expect(candidateLabel("2026-10-27", TODAY)).toBe("10월 27일 (화)");
    expect(candidateLabel("2026-10-27", undefined)).toBe("10월 27일 (화)");
  });
});

import { describe, expect, it } from "vitest";
import { copy } from "./copy";
import { addDays, formatKst, kstToUtcIso, relativeChecked } from "./time";

describe("time", () => {
  it("shows KST regardless of device time zone", () => {
    expect(formatKst("2026-10-24T08:00:05Z", "HH:mm")).toBe("17:00");
    expect(formatKst("2026-10-23T16:30:00Z", "date")).toBe("2026-10-24");
    // 01:30 KST on the 24th is still the 23rd on the device clock in the US and in UTC
    expect(formatKst("2026-10-23T16:30:00Z", "HH:mm")).toBe("01:30");
    expect(formatKst("2026-10-24T15:00:00Z", "HH:mm")).toBe("00:00");
    expect(formatKst("2026-10-24T09:05:00Z", copy.dateStyle.monthDay)).toBe("10월 24일");
    expect(formatKst("2026-01-02T00:05:00Z", copy.dateStyle.monthDayTime)).toBe("1월 2일 09:05");
  });

  it("adds days on logical date", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addDays("2026-10-24", 0)).toBe("2026-10-24");
  });

  it("says how long ago a check was", () => {
    const t = Date.parse("2026-10-24T08:00:00Z");
    expect(relativeChecked("2026-10-24T07:59:40Z", t)).toBe(copy.settings.checkedJustNow);
    expect(relativeChecked("2026-10-24T07:55:00Z", t)).toBe(copy.settings.checkedMinutesAgo(5));
  });
});

describe("kstToUtcIso", () => {
  it("reads the wall clock as Seoul time whatever the device zone is", () => {
    expect(kstToUtcIso("2026-10-25", "14:00")).toBe("2026-10-25T05:00:00Z");
    expect(kstToUtcIso("2026-10-25", "00:30")).toBe("2026-10-24T15:30:00Z");
  });
});

describe("logicalDateOf", () => {
  it("counts the hours before 04:00 Seoul as the day before", async () => {
    const { logicalDateOf } = await import("./time");
    expect(logicalDateOf("2026-10-24T15:30:00Z")).toBe("2026-10-24"); // 00:30 on the 25th
    expect(logicalDateOf("2026-10-24T18:59:00Z")).toBe("2026-10-24"); // 03:59
    expect(logicalDateOf("2026-10-24T19:00:00Z")).toBe("2026-10-25"); // 04:00
  });
});

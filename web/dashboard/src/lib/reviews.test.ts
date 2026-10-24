import { afterEach, describe, expect, it } from "vitest";
import { lastSunday, nextMonthlyReview, nextQuarterReview, reviewDayLabel, seoulToday } from "./reviews";

const original = process.env.TZ;

describe("review dates (SP3-4 11.2)", () => {
  afterEach(() => {
    process.env.TZ = original;
  });

  it("reads today in Korea whatever the device zone", () => {
    for (const tz of ["UTC", "America/Los_Angeles"]) {
      process.env.TZ = tz;
      expect(seoulToday(new Date("2026-10-24T14:59:59Z"))).toBe("2026-10-24");
      expect(seoulToday(new Date("2026-10-24T15:00:00Z"))).toBe("2026-10-25");
    }
  });

  it("finds the last Sunday of a month", () => {
    expect(lastSunday(2026, 10)).toBe("2026-10-25");
    expect(lastSunday(2026, 11)).toBe("2026-11-29");
    expect(lastSunday(2026, 12)).toBe("2026-12-27");
    expect(lastSunday(2027, 1)).toBe("2027-01-31");
    expect(lastSunday(2027, 2)).toBe("2027-02-28");
    expect(lastSunday(2027, 3)).toBe("2027-03-28");
  });

  it("monthly ladder: the last Sunday of this month, or of the next once it has passed", () => {
    expect(nextMonthlyReview("2026-10-24")).toBe("2026-10-25");
    expect(nextMonthlyReview("2026-10-25")).toBe("2026-10-25"); // the review day itself
    expect(nextMonthlyReview("2026-10-26")).toBe("2026-11-29");
    expect(nextMonthlyReview("2026-12-28")).toBe("2027-01-31");
  });

  it("quarterly areas: the last Sunday of the quarter's last month (its last week)", () => {
    expect(nextQuarterReview("2026-10-24")).toBe("2026-12-27");
    expect(nextQuarterReview("2026-12-27")).toBe("2026-12-27");
    expect(nextQuarterReview("2026-12-28")).toBe("2027-03-28");
    expect(nextQuarterReview("2026-09-27")).toBe("2026-09-27");
    expect(nextQuarterReview("2026-09-28")).toBe("2026-12-27");
    expect(nextQuarterReview("2027-01-01")).toBe("2027-03-28");
  });

  it("writes a review day as M월 D일(요일)", () => {
    expect(reviewDayLabel("2026-10-25")).toBe("10월 25일(일)");
    expect(reviewDayLabel("2026-12-27")).toBe("12월 27일(일)");
    expect(reviewDayLabel("2027-03-03")).toBe("3월 3일(수)");
  });
});

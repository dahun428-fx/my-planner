import { afterEach, describe, expect, it } from "vitest";
import { formatDay, formatKst } from "./time";

const original = process.env.TZ;

describe("formatKst", () => {
  afterEach(() => {
    process.env.TZ = original;
  });

  it("shows KST regardless of device time zone", () => {
    for (const tz of ["UTC", "America/Los_Angeles"]) {
      process.env.TZ = tz;
      // the zone really changed for this process (Los Angeles is UTC-7 on this date)
      expect(new Date("2026-10-24T08:00:05Z").getTimezoneOffset()).toBe(tz === "UTC" ? 0 : 420);
      expect(formatKst("2026-10-24T08:00:05Z", "HH:mm:ss")).toBe("17:00:05");
      expect(formatKst("2026-10-24T08:00:05Z", "HH:mm")).toBe("17:00");
      expect(formatKst("2026-10-24T08:00:05Z", "M/D HH:mm")).toBe("10/24 17:00");
      expect(formatKst("2026-10-24T15:30:00Z", "M/D HH:mm")).toBe("10/25 00:30");
      expect(formatKst("2026-10-24T15:30:00Z", "M/D")).toBe("10/25");
    }
  });

  it("reads offsets other than Z", () => {
    expect(formatKst("2026-10-24T10:00:00+09:00", "HH:mm")).toBe("10:00");
  });

  it("returns a dash for an unreadable time", () => {
    expect(formatKst("어제", "HH:mm")).toBe("—");
  });
});

describe("formatDay", () => {
  it("drops the year and leading zeros", () => {
    expect(formatDay("2026-10-04")).toBe("10/4");
    expect(formatDay("2026-01-25")).toBe("1/25");
    expect(formatDay("10/4")).toBe("—");
  });
});

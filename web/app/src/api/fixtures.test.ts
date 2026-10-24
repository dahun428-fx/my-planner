import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { type ModelName, validateModel } from "./validate";

// [fixture file, model]. Tickets that add fixtures add rows here.
const table: [string, ModelName][] = [
  ["health.json", "Health"],
  ["health-degraded.json", "Health"],
  ["health-safe-mode.json", "SafeModeHealth"],
  ["today.json", "Today"],
  ["today-empty.json", "Today"],
  ["checkins-today.json", "CheckinList"],
  ["catalog.json", "UiCatalog"],
  ["checkin-341.json", "CheckinDetail"],
  ["checkin-341-answered.json", "CheckinDetail"],
  ["checkin-341-missed.json", "CheckinDetail"],
  ["checkin-340-brief.json", "CheckinDetail"],
  ["today-cards.json", "Today"],
  ["week.json", "Week"],
  ["priorities-month.json", "Priorities"],
  ["priorities-quarter.json", "Priorities"],
  ["priorities-year.json", "Priorities"],
  ["drafts.json", "Drafts"],
  ["activity-desc-1.json", "ActivityResponse"],
  ["activity-desc-2.json", "ActivityResponse"],
  ["activity-asc.json", "ActivityResponse"],
  ["notify.json", "NotifySettings"],
  ["notify-effective-telegram.json", "NotifySettings"],
  ["health-paused.json", "Health"],
];

// The BE before R4a has no `next_before` key at all, so that fixture is checked as the client reads it (key absent -> null).
const OLD_BE = new Set(["activity-asc.json"]);

const dir = join(__dirname, "../test/fixtures");

describe("fixtures match schema.json", () => {
  it.each(table)("%s is a valid %s", (file, model) => {
    const value: unknown = JSON.parse(readFileSync(join(dir, file), "utf8"));
    const checked = OLD_BE.has(file) ? { next_before: null, ...(value as object) } : value;
    expect(validateModel(model, checked)).toBe(true);
  });

  it("every fixture file is in the table", () => {
    const files = readdirSync(dir).filter((f) => f.endsWith(".json")).sort();
    expect(files).toEqual(table.map(([f]) => f).sort());
  });
});

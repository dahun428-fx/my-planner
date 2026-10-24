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
];

const dir = join(__dirname, "../test/fixtures");

describe("fixtures match schema.json", () => {
  it.each(table)("%s is a valid %s", (file, model) => {
    const value: unknown = JSON.parse(readFileSync(join(dir, file), "utf8"));
    expect(validateModel(model, value)).toBe(true);
  });

  it("every fixture file is in the table", () => {
    const files = readdirSync(dir).filter((f) => f.endsWith(".json")).sort();
    expect(files).toEqual(table.map(([f]) => f).sort());
  });
});

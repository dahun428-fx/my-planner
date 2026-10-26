import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import catalogJson from "../../test/fixtures/catalog.json";
import { type Catalog, makePropsCheck } from "../catalog";
import { checkBlock } from "./checkBlock";

// SP6 spec 13 (app schema): the BE's shared props fixtures, read in place (never copied). `ok`
// passes the catalog schema (and checkBlock for ui_block); `bad` fails, except the codes only the
// BE can judge (10.3, B9, and model_validator rules JSON Schema cannot say: gap 10).
// In jsdom `import.meta.url` is not a file: URL, so the path is built from __dirname.
const DIR = path.join(__dirname, "../../../../../tests/fixtures/ui_props");
const BE_ONLY = ["bad_char", "banned_word", "slash", "too_large", "period_one", "value_over_max", "not_unique"];
// 7.2 / 10.1: integer lists carry `uniqueItems`, so their `not_unique` is judged on both sides.
// Only the candidate dates' `not_unique` (ui_date_choice) is the BE's alone.
const BOTH_SIDES = (name: string, file: string) => file.startsWith("not_unique") && name !== "ui_date_choice";
const beOnly = (name: string, file: string) => BE_ONLY.some((code) => file.startsWith(`${code}-`)) && !BOTH_SIDES(name, file);

const check = makePropsCheck(catalogJson as Catalog);
const accepts = (name: string, props: unknown) => check(name, props) && (name !== "ui_block" || checkBlock(props));

const cases = fs.readdirSync(DIR).flatMap((name) =>
  (["ok", "bad"] as const).flatMap((kind) => {
    const dir = path.join(DIR, name, kind);
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((file) => ({ name, kind, file }));
  }),
);

describe("shared ui props fixtures", () => {
  it("fixture dir is not empty", () => {
    expect(cases.length).toBeGreaterThan(20);
    expect(cases.some((c) => c.name === "ui_block" && c.kind === "ok")).toBe(true);
  });

  it.each(cases.filter((c) => !(c.kind === "bad" && beOnly(c.name, c.file))))("$name/$kind/$file", ({ name, kind, file }) => {
    const props: unknown = JSON.parse(fs.readFileSync(path.join(DIR, name, kind, file), "utf8"));
    expect(accepts(name, props)).toBe(kind === "ok");
  });
});

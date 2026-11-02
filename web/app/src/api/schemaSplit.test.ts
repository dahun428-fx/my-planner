import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import lateList from "../../scripts/late-models.json";
import schema from "./schema.json";
import late from "./schema.late.json";

// SP15 global constraints ("스키마가 첫 로드에 든다"): schema.json is bundled into `_app` through
// validate.ts, so the models in scripts/late-models.json live in schema.late.json, which only
// validateLate.ts reads. The first screen's files must not pull validateLate (or api/panel) in.
const src = join(__dirname, "..");

const firstLoadFiles = (): string[] => {
  const lib = readdirSync(join(src, "lib"))
    .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
    .filter((f) => f.endsWith(".ts") || f.startsWith("ConnectionProvider"))
    .map((f) => `lib/${f}`);
  const components = readdirSync(join(src, "components"))
    .filter((f) => f.startsWith("ConnectionProvider"))
    .map((f) => `components/${f}`);
  return ["api/client.ts", "api/validate.ts", "pages/_app.tsx", "ui/registry.tsx", ...lib, ...components];
};

describe("schema split (SP15)", () => {
  it("schema.json and schema.late.json share no model", () => {
    const first = Object.keys(schema.models);
    const later = Object.keys(late.models);
    expect(first.filter((name) => later.includes(name))).toEqual([]);
  });

  it("the late models are exactly the late-models.json list", () => {
    expect(Object.keys(late.models).sort()).toEqual([...lateList.models].sort());
    expect(late.api).toBe(schema.api);
  });

  it("first-load files do not import validateLate or api/panel", () => {
    const files = firstLoadFiles();
    expect(files).toContain("lib/ConnectionProvider.tsx");
    for (const file of files) {
      const text = readFileSync(join(src, file), "utf8");
      expect(text, file).not.toMatch(/validateLate|api\/panel|\.\/panel["']/);
    }
  });
});

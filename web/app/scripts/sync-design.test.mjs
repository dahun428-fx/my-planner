// @vitest-environment node
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { HEADER, SOURCE, TARGET, designCopy, syncDesign } from "./sync-design.mjs";

let dirs = [];
afterEach(() => {
  dirs.forEach((d) => rmSync(d, { recursive: true, force: true }));
  dirs = [];
});

describe("sync:design", () => {
  // DESIGN.md: web/shared/global.css is the single source; the app's copy must be the same bytes
  // under the generated-file header. Run `npm run sync:design` after changing the source.
  it("the app's copy matches web/shared/global.css", () => {
    expect(SOURCE).toBe(fileURLToPath(new URL("../../shared/global.css", import.meta.url)));
    expect(TARGET).toBe(fileURLToPath(new URL("../src/styles/global.css", import.meta.url)));
    expect(readFileSync(TARGET, "utf8")).toBe(designCopy(readFileSync(SOURCE, "utf8")));
  });

  it("puts the generated-file header first and keeps the source as it is", () => {
    expect(HEADER).toMatch(/GENERATED/);
    expect(HEADER).toMatch(/web\/shared\/global\.css/);
    expect(HEADER).toMatch(/npm run sync:design/);
    expect(designCopy(":root{}\n")).toBe(`${HEADER}\n:root{}\n`);
  });

  it("writes the copy and says whether it changed", () => {
    const dir = mkdtempSync(join(tmpdir(), "sync-design-"));
    dirs.push(dir);
    const src = join(dir, "global.css");
    const out = join(dir, "copy.css");
    writeFileSync(src, ":root { --x: 1px; }\n");
    expect(syncDesign(src, out)).toBe(true);
    expect(readFileSync(out, "utf8")).toBe(designCopy(":root { --x: 1px; }\n"));
    expect(syncDesign(src, out)).toBe(false);
  });
});

// @vitest-environment node
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import {
  HEADER,
  PICTO_SOURCE,
  PICTO_TARGET,
  SOURCE,
  TARGET,
  designCopy,
  parseSymbols,
  pictogramsModule,
  syncDesign,
} from "./sync-design.mjs";

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

// Spec 9.1 table, in table order. SP9 adds three ids and changes this list with the table.
const SPEC_IDS = [
  "career", "finance", "health", "relationships", "learning", "quality_of_life", "high", "low", "turning_point", "chapter", "condition", "ladder", "level", "quest", "review", "todo", "habit", "memory", "future", "eye", "eyeoff", "assistant", "home", "curve", "status", "list", "estimate", "settings",
  "dumbbell", "compass", // SP14 10장: the partners (운동메이트, 라이프 매니저)
];
const DRAFT = fileURLToPath(new URL("../../../docs/design/pictograms-draft.json", import.meta.url));

describe("pictograms", () => {
  const svg = () => readFileSync(PICTO_SOURCE, "utf8");

  it("the pictogram copy matches web/shared/pictograms.svg", () => {
    expect(PICTO_SOURCE).toBe(fileURLToPath(new URL("../../shared/pictograms.svg", import.meta.url)));
    expect(PICTO_TARGET).toBe(fileURLToPath(new URL("../src/components/pictograms.gen.tsx", import.meta.url)));
    expect(readFileSync(PICTO_TARGET, "utf8")).toBe(pictogramsModule(svg()));
  });

  it("ids are exactly the spec 9.1 table", () => {
    expect(parseSymbols(svg()).map((s) => s.id)).toEqual(SPEC_IDS);
  });

  it("source matches docs/design/pictograms-draft.json", () => {
    const draft = JSON.parse(readFileSync(DRAFT, "utf8")).icons.map((i) => [i.id, i.markup]);
    expect(parseSymbols(svg()).map((s) => [s.id, s.children])).toEqual(draft);
  });

  it("source has no style, colour fill, script or foreignObject", () => {
    const text = svg();
    expect(text).not.toMatch(/style=|fill="(?!none)|<script|foreignObject/);
    for (const { children } of parseSymbols(text)) {
      for (const m of children.matchAll(/<\/?([a-zA-Z]+)/g)) expect(m[1]).toMatch(/^(path|circle|rect)$/);
      for (const m of children.matchAll(/\s([a-zA-Z-]+)=/g)) {
        expect(["d", "cx", "cy", "r", "x", "y", "width", "height", "rx", "stroke-width", "stroke-dasharray"]).toContain(m[1]);
      }
    }
    const marks = parseSymbols(text).filter((s) => /stroke-(width|dasharray)/.test(s.children)).map((s) => s.id);
    expect(marks).toEqual(["condition", "future", "list", "estimate"]);
  });

  it("module exports the sprite and the component", () => {
    const mod = pictogramsModule(svg());
    expect(mod).toContain("export function PictogramSprite");
    expect(mod).toContain("export function Pictogram");
    expect(mod).toContain("strokeWidth");
    expect(mod).toContain("strokeDasharray");
    expect(mod).toContain("#p-");
    expect(mod).not.toContain("stroke-width");
    expect(mod).not.toContain("stroke-dasharray");
  });

  it("writes both files and says whether either changed", () => {
    const dir = mkdtempSync(join(tmpdir(), "sync-design-"));
    dirs.push(dir);
    const css = join(dir, "global.css");
    const cssOut = join(dir, "copy.css");
    const out = join(dir, "pictograms.gen.tsx");
    writeFileSync(css, ":root{}\n");
    expect(syncDesign(css, cssOut, PICTO_SOURCE, out)).toBe(true);
    expect(readFileSync(out, "utf8")).toBe(pictogramsModule(svg()));
    expect(syncDesign(css, cssOut, PICTO_SOURCE, out)).toBe(false);
    writeFileSync(out, "stale");
    expect(syncDesign(css, cssOut, PICTO_SOURCE, out)).toBe(true);
  });
});

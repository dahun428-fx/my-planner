import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "Today.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const rule = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(([, sel]) => sel.split(",").some((s) => s.trim() === selector))?.[2] ?? "";

describe("Today styles", () => {
  // The secretary hue marks what the secretary made and links; a plain control is ink (as in A08).
  it("the brief's 더 보기 / 접기 is ink, not the secretary hue", () => {
    expect(rule(".more")).toMatch(/color:\s*var\(--text\)/);
  });
});

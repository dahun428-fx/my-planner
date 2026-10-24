import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function vars(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}
function blockAfter(selectorPattern: RegExp, from = css): string {
  const m = from.match(selectorPattern);
  if (!m || m.index === undefined) throw new Error(`no block for ${selectorPattern}`);
  const open = from.indexOf("{", m.index);
  return from.slice(open + 1, from.indexOf("}", open));
}
const mediaStart = css.indexOf("@media (prefers-color-scheme: dark)");
const COLORS = /^--(ground|surface|raised|bar|rule|border|control|text|muted|text-2|primary|on-primary|hue|positive|negative|notice-[\w]+)$/;
const colorsOf = (o: Record<string, string>) => Object.fromEntries(Object.entries(o).filter(([k]) => COLORS.test(k)));

const light = vars(blockAfter(/:root\s*\{/));
const dark = vars(blockAfter(/:root\s*\{/, css.slice(mediaStart)));
const themes = { light, dark };

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function ratio(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const PAIRS: [string, string][] = [
  ["--text", "--surface"],
  ["--text", "--ground"],
  ["--muted", "--surface"],
  ["--muted", "--ground"],
  ["--text-2", "--surface"],
  ["--text-2", "--raised"],
  ["--text", "--raised"],
  ["--hue", "--surface"],
  ["--hue", "--ground"],
  ["--negative", "--surface"],
  ["--positive", "--surface"],
  ["--on-primary", "--primary"],
  ["--notice-ink", "--notice-bg"],
];

function moduleCss(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return moduleCss(path);
    return name.endsWith(".module.css") ? [path] : [];
  });
}

describe("tokens contrast", () => {
  for (const [theme, t] of Object.entries(themes)) {
    it.each(PAIRS)(`${theme}: %s on %s is at least 4.5:1`, (fg, bg) => {
      expect(t[fg], fg).toMatch(/^#[0-9a-f]{6}$/i);
      expect(t[bg], bg).toMatch(/^#[0-9a-f]{6}$/i);
      expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
    });
  }

  it("theme overrides repeat the light and dark values", () => {
    expect(colorsOf(vars(blockAfter(/:root\[data-theme="light"\]\s*\{/)))).toEqual(colorsOf(light));
    expect(colorsOf(vars(blockAfter(/:root\[data-theme="dark"\]\s*\{/)))).toEqual(colorsOf(dark));
    expect(Object.keys(colorsOf(dark)).sort()).toEqual(Object.keys(colorsOf(light)).sort());
  });

  it("muted on raised is not used", () => {
    const offenders = moduleCss(join(__dirname, "..")).flatMap((file) => {
      const body = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      return [...body.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
        .filter(([, , decl]) => /background(-color)?\s*:\s*var\(--raised\)/.test(decl) && /(^|[;\s])color\s*:\s*var\(--muted\)/.test(decl))
        .map(([, sel]) => `${relative(join(__dirname, ".."), file)}: ${sel.trim()}`);
    });
    expect(offenders).toEqual([]);
  });
});

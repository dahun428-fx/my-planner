import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { PALETTE_GROUND, PALETTES } from "../lib/theme";

const css = readFileSync(join(__dirname, "tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function vars(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}
// Every rule block of tokens.css: its selector list and whether it sits in the dark media query.
type Block = { selectors: string[]; dark: boolean; body: string };
const blocks: Block[] = [];
{
  let dark = false;
  let head = 0;
  const brace = /[{}]/g;
  for (let m = brace.exec(css); m; m = brace.exec(css)) {
    const text = css.slice(head, m.index).trim();
    if (m[0] === "}") dark = false; // the end of an @media
    else if (text.startsWith("@media")) dark = text.includes("prefers-color-scheme: dark");
    else {
      const close = css.indexOf("}", m.index);
      blocks.push({ selectors: text.split(",").map((x) => x.trim().replace(/\s+/g, " ")), dark, body: css.slice(m.index + 1, close) });
      brace.lastIndex = close + 1;
    }
    head = brace.lastIndex;
  }
}
function block(selector: string, dark = false): Record<string, string> {
  const found = blocks.filter((b) => b.dark === dark && b.selectors.includes(selector));
  if (found.length === 0) throw new Error(`no block for ${selector}${dark ? " (dark media)" : ""}`);
  return Object.assign({}, ...found.map((b) => vars(b.body)));
}
const COLORS = /^--(ground|surface|raised|bar|rule|border|control|text|muted|text-2|primary|on-primary|hue|positive|negative|notice-[\w]+)$/;
const colorsOf = (o: Record<string, string>) => Object.fromEntries(Object.entries(o).filter(([k]) => COLORS.test(k)));

const light = colorsOf(block(":root"));
const dark = colorsOf(block(":root", true));
// The notice colours stay the ink ones in every palette (semantic, like --positive and --negative).
const notice = (t: Record<string, string>) => Object.fromEntries(Object.entries(t).filter(([k]) => k.startsWith("--notice-")));

// Each palette: its light set, the dark set under the media query, and the same dark set for
// data-theme="dark". Ink is the :root sets (no data-palette).
const sel = (p: string) => ({
  light: `:root[data-palette="${p}"]`,
  media: `:root[data-palette="${p}"]:not([data-theme="light"])`,
  dark: `:root[data-palette="${p}"][data-theme="dark"]`,
  nestedLight: `[data-palette="${p}"]`,
  nestedMedia: `:root:not([data-theme="light"]) [data-palette="${p}"]`,
  nestedDark: `:root[data-theme="dark"] [data-palette="${p}"]`,
});
const OTHERS = PALETTES.filter((p) => p !== "ink");
const sets: Record<string, Record<string, string>> = { "ink light": light, "ink dark": dark };
for (const p of OTHERS) {
  sets[`${p} light`] = { ...notice(light), ...colorsOf(block(sel(p).light)) };
  sets[`${p} dark`] = { ...notice(dark), ...colorsOf(block(sel(p).media, true)) };
}

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
  ["--text-2", "--ground"],
  ["--text", "--raised"],
  ["--hue", "--surface"],
  ["--hue", "--ground"],
  ["--hue", "--raised"],
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
  for (const [set, t] of Object.entries(sets)) {
    it.each(PAIRS)(`${set}: %s on %s is at least 4.5:1`, (fg, bg) => {
      expect(t[fg], fg).toMatch(/^#[0-9a-f]{6}$/i);
      expect(t[bg], bg).toMatch(/^#[0-9a-f]{6}$/i);
      expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
    });
  }

  it("theme overrides repeat the light and dark values", () => {
    expect(colorsOf(block(':root[data-theme="light"]'))).toEqual(light);
    expect(colorsOf(block(':root[data-theme="dark"]'))).toEqual(dark);
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort());
  });

  it.each(OTHERS)("%s sets every colour but the notice ones, and repeats its dark set for data-theme", (p) => {
    const keys = Object.keys(light).filter((k) => !k.startsWith("--notice-")).sort();
    expect(Object.keys(colorsOf(block(sel(p).light))).sort()).toEqual(keys);
    expect(Object.keys(colorsOf(block(sel(p).media, true))).sort()).toEqual(keys);
    expect(colorsOf(block(sel(p).dark))).toEqual(colorsOf(block(sel(p).media, true)));
  });

  // A swatch in Settings carries data-palette itself and shows that palette in the current mode.
  it.each(PALETTES)("%s also applies to an element that carries data-palette", (p) => {
    const s = sel(p);
    const ownLight = p === "ink" ? light : colorsOf(block(s.light));
    const ownDark = p === "ink" ? dark : colorsOf(block(s.media, true));
    expect({ ...notice(light), ...colorsOf(block(s.nestedLight)) }).toMatchObject(ownLight);
    expect({ ...notice(dark), ...colorsOf(block(s.nestedMedia, true)) }).toMatchObject(ownDark);
    expect({ ...notice(dark), ...colorsOf(block(s.nestedDark)) }).toMatchObject(ownDark);
  });

  it("browser chrome colours are each palette's ground", () => {
    for (const p of PALETTES) {
      expect(PALETTE_GROUND[p], p).toEqual({ light: sets[`${p} light`]["--ground"], dark: sets[`${p} dark`]["--ground"] });
    }
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

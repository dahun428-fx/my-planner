import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { DEFAULT_PALETTE, PALETTE_GROUND, PALETTES } from "../lib/theme";

// The design system's tokens (DESIGN.md, web/shared/global.css), read from the app's copy.
const css = readFileSync(join(__dirname, "global.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function vars(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}
// Every rule block of global.css: its selector list and whether it sits in the dark media query.
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
const pick = (re: RegExp) => (o: Record<string, string>) => Object.fromEntries(Object.entries(o).filter(([k]) => re.test(k)));
// The role colours a preset changes, and the semantic ones it never does.
const ROLE = /^--(ground|surface|raised|bar|rule|border|control|text|muted|text-2|primary|on-primary|hue)$/;
const SEMANTIC = /^--(positive|negative|notice-[\w]+)$/;
const AREA = /^--area-[\w-]+$/;
const roles = pick(ROLE);
const semantic = pick(SEMANTIC);
const areas = pick(AREA);

// The default (paper): :root, and under the dark media query :root:not([data-theme="light"]).
const rootLight = block(":root");
const rootDark = block(':root:not([data-theme="light"])', true);
const theme = { light: { ...semantic(rootLight), ...areas(rootLight) }, dark: { ...semantic(rootDark), ...areas(rootDark) } };

// Each preset: its light set, the dark set under the media query, and the same dark set for
// data-theme="dark". The second form of each is an element that carries data-palette (a swatch).
const sel = (p: string) => ({
  light: `:root[data-palette="${p}"]`,
  media: `:root[data-palette="${p}"]:not([data-theme="light"])`,
  dark: `:root[data-palette="${p}"][data-theme="dark"]`,
  nestedLight: `[data-palette="${p}"]`,
  nestedMedia: `:root:not([data-theme="light"]) [data-palette="${p}"]`,
  nestedDark: `:root[data-theme="dark"] [data-palette="${p}"]`,
});
const PRESETS = PALETTES.filter((p) => p !== DEFAULT_PALETTE);
const own: Record<string, { light: Record<string, string>; dark: Record<string, string> }> = {
  [DEFAULT_PALETTE]: { light: roles(rootLight), dark: roles(rootDark) },
};
for (const p of PRESETS) own[p] = { light: roles(block(sel(p).light)), dark: roles(block(sel(p).media, true)) };
const sets: Record<string, Record<string, string>> = {};
for (const p of PALETTES) {
  sets[`${p} light`] = { ...theme.light, ...own[p].light };
  sets[`${p} dark`] = { ...theme.dark, ...own[p].dark };
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
  ["--negative", "--ground"],
  ["--positive", "--surface"],
  ["--positive", "--ground"],
  ["--on-primary", "--primary"],
  ["--notice-ink", "--notice-bg"],
];
const AREAS = ["career", "finance", "health", "relationships", "learning", "quality-of-life"];

function moduleCss(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return moduleCss(path);
    return name.endsWith(".module.css") ? [path] : [];
  });
}
const declarations = () =>
  moduleCss(join(__dirname, "..")).flatMap((file) => {
    const body = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    return [...body.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, sel, decl]) => ({ where: `${relative(join(__dirname, ".."), file)}: ${sel.trim()}`, decl }));
  });

describe("tokens contrast", () => {
  it("has twelve sets: six presets, light and dark, paper first", () => {
    expect(Object.keys(sets)).toHaveLength(12);
    expect(PALETTES[0]).toBe("paper");
    expect(DEFAULT_PALETTE).toBe("paper");
  });

  for (const [set, t] of Object.entries(sets)) {
    it.each(PAIRS)(`${set}: %s on %s is at least 4.5:1`, (fg, bg) => {
      expect(t[fg], fg).toMatch(/^#[0-9a-f]{6}$/i);
      expect(t[bg], bg).toMatch(/^#[0-9a-f]{6}$/i);
      expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
    });

    // DESIGN.md: an area colour is also small tag letters, so text contrast on both papers.
    it.each(AREAS)(`${set}: --area-%s as text on --ground and --surface is at least 4.5:1`, (a) => {
      const c = t[`--area-${a}`];
      expect(c).toMatch(/^#[0-9a-f]{6}$/i);
      expect(ratio(c, t["--ground"]), "ground").toBeGreaterThanOrEqual(4.5);
      expect(ratio(c, t["--surface"]), "surface").toBeGreaterThanOrEqual(4.5);
    });
  }

  // DESIGN.md --control: the round check's ring and the off marks, a graphic (WCAG 1.4.11): 3:1 on
  // the paper a row sits on (--ground) and in a card (--surface). Field and pill outlines are --border.
  it.each(Object.keys(sets))("%s: --control on --ground and --surface is at least 3:1", (set) => {
    const t = sets[set];
    expect(ratio(t["--control"], t["--ground"])).toBeGreaterThanOrEqual(3);
    expect(ratio(t["--control"], t["--surface"])).toBeGreaterThanOrEqual(3);
  });

  // SP6 13장 "대비" (G-A3): the pairs the chat cards newly use stay in the 4.5:1 list above, so they
  // run in every preset, light and dark. The progress fill (3:1) is the test below.
  it("SP6 pairs are checked in all twelve sets", () => {
    expect(PAIRS).toEqual(expect.arrayContaining([["--text-2", "--raised"], ["--hue", "--surface"]]));
    expect(Object.keys(sets)).toEqual(PALETTES.flatMap((p) => [`${p} light`, `${p} dark`]));
  });

  // SP6 5.3.4: the progress bar's fill against its track is a graphic, 3:1 (WCAG 1.4.11).
  it.each(Object.keys(sets))("progress fill vs track: %s --primary on --raised is at least 3:1", (set) => {
    const t = sets[set];
    expect(ratio(t["--primary"], t["--raised"])).toBeGreaterThanOrEqual(3);
  });

  it("theme overrides repeat the light and dark values", () => {
    expect(roles(block(':root[data-theme="light"]'))).toEqual(own.paper.light);
    expect({ ...semantic(block(':root[data-theme="dark"]')), ...areas(block(':root[data-theme="dark"]')) }).toEqual(theme.dark);
    expect(roles(block(':root[data-theme="dark"]'))).toEqual(own.paper.dark);
    expect(Object.keys(own.paper.dark).sort()).toEqual(Object.keys(own.paper.light).sort());
    expect(Object.keys(theme.dark).sort()).toEqual(Object.keys(theme.light).sort());
  });

  it.each(PRESETS)("%s sets every role colour, and repeats its dark set for data-theme", (p) => {
    const keys = Object.keys(own.paper.light).sort();
    expect(Object.keys(own[p].light).sort()).toEqual(keys);
    expect(Object.keys(own[p].dark).sort()).toEqual(keys);
    expect(roles(block(sel(p).dark))).toEqual(own[p].dark);
  });

  // Semantic and area colours are fixed: a preset never changes them.
  it("no preset sets a semantic or area colour", () => {
    const offenders = blocks
      .filter((b) => b.selectors.some((s) => s.includes("[data-palette=")))
      .flatMap((b) => Object.keys(vars(b.body)).filter((k) => SEMANTIC.test(k) || AREA.test(k)).map((k) => `${b.selectors[0]} ${k}`));
    expect(offenders).toEqual([]);
  });

  // A swatch in Settings carries data-palette itself and shows that palette in the current mode.
  it.each(PALETTES)("%s also applies to an element that carries data-palette", (p) => {
    const s = sel(p);
    expect(roles(block(s.nestedLight))).toEqual(own[p].light);
    expect(roles(block(s.nestedMedia, true))).toEqual(own[p].dark);
    expect(roles(block(s.nestedDark))).toEqual(own[p].dark);
  });

  // DESIGN.md: "ink" keeps the achromatic set that was the default; only its --control is darker,
  // to meet the 3:1 above.
  it("ink keeps the old default's colours", () => {
    expect(own.ink.light).toMatchObject({ "--ground": "#f2f2f5", "--surface": "#ffffff", "--text": "#111113", "--muted": "#6a6a70", "--hue": "#1d5fbf" });
    expect(own.ink.dark).toMatchObject({ "--ground": "#000000", "--surface": "#1c1c1e", "--text": "#ffffff", "--muted": "#a1a1a6", "--hue": "#5b9bff" });
  });

  it("browser chrome colours are each palette's ground", () => {
    for (const p of PALETTES) {
      expect(PALETTE_GROUND[p], p).toEqual({ light: sets[`${p} light`]["--ground"], dark: sets[`${p} dark`]["--ground"] });
    }
  });

  // Before the first effect applies a choice, the browser chrome and the launch screen are paper's.
  it("the first paint's theme-color metas and the manifest are the default palette's ground", () => {
    const doc = readFileSync(join(__dirname, "../pages/_document.tsx"), "utf8");
    const metas = [...doc.matchAll(/name="theme-color" media="\(prefers-color-scheme: (light|dark)\)" content="(#[0-9a-f]{6})"/g)].map((m) => [m[1], m[2]]);
    expect(Object.fromEntries(metas)).toEqual(PALETTE_GROUND[DEFAULT_PALETTE]);
    const manifest = JSON.parse(readFileSync(join(__dirname, "../../public/manifest.webmanifest"), "utf8"));
    expect(manifest.theme_color).toBe(PALETTE_GROUND[DEFAULT_PALETTE].light);
    expect(manifest.background_color).toBe(PALETTE_GROUND[DEFAULT_PALETTE].light);
  });

  it("muted on raised is not used", () => {
    const offenders = declarations()
      .filter(({ decl }) => /background(-color)?\s*:\s*var\(--raised\)/.test(decl) && /(^|[;\s])color\s*:\s*var\(--muted\)/.test(decl))
      .map(({ where }) => where);
    expect(offenders).toEqual([]);
  });

  // DESIGN.md: the stage ramp is fill only, and an area colour never fills a large surface.
  it("ramp colours are never letters, area colours never a background", () => {
    const offenders = declarations()
      .filter(({ decl }) => /(^|[;\s])color\s*:\s*var\(--ramp-/.test(decl) || /background(-color)?\s*:\s*var\(--area-/.test(decl))
      .map(({ where }) => where);
    expect(offenders).toEqual([]);
  });
});

// DESIGN.md's front matter and global.css say the same colours (they change in the same commit).
describe("DESIGN.md front matter", () => {
  const designPath = join(__dirname, "../../../../DESIGN.md");
  const front = existsSync(designPath) ? (readFileSync(designPath, "utf8").split(/^---$/m)[1] ?? "") : "";
  const yaml = Object.fromEntries([...front.matchAll(/^\s+([\w-]+):\s*"(#[0-9a-fA-F]{6})"/gm)].map((m) => [m[1], m[2].toLowerCase()]));

  it("lists the paper sets, the area colours and the ramp as global.css has them", () => {
    expect(Object.keys(yaml).length).toBeGreaterThan(0);
    for (const [k, v] of Object.entries({ ...own.paper.light, ...theme.light })) {
      const name = k.slice(2);
      if (name in yaml) expect(yaml[name], name).toBe(v);
    }
    for (const [k, v] of Object.entries({ ...own.paper.dark, ...theme.dark })) {
      const name = `dark-${k.slice(2)}`;
      if (name in yaml) expect(yaml[name], name).toBe(v);
    }
    for (const k of ["ground", "surface", "raised", "rule", "border", "control", "text", "text-2", "muted", "primary", "on-primary", "hue", "positive", "negative"]) {
      expect(yaml[k], k).toBeDefined();
      expect(yaml[`dark-${k}`], `dark-${k}`).toBeDefined();
    }
    for (const a of AREAS) {
      expect(yaml[`area-${a}`], a).toBe(theme.light[`--area-${a}`]);
      expect(yaml[`dark-area-${a}`], a).toBe(theme.dark[`--area-${a}`]);
    }
    for (const i of [1, 2, 3, 4, 5]) expect(yaml[`ramp-${i}`]).toBe(rootLight[`--ramp-${i}`]);
  });
});

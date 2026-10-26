// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// The dashboard's tokens are the design system's (DESIGN.md, the copy of web/shared/global.css) plus the few
// chart and bar names of tokens.css, each one a shared role. Colours are read through their var() chains.
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");
const shared = strip(readFileSync(join(__dirname, "global.css"), "utf8"));
const tokens = strip(readFileSync(join(__dirname, "tokens.css"), "utf8"));
const globals = strip(readFileSync(join(__dirname, "globals.css"), "utf8"));

type Block = { selectors: string[]; dark: boolean; body: string };

/**
 * Every rule block: its selector list and whether it sits in the dark colour-scheme media query. Blocks in
 * any other @media (the narrow-screen gutter, reduced motion) are left out: they are not a colour theme.
 */
function blocksOf(css: string): Block[] {
  const out: Block[] = [];
  let dark = false;
  let other = false;
  let head = 0;
  const brace = /[{}]/g;
  for (let m = brace.exec(css); m; m = brace.exec(css)) {
    const text = css.slice(head, m.index).trim();
    if (m[0] === "}") dark = other = false; // the end of an @media
    else if (text.startsWith("@media")) {
      dark = text.includes("prefers-color-scheme: dark");
      other = !dark;
    } else if (text.startsWith("@font-face") || other) brace.lastIndex = css.indexOf("}", m.index) + 1;
    else {
      const close = css.indexOf("}", m.index);
      out.push({ selectors: text.split(",").map((x) => x.trim().replace(/\s+/g, " ")), dark, body: css.slice(m.index + 1, close) });
      brace.lastIndex = close + 1;
    }
    head = brace.lastIndex;
  }
  return out;
}

const vars = (body: string): Record<string, string> =>
  Object.fromEntries([...body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));

const all = [...blocksOf(shared), ...blocksOf(tokens)];
function declared(selector: string, dark: boolean): Record<string, string> {
  return Object.assign({}, ...all.filter((b) => b.dark === dark && b.selectors.includes(selector)).map((b) => vars(b.body)));
}

/** The paper theme (the default, no data-palette): light, the dark media query, and data-theme="dark". */
const light = declared(":root", false);
const themes: Record<string, Record<string, string>> = {
  light,
  darkMedia: { ...light, ...declared(':root:not([data-theme="light"])', true) },
  dark: { ...light, ...declared(':root[data-theme="dark"]', false) },
};

/** Follow var() until a hex comes out (`var(--a, fallback)` takes --a). */
function resolve(set: Record<string, string>, name: string, seen: string[] = []): string {
  if (seen.includes(name)) throw new Error(`var() loop: ${[...seen, name].join(" > ")}`);
  const value = set[name];
  if (value === undefined) throw new Error(`${name} is not defined`);
  const ref = /^var\(\s*(--[\w-]+)/.exec(value);
  return ref ? resolve(set, ref[1], [...seen, name]) : value.toLowerCase();
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// B6: a condition dot on the curve sits on the panel or on a chapter band (raised or ground).
describe("condition dot colour", () => {
  it("is a var() of a shared role, not a hex of its own", () => {
    expect(light["--condition-dot"]).toMatch(/^var\(--[\w-]+\)$/);
  });

  it.each(Object.keys(themes))("is at least 3:1 against every curve background (%s)", (name) => {
    const t = themes[name];
    const dot = resolve(t, "--condition-dot");
    expect(dot).toMatch(/^#[0-9a-f]{6}$/);
    for (const bg of ["--surface", "--raised", "--ground"]) {
      expect(contrast(dot, resolve(t, bg)), `${name} ${bg}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("the two dark sets agree", () => {
    expect(resolve(themes.darkMedia, "--condition-dot")).toBe(resolve(themes.dark, "--condition-dot"));
    expect(resolve(themes.darkMedia, "--condition-dot")).not.toBe(resolve(themes.light, "--condition-dot"));
  });

  it("is drawn with its own token and no opacity", () => {
    const rule = /\.curve-cond-dot\s*\{([^}]*)\}/.exec(globals)?.[1] ?? "";
    expect(rule).toMatch(/fill:\s*var\(--condition-dot\)/);
    expect(rule).not.toMatch(/opacity/);
  });
});

describe("dashboard tokens", () => {
  const own = vars(blocksOf(tokens).map((b) => b.body).join("\n"));
  const sharedNames = new Set(Object.keys(vars(blocksOf(shared).map((b) => b.body).join("\n"))));

  it("tokens.css renames nothing of global.css and holds no colour of its own", () => {
    expect(Object.keys(own).length).toBeGreaterThan(0);
    expect(Object.keys(own).filter((n) => sharedNames.has(n))).toEqual([]);
    expect(tokens).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    for (const [name, value] of Object.entries(own)) {
      const ref = /^var\((--[\w-]+)\)$/.exec(value)?.[1];
      if (ref) expect(sharedNames.has(ref), `${name}: ${value}`).toBe(true);
      else expect(value, name).toMatch(/^\d+px$/);
    }
  });

  it("every chart colour resolves in light and dark", () => {
    for (const t of Object.values(themes)) {
      for (const name of Object.keys(own).filter((n) => !n.endsWith("-h"))) expect(resolve(t, name), name).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("globals.css takes every colour from a token", () => {
    expect(globals).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
  });

  it("names only tokens that exist", () => {
    const known = new Set([...sharedNames, ...Object.keys(own), "--area"]);
    const used = new Set([...globals.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]));
    expect([...used].filter((n) => !known.has(n))).toEqual([]);
  });

  it("is paper by default (no data-palette) and keeps the dark sets", () => {
    expect(resolve(themes.light, "--ground")).toBe("#f6f3ec");
    expect(resolve(themes.dark, "--ground")).toBe("#12110f");
    expect(resolve(themes.darkMedia, "--ground")).toBe("#12110f");
  });

  // The renames DESIGN.md Layout and Shapes give for the dashboard's older names.
  it("carries the dashboard's older names at the shared values", () => {
    expect(light["--gap"]).toBe("20px");
    expect(light["--panel-gap"]).toBe("12px");
    expect(light["--row"]).toBe("52px");
    expect(light["--fs-title"]).toBe("1.375rem");
    expect(light["--fs-body"]).toBe("1.0625rem");
    expect(resolve(light, "--measure")).toBe("960px");
    expect(resolve(light, "--radius-control")).toBe("999px");
    expect(light["--radius-field"]).toBe("12px");
  });
});

// A chart is drawn at a guessed width before it measures its box; an `auto` or `1fr` track would let that first
// drawing widen the column past the gutter at 360px (and ResizeObserver then keeps it). Columns are minmax(0, 1fr).
describe("panel grids", () => {
  it.each([".panels", ".curve-pair"])("%s columns never grow to fit their content", (cls) => {
    const tracks = [...globals.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter((m) => m[1].split(",").some((s) => s.trim() === cls))
      .map((m) => /grid-template-columns:\s*([^;]+);/.exec(m[2])?.[1])
      .filter((t): t is string => t !== undefined);
    expect(tracks.length).toBeGreaterThanOrEqual(2); // one column, then two from 720px
    for (const t of tracks) expect(t.trim()).toMatch(/^minmax\(0, 1fr\)( minmax\(0, 1fr\))?$/);
  });
});

// DESIGN.md Colors: the six area colours mark (dots, tag letters, chart lines), never fill a surface; the ramp
// fills ordinal steps and is never a letter colour.
describe("area colours and the ramp", () => {
  const decls = [...globals.matchAll(/([^{}]+)\{([^{}]*)\}/g)].flatMap((m) =>
    [...m[2].matchAll(/([\w-]+)\s*:\s*([^;]+);?/g)].map((d) => ({ selector: m[1].trim(), prop: d[1], value: d[2] })),
  );

  it("an area colour is a letter, a line or a dot", () => {
    const area = decls.filter((d) => /var\(--area\b|var\(--area-/.test(d.value));
    expect(area.length).toBeGreaterThan(0);
    for (const d of area) {
      const ok = d.prop === "color" || d.prop === "stroke" || (/dot/.test(d.selector) && (d.prop === "fill" || d.prop === "background")) || (/tick|label/.test(d.selector) && d.prop === "fill");
      expect(ok, `${d.selector} { ${d.prop}: ${d.value} }`).toBe(true);
    }
  });

  it("a ramp step only fills", () => {
    const ramp = decls.filter((d) => /var\(--ramp-/.test(d.value));
    expect(ramp.length).toBeGreaterThan(0);
    for (const d of ramp) expect(["fill", "background", "stroke"], `${d.selector} { ${d.prop} }`).toContain(d.prop);
    for (const d of ramp.filter((x) => x.prop === "stroke")) expect(d.selector, "a stroke ramp is a round dot").toMatch(/dot/);
  });
});

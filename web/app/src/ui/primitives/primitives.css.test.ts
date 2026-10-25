import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// SP6 Global Constraints and Review Focus 2, read from the stylesheet itself.
const css = readFileSync(join(__dirname, "primitives.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Every plain rule block (selector + body) outside @media, and each @media's own blocks. */
function rules(text: string): { selector: string; body: string }[] {
  return [...text.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector, body]) => ({ selector: selector.trim(), body }));
}
function media(query: string): string {
  const at = css.indexOf(`@media ${query}`);
  if (at < 0) return "";
  const open = css.indexOf("{", at);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i);
  }
  return "";
}

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return tsxFiles(path);
    return name.endsWith(".tsx") && !/\.test\./.test(name) ? [path] : [];
  });
}

describe("primitives.module.css", () => {
  it("has no hex colours", () => {
    expect(css.match(/#[0-9a-f]{3,8}\b/gi) ?? []).toEqual([]);
  });

  it("uses --hue only for .highlight", () => {
    const withHue = rules(css).filter((r) => r.body.includes("var(--hue)"));
    expect(withHue.length).toBeGreaterThan(0);
    for (const r of withHue) expect(r.selector.split(",").every((s) => /\.highlight\b/.test(s))).toBe(true);
  });

  it("styles <progress> without inline width", () => {
    const bar = rules(css).find((r) => r.selector === ".bar");
    expect(bar?.body).toMatch(/appearance:\s*none/);
    expect(bar?.body).toMatch(/height:\s*6px/);
    for (const pseudo of ["::-webkit-progress-bar", "::-webkit-progress-value", "::-moz-progress-bar"]) {
      expect(rules(css).some((r) => r.selector === `.bar${pseudo}`), pseudo).toBe(true);
    }
    // Track --raised, fill --primary (5.3.4); never --hue.
    expect(rules(css).find((r) => r.selector === ".bar::-webkit-progress-bar")?.body).toMatch(/background(-color)?:\s*var\(--raised\)/);
    expect(rules(css).find((r) => r.selector === ".bar::-webkit-progress-value")?.body).toMatch(/background(-color)?:\s*var\(--primary\)/);
    expect(rules(css).find((r) => r.selector === ".bar::-moz-progress-bar")?.body).toMatch(/background(-color)?:\s*var\(--primary\)/);
  });

  it("a row group is one column under 340px", () => {
    const narrow = rules(media("(max-width: 340px)"));
    const row = narrow.find((r) => r.selector === ".row");
    expect(row?.body).toMatch(/grid-template-columns:\s*1fr/);
    expect(row?.body).toMatch(/grid-auto-flow:\s*row/);
  });

  // DESIGN.md (was: square while pressable, SP5 5.5.4): every check is the 22px round one; a
  // read-only card draws it dashed, so the two states still differ by shape.
  it("the check is a 22px circle; a read-only card draws it dashed", () => {
    const circle = rules(css).find((r) => r.selector === ".circle");
    expect(circle?.body).toMatch(/width:\s*var\(--check\)/);
    expect(circle?.body).toMatch(/border-radius:\s*var\(--radius-pill\)/);
    const round = rules(css).find((r) => r.selector === "[data-read-only] .circle");
    expect(round?.body).toMatch(/border-radius:\s*var\(--radius-pill\)/);
    expect(round?.body).toMatch(/border-style:\s*dashed/);
  });

  it("has no 700 weight (screen titles only)", () => {
    expect(css).not.toMatch(/font-weight:\s*(700|bold)/);
  });

  it("noInlineStyle: no style= or dangerouslySetInnerHTML in src/ui", () => {
    const ui = join(__dirname, "..");
    const offenders = tsxFiles(ui).flatMap((file) => {
      const text = readFileSync(file, "utf8");
      return /\bstyle=\{|dangerouslySetInnerHTML/.test(text) ? [relative(ui, file)] : [];
    });
    expect(offenders).toEqual([]);
  });
});

// DESIGN.md 비서 카드: every generative card (the G-A1 parts and the G-A2 chat cards draw in Part's
// frame) is --surface with a 1px --rule, a 16px radius and 16px inside.
describe("parts.module.css card frame", () => {
  const parts = readFileSync(join(__dirname, "../components/parts.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  it("is --surface, 1px --rule, radius 16, padding 16", () => {
    const card = rules(parts).find((r) => r.selector === ".card");
    expect(card?.body).toMatch(/background:\s*var\(--surface\)/);
    expect(card?.body).toMatch(/border:\s*1px solid var\(--rule\)/);
    expect(card?.body).toMatch(/border-radius:\s*var\(--radius-container\)/);
    expect(card?.body).toMatch(/padding:\s*var\(--pad\)/);
    expect(readFileSync(join(__dirname, "../../styles/global.css"), "utf8")).toMatch(/--radius-container:\s*16px/);
  });
  it("has no hex colours", () => {
    expect(parts.match(/#[0-9a-f]{3,8}\b/gi) ?? []).toEqual([]);
  });
});

// SP6 G-A2 Step 11: the chat cards' stylesheet keeps the same rules.
describe("cards.module.css", () => {
  const cards = readFileSync(join(__dirname, "../chat/cards.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

  it("has no hex colours", () => {
    expect(cards.match(/#[0-9a-f]{3,8}\b/gi) ?? []).toEqual([]);
  });

  it("uses --hue only for ui_result's change pill", () => {
    const withHue = rules(cards).filter((r) => r.body.includes("var(--hue)"));
    expect(withHue.map((r) => r.selector)).toEqual([".changeChip"]);
  });

  it("stacks a block's parts 12px apart", () => {
    const block = rules(cards).find((r) => r.selector === ".block");
    expect(block?.body).toMatch(/flex-direction:\s*column/);
    expect(block?.body).toMatch(/gap:\s*(0\.75rem|12px)/);
  });

  it("has no 700 weight (screen titles only)", () => {
    expect(cards).not.toMatch(/font-weight:\s*(700|bold)/);
  });

  it("is imported from _app", () => {
    const app = readFileSync(join(__dirname, "../../pages/_app.tsx"), "utf8");
    expect(app).toContain('import "../ui/chat/cards.module.css";');
  });
});

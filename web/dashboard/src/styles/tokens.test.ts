// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const tokens = readFileSync(join(__dirname, "tokens.css"), "utf8");
const globals = readFileSync(join(__dirname, "globals.css"), "utf8");

/** The custom properties of each theme block: light `:root {`, the dark media query, and `[data-theme="dark"]`. */
function themes(): Record<string, Record<string, string>> {
  const blocks: Record<string, string> = {
    light: /:root \{([^}]*)\}/.exec(tokens)![1],
    darkMedia: /:root:not\(\[data-theme="light"\]\) \{([^}]*)\}/.exec(tokens)![1],
    dark: /:root\[data-theme="dark"\] \{([^}]*)\}/.exec(tokens)![1],
  };
  const out: Record<string, Record<string, string>> = {};
  for (const [name, body] of Object.entries(blocks)) {
    out[name] = Object.fromEntries([...body.matchAll(/(--[a-z-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2].toLowerCase()]));
  }
  // the dark blocks only override; what they leave out is the light value
  for (const name of ["darkMedia", "dark"]) out[name] = { ...out.light, ...out[name] };
  return out;
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
  it.each(Object.keys(themes()))("is at least 3:1 against every curve background (%s)", (name) => {
    const t = themes()[name];
    expect(t["--condition-dot"]).toMatch(/^#/);
    for (const bg of ["--surface", "--raised", "--ground"]) {
      expect(contrast(t["--condition-dot"], t[bg]), `${name} ${bg}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("the two dark blocks agree", () => {
    expect(themes().darkMedia["--condition-dot"]).toBe(themes().dark["--condition-dot"]);
  });

  it("is drawn with its own token and no opacity", () => {
    const rule = /\.curve-cond-dot\s*\{([^}]*)\}/.exec(globals)?.[1] ?? "";
    expect(rule).toMatch(/fill:\s*var\(--condition-dot\)/);
    expect(rule).not.toMatch(/opacity/);
  });
});

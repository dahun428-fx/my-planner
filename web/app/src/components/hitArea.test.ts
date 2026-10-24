import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");
const read = (name: string) => strip(readFileSync(join(__dirname, name), "utf8"));
function rule(css: string, selector: string): string {
  const m = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(([, sel]) =>
    sel.split(",").some((s) => s.trim() === selector),
  );
  if (!m) throw new Error(`no rule ${selector}`);
  return m[2];
}

describe("touch targets and focus rings", () => {
  it("segmented option keeps 32px look with a 44px hit area", () => {
    const css = read("Segmented.module.css");
    expect(rule(css, ".option")).toMatch(/min-height:\s*var\(--small-control-h\)/);
    expect(rule(css, ".option")).toMatch(/position:\s*relative/);
    const after = rule(css, ".option::after");
    expect(after).toMatch(/content:\s*""/);
    expect(after).toMatch(/position:\s*absolute/);
    // inset of (32 - 44) / 2 = -6px top and bottom grows the box to the 44px control height.
    expect(after.replace(/\s+/g, " ")).toMatch(
      /inset: calc\(\(var\(--small-control-h\) - var\(--control-h\)\) \/ 2\) 0/,
    );
  });

  it("focus rings do not use the secretary hue", () => {
    const offenders = readdirSync(__dirname)
      .filter((f) => f.endsWith(".module.css"))
      .flatMap((f) =>
        [...read(f).matchAll(/([^{}]+)\{([^{}]*)\}/g)]
          .filter(([, , decl]) => /outline[\w-]*\s*:[^;]*var\(--hue\)/.test(decl))
          .map(([, sel]) => `${f}: ${sel.trim()}`),
      );
    expect(offenders).toEqual([]);
  });
});

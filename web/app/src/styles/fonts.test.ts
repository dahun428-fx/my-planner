import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// DESIGN.md Typography: Pretendard Variable, self-hosted (public/fonts/pretendard/, dynamic-subset
// woff2 with its OFL licence), each face with its unicode-range and font-display: swap.
const css = readFileSync(join(__dirname, "global.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const faces = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1]);
const dir = join(__dirname, "../../public/fonts/pretendard");

describe("Pretendard", () => {
  it("is the first family of --font", () => {
    expect(css).toMatch(/--font:\s*"Pretendard Variable",/);
  });

  it("every subset is a swap face with a unicode-range, served from /fonts/pretendard/", () => {
    expect(faces.length).toBe(92);
    for (const f of faces) {
      expect(f).toMatch(/font-family:\s*"Pretendard Variable"/);
      expect(f).toMatch(/font-display:\s*swap/);
      expect(f).toMatch(/unicode-range:\s*U\+/);
      const url = /src:\s*url\(\/fonts\/pretendard\/([\w.]+\.woff2)\)/.exec(f)?.[1];
      expect(url, f).toBeDefined();
      expect(existsSync(join(dir, url!)), url).toBe(true);
    }
  });

  it("ships the OFL licence and no file the stylesheet does not name", () => {
    expect(readFileSync(join(dir, "LICENSE.txt"), "utf8")).toMatch(/SIL Open Font License/);
    const named = new Set(faces.map((f) => /\/fonts\/pretendard\/([\w.]+\.woff2)/.exec(f)?.[1]));
    expect(readdirSync(dir).filter((n) => n !== "LICENSE.txt" && !named.has(n))).toEqual([]);
  });

  it("the CSP lets the page load its own fonts", () => {
    const doc = readFileSync(join(__dirname, "../pages/_document.tsx"), "utf8");
    expect(doc).toMatch(/font-src 'self'/);
  });
});

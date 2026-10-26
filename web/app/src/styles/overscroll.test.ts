import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// iPhone: the page must not rubber-band, and a sheet's scrolling must not carry on to the page.
const read = (p: string) => readFileSync(join(__dirname, p), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const global = read("global.css");
const rule = (css: string, selector: string) =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, sel]) => sel.split(",").some((s) => s.trim() === selector))
    .map(([, , body]) => body)
    .join("");

describe("overscroll", () => {
  it("the page does not bounce and holds still under an open sheet", () => {
    expect(rule(global, "html")).toMatch(/overscroll-behavior:\s*none/);
    expect(rule(global, "body")).toMatch(/overscroll-behavior:\s*none/);
    expect(rule(global, "html[data-sheet-open]")).toMatch(/overflow:\s*hidden/);
  });

  it("every scrolling box keeps its scroll to itself", () => {
    for (const p of ["../components/Sheet.module.css", "../chat/ChatSheet.module.css", "../chat/ConversationList.module.css"]) {
      const css = read(p);
      for (const [, body] of css.matchAll(/\{([^{}]*overflow-y:\s*auto[^{}]*)\}/g)) {
        expect(body, p).toMatch(/overscroll-behavior:\s*contain/);
      }
    }
  });
});

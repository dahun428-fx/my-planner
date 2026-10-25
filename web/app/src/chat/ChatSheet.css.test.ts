import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// DESIGN.md 채팅 and 입력창, read from the stylesheet.
const css = readFileSync(join(__dirname, "ChatSheet.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const rule = (selector: string) =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, sel]) => sel.split(",").some((s) => s.trim().replace(/\s+/g, " ") === selector))
    .map(([, , body]) => body)
    .join("");

describe("chat styles", () => {
  it("the secretary's text is open body text, no bubble", () => {
    expect(rule(".text")).toMatch(/font-size:\s*var\(--fs-body\)/);
    expect(rule(".text")).toMatch(/line-height:\s*var\(--lh-body\)/);
    expect(rule(".theirs")).not.toMatch(/background|border-radius|max-width/);
  });

  it("my message is a --raised bubble at the right: 18/18/4/18, 12×18, at most 80%", () => {
    const b = rule(".bubble");
    expect(b).toMatch(/background:\s*var\(--raised\)/);
    expect(b).toMatch(/color:\s*var\(--text\)/);
    expect(b).toMatch(/border-radius:\s*var\(--radius-bubble\) var\(--radius-bubble\) 4px var\(--radius-bubble\)/);
    expect(b).toMatch(/padding:\s*0\.75rem 1\.125rem/);
    expect(b).toMatch(/max-width:\s*80%/);
    expect(rule(".mine")).toMatch(/justify-content:\s*flex-end/);
  });

  it("messages are 12px apart, 20px when the speaker changes", () => {
    expect(rule(".list > * + *")).toMatch(/margin-top:\s*var\(--panel-gap\)/);
    expect(rule(".list > .mine + .theirs")).toMatch(/margin-top:\s*var\(--speaker-gap\)/);
    expect(rule(".list > .theirs + .mine")).toMatch(/margin-top:\s*var\(--speaker-gap\)/);
  });

  it("the field is 12px round with a --border outline, 1.5px --primary only when ready", () => {
    const input = rule(".input");
    expect(input).toMatch(/border-radius:\s*var\(--radius-field\)/);
    expect(input).toMatch(/border:\s*1px solid var\(--border\)/);
    expect(input).toMatch(/resize:\s*none/);
    const ready = rule(".input[data-ready]");
    expect(ready).toMatch(/border-color:\s*var\(--primary\)/);
    expect(ready).toMatch(/box-shadow:\s*0 0 0 0\.5px var\(--primary\)/);
  });

  it("the send button is a 44px hit area around a 36px circle", () => {
    expect(rule(".send")).toMatch(/width:\s*var\(--control-h\)/);
    expect(rule(".send")).toMatch(/height:\s*var\(--control-h\)/);
    expect(rule(".sendMark")).toMatch(/width:\s*2\.25rem/);
    expect(rule(".sendMark")).toMatch(/background:\s*var\(--primary\)/);
  });

  it("the ready field still shows focus: a 2px --text outline off the field", () => {
    expect(rule(".input[data-ready]:focus-visible")).toMatch(/outline:\s*2px solid var\(--text\)/);
    expect(rule(".input[data-ready]:focus-visible")).toMatch(/outline-offset:\s*2px/);
  });
});

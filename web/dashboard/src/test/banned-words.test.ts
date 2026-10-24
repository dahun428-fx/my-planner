// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// SP1 banned words plus the streak word of ADR 0006 (spec 13.1, 13.5). Written as escapes so this
// file itself stays clean.
const BANNED = ["\ub193\ucce4\uc5b4\uc694", "\ubc00\ub838\uc5b4\uc694", "\ub2a6\uc5c8\uc9c0\ub9cc", "\uc2e4\ud328", "\uc5f0\uc18d"];

const src = join(__dirname, "..");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("banned words", () => {
  it("are nowhere in src/", () => {
    const all = files(src);
    expect(all.length).toBeGreaterThan(10);
    const hits = all.flatMap((f) => {
      const text = readFileSync(f, "utf8");
      return BANNED.filter((w) => text.includes(w)).map((w) => `${relative(src, f)}: ${w}`);
    });
    expect(hits).toEqual([]);
  });
});

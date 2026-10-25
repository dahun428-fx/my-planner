// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// The banned words of SP5 10 (SP1 5.4's canonical six, plus the three app-screen words of ADR 0006) and the
// three SP7 7 adds. Written as escapes so this file itself stays clean.
const BANNED = [
  // SP1 5.4 (`harness/prompts/system.md` `banned-words` block)
  "\ubc00\ub838\ub2e4",
  "\ub193\ucce4\ub2e4",
  "\uc2e4\ud328",
  "\ub193\ucce4\uc5b4\uc694",
  "\ubc00\ub838\uc5b4\uc694",
  "\ub2a6\uc5c8\uc9c0\ub9cc",
  // SP5 10 (app screens, ADR 0006)
  "\uc5f0\uc18d",
  "\uc2a4\ud2b8\ub9ad",
  "\ub2ec\uc131\ub960",
  // SP7 7
  "\ub04a\uacbc",
  "\uba70\uce60\uc9f8",
  "\ub0a8\uc74c",
  // SP8 appendix A (static copy checks only; the brain's banned-words block does not get these)
  "\ubcf4\ub108\uc2a4\uac00 \uc904",
  "\uc2a4\ud0ef\uc774 \ub5a8\uc5b4",
];

const src = join(__dirname, "..");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const hitsIn = (text: string) => BANNED.filter((w) => text.includes(w));

describe("banned words", () => {
  it("are the fourteen of SP5 10, SP7 7 and SP8", () => {
    expect(BANNED).toHaveLength(14);
    expect(new Set(BANNED).size).toBe(14);
  });

  it("are caught in a planted line", () => {
    // each word inside an ordinary sentence is found
    for (const w of BANNED) expect(hitsIn(`이번 주 ${w} 2번`)).toContain(w);
  });

  it("are nowhere in src/", () => {
    const all = files(src);
    expect(all.length).toBeGreaterThan(10);
    const hits = all.flatMap((f) => {
      const text = readFileSync(f, "utf8");
      return hitsIn(text).map((w) => `${relative(src, f)}: ${w}`);
    });
    expect(hits).toEqual([]);
  });
});

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { copy } from "./copy";

const repoRoot = join(__dirname, "../../../..");
const srcRoot = join(__dirname, "..");
const APP_BANNED = ["연속", "스트릭", "달성률"];

function readBannedList(): string[] {
  const md = readFileSync(join(repoRoot, "src/my_planner/harness/prompts/system.md"), "utf8");
  const block = md.match(/<!-- banned-words:start -->([\s\S]*?)<!-- banned-words:end -->/);
  if (!block) return [];
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}
const banned = [...readBannedList(), ...APP_BANNED];

// Every copy value as text; template functions are called with sample arguments.
function texts(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value === "function") {
    const fn = value as (...args: unknown[]) => unknown;
    const args = (sample: unknown) => Array.from({ length: Math.max(fn.length, 1) }, () => sample);
    return [...texts(fn(...args("00:00"))), ...texts(fn(...args(3)))];
  }
  if (value && typeof value === "object") return Object.values(value).flatMap(texts);
  return [];
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "test" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

describe("copy", () => {
  it("banned list is read", () => {
    expect(readBannedList()).toContain("놓쳤어요");
  });

  it("no banned words", () => {
    const values = texts(copy);
    expect(values.length).toBeGreaterThan(20);
    const inCopy = values.filter((t) => banned.some((w) => t.includes(w)));
    expect(inCopy).toEqual([]);
    const inSource = sourceFiles(srcRoot).flatMap((file) => {
      const body = readFileSync(file, "utf8");
      return banned.filter((w) => body.includes(w)).map((w) => `${relative(srcRoot, file)}: ${w}`);
    });
    expect(inSource).toEqual([]);
  });

  it("areas are glossary names", () => {
    expect(Object.values(copy.areas)).toEqual(["커리어", "경제", "건강", "관계", "배움", "삶의 질"]);
  });

  it("loops use appendix A names", () => {
    expect(copy.loops).toEqual({
      morning_brief: "아침 브리핑",
      evening_checkin: "저녁 체크인",
      review: "주간 회고",
      return: "다시 이어서",
    });
  });

  it("templates fill values", () => {
    expect(copy.errors.block("shape")).toBe("이 부분을 불러오지 못했어요 (shape)");
    expect(copy.status.limitedUntil("21:30")).toBe("비서가 21:30까지 답을 쉬어요");
  });
});

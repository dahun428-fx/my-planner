import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { copy, habitMeta } from "./copy";

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

  it("banned list has the SP7 words", () => {
    // SP7 7장: SP7-05 added these to the system.md block the app reads.
    const list = readBannedList();
    for (const w of ["끊겼", "며칠째", "남음"]) expect(list).toContain(w);
    for (const w of ["밀렸다", "놓쳤다", "실패"]) expect(list).toContain(w);
  });

  it("habit copy is appendix A verbatim", () => {
    expect(copy.habits.heading).toBe("습관");
    expect(copy.habits.manage).toBe("관리");
    expect(copy.habits.todayLine).toBe("오늘 습관");
    expect(copy.habits.addRow).toBe("습관 추가하기");
    expect(copy.habits.empty).toBe("챙기고 싶은 습관을 더해 보세요. 매일 하는 것도, 주 몇 번 하는 것도 돼요.");
    expect(copy.habits.weekOfTarget(2, 3)).toBe("이번 주 2번 · 목표 3번");
    expect(copy.habits.weekMet).toBe("이번 주 목표만큼 했어요");
    expect(copy.habits.week(4)).toBe("이번 주 4번");
    expect(copy.habits.lastWeek(3)).toBe("지난주 3번");
    expect(copy.habits.weekOf(10, 5, 1)).toBe("10월 5일 주 1번");
  });

  it("habit copy has no banned word, ratio or what is left", () => {
    const values = texts(copy.habits);
    expect(values.length).toBeGreaterThan(5);
    for (const t of values) {
      expect(banned.filter((w) => t.includes(w))).toEqual([]);
      expect(t).not.toMatch(/%|남음|남은|\d+\s*\/\s*\d+/);
    }
  });

  it("habitMeta picks the line by kind and count", () => {
    expect(habitMeta({ kind: "daily", target_per_week: null, week_count: 4 })).toBe("이번 주 4번");
    expect(habitMeta({ kind: "daily", target_per_week: null, week_count: 0 })).toBe("이번 주 0번");
    expect(habitMeta({ kind: "weekly", target_per_week: 3, week_count: 2 })).toBe("이번 주 2번 · 목표 3번");
    expect(habitMeta({ kind: "weekly", target_per_week: 3, week_count: 3 })).toBe("이번 주 목표만큼 했어요");
    // Over the target is still "met", never a count above it.
    expect(habitMeta({ kind: "weekly", target_per_week: 2, week_count: 5 })).toBe("이번 주 목표만큼 했어요");
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
    expect(copy.status.limited("21:30")).toBe("비서가 21:30까지 답을 쉬어요");
  });
});

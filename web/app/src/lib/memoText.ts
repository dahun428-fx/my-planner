import { copy } from "./copy";
import { formatKst } from "./time";

// SP9 6.2: a checklist line is a list marker (`-`, `*`, `+` or `1.`), maybe under `>` quotes and
// indents, then `[ ]` or `[x]`. These are the lines markdown-to-jsx draws as task checkboxes.
const CHECK_LINE = /^(\s*(?:>\s*)*\s*(?:[-*+]|\d+[.)])\s+\[)([ xX])(\])/;
const FENCE = /^\s{0,3}(`{3,}|~{3,})/;

/**
 * The 0-based line numbers of the body's checklist lines, in order (the order the renderer draws
 * their boxes). Lines inside a fenced code block are not checklists: the renderer shows them as code.
 */
export function checklistLines(body: string): number[] {
  const out: number[] = [];
  let fence: string | null = null;
  body.split("\n").forEach((line, i) => {
    const f = line.match(FENCE);
    if (f) {
      const mark = f[1][0];
      if (fence === null) fence = mark;
      else if (fence === mark) fence = null;
      return;
    }
    if (fence === null && CHECK_LINE.test(line)) out.push(i);
  });
  return out;
}

/** Flips `[ ]`↔`[x]` on line `lineIndex` (0-based) only; any other line, or a line that is not a checklist, stays as it is. */
export function toggleChecklistLine(body: string, lineIndex: number): string {
  const lines = body.split("\n");
  const line = lines[lineIndex];
  if (line === undefined) return body;
  const m = line.match(CHECK_LINE);
  if (!m) return body;
  lines[lineIndex] = line.replace(CHECK_LINE, (_all, head: string, mark: string, tail: string) => `${head}${mark === " " ? "x" : " "}${tail}`);
  return lines.join("\n");
}

/** SP9 9.4 row date: "오늘 14:02", "어제", "10월 21일" (Seoul calendar days). */
export function memoDay(iso: string, now: number = Date.now()): string {
  const day = formatKst(iso, "date");
  const today = formatKst(new Date(now).toISOString(), "date");
  const yesterday = formatKst(new Date(now - 86_400_000).toISOString(), "date");
  if (day === today) return copy.memos.today(formatKst(iso, "HH:mm"));
  if (day === yesterday) return copy.memos.yesterday;
  return copy.dateParts.monthDay(Number(day.slice(5, 7)), Number(day.slice(8, 10)));
}

/** The words of each checklist line after its box (bold marks dropped): the box's accessible name. */
export function checklistLabels(body: string, lines: number[]): string[] {
  const all = body.split("\n");
  return lines.map((i) => (all[i] ?? "").replace(CHECK_LINE, "").replace(/\*\*/g, "").trim());
}

import { copy } from "./copy";
import { formatKst } from "./time";

// SP9 6.2: the memo format is a title line, lists `- `, numbered lists `1. `, checkboxes `- [ ]` /
// `- [x]` and bold `**`. A checklist line is `-` or `1.` (maybe indented), a space, then the box.
const CHECK_LINE = /^(\s*(?:-|\d+\.)\s+\[)([ xX])(\])/;

/** The 0-based line numbers of the body's checklist lines, in order (the order the renderer draws their boxes). */
export function checklistLines(body: string): number[] {
  const out: number[] = [];
  body.split("\n").forEach((line, i) => {
    if (CHECK_LINE.test(line)) out.push(i);
  });
  return out;
}

/**
 * Flips `[ ]`↔`[x]` on line `lineIndex` (0-based) only. A line that is not one of checklistLines(body)
 * (or not there at all) leaves the body as it is.
 */
export function toggleChecklistLine(body: string, lineIndex: number): string {
  if (!checklistLines(body).includes(lineIndex)) return body;
  const lines = body.split("\n");
  lines[lineIndex] = lines[lineIndex].replace(CHECK_LINE, (_all, head: string, mark: string, tail: string) => `${head}${mark === " " ? "x" : " "}${tail}`);
  return lines.join("\n");
}

// A supported list start: indent, `-` or `1.`, the spaces after it, and a box right after when there is one.
const LIST_HEAD = /^(\s*)(-|\d+\.)(\s+)(\[[ xX]\](?=\s|$))?/;
// Markdown punctuation the memo format does not use (and `:` `.` `@`, which start bare autolinks); each is
// escaped so it shows as typed.
const PUNCT = /[\\#>|`~_[\]<!()=+&:.@]/g;

function escapeRest(rest: string): string {
  return rest.replace(PUNCT, (c) => `\\${c}`).replace(/\*\*|\*/g, (m) => (m === "**" ? m : "\\*"));
}

/**
 * SP9 6.2: everything but the memo format shows as typed. Before the SP6 renderer compiles a memo,
 * each line keeps its list head (`- `, `1. `, a box) and the rest has headings, quotes, tables,
 * code, strikes, links, emphasis, rules and other list marks escaped. `**` stays bold. Lines are
 * neither added nor removed, so checklistLines still names the renderer's boxes.
 */
export function escapeMemoMarkdown(body: string): string {
  return body
    .split("\n")
    .map((line) => {
      const m = line.match(LIST_HEAD);
      if (m) return m[0] + escapeRest(line.slice(m[0].length));
      const indent = line.match(/^\s*/)?.[0] ?? "";
      // A line that only looks like a list (`-x`, `---`, `1)`) keeps its first character as typed.
      let rest = line.slice(indent.length);
      let lead = "";
      if (/^-/.test(rest) || /^\d+\./.test(rest)) {
        const n = rest.match(/^\d+/)?.[0] ?? "";
        lead = n ? `${n}\\.` : "\\-";
        rest = rest.slice(n ? n.length + 1 : 1);
      }
      return indent + lead + escapeRest(rest);
    })
    .join("\n");
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

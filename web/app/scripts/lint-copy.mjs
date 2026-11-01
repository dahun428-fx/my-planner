#!/usr/bin/env node
// Spec 10장: screen code does not hold Korean sentences; they live in src/lib/copy.ts.
// Reports Hangul in string/template literals and JSX text outside lib/copy.ts (and SP13's
// lib/copyStanding.ts, kept off the first screen), api/types.gen.ts,
// *.test.* files and test/. Comments are not checked.
// SP13 10.1 (and SP5 10장): the banned words are reported in any string or JSX text, copy.ts included.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";

const HANGUL = /[가-힣]/;
const COPY_FILES = new Set(["lib/copy.ts", "lib/copyStanding.ts"]);
// The app's banned words (the system.md `banned-words` block is the canonical list; copy.test.ts reads both).
const BANNED = ["연속", "스트릭", "달성률", "등수", "패배", "뒤처짐", "실패"];
const root = resolve(process.argv[2] ?? "src");

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    const rel = relative(root, path).split("\\").join("/");
    if (statSync(path).isDirectory()) return rel === "test" ? [] : files(path);
    if (!/\.(ts|tsx)$/.test(name) || /\.test\./.test(name)) return [];
    if (rel === "api/types.gen.ts") return [];
    return [path];
  });
}

const TEXT_KINDS = new Set([
  ts.SyntaxKind.StringLiteral,
  ts.SyntaxKind.NoSubstitutionTemplateLiteral,
  ts.SyntaxKind.TemplateHead,
  ts.SyntaxKind.TemplateMiddle,
  ts.SyntaxKind.TemplateTail,
  ts.SyntaxKind.JsxText,
]);

const problems = [];
for (const file of files(root)) {
  const text = readFileSync(file, "utf8");
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const rel = relative(root, file).split("\\").join("/");
  const visit = (node) => {
    if (TEXT_KINDS.has(node.kind)) {
      const t = node.getText(sf);
      for (const w of BANNED) {
        const at = t.indexOf(w);
        if (at < 0) continue;
        const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf) + at);
        problems.push(`${rel}:${line + 1}: banned word "${w}"`);
      }
    }
    if (!COPY_FILES.has(rel) && TEXT_KINDS.has(node.kind) && HANGUL.test(node.getText(sf))) {
      const start = node.getStart(sf);
      const offset = node.getText(sf).search(HANGUL);
      const { line } = sf.getLineAndCharacterOfPosition(start + offset);
      problems.push(`${relative(root, file).split("\\").join("/")}:${line + 1}: Korean text outside lib/copy.ts`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

if (problems.length > 0) {
  for (const p of problems) console.error(p);
  process.exitCode = 1;
}

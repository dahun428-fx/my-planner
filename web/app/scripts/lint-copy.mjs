#!/usr/bin/env node
// Spec 10장: screen code does not hold Korean sentences; they live in src/lib/copy.ts.
// Reports Hangul in string/template literals and JSX text outside lib/copy.ts, api/types.gen.ts,
// *.test.* files and test/. Comments are not checked.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";

const HANGUL = /[가-힣]/;
const root = resolve(process.argv[2] ?? "src");

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    const rel = relative(root, path).split("\\").join("/");
    if (statSync(path).isDirectory()) return rel === "test" ? [] : files(path);
    if (!/\.(ts|tsx)$/.test(name) || /\.test\./.test(name)) return [];
    if (rel === "lib/copy.ts" || rel === "api/types.gen.ts") return [];
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
  const visit = (node) => {
    if (TEXT_KINDS.has(node.kind) && HANGUL.test(node.getText(sf))) {
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

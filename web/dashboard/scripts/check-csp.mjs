#!/usr/bin/env node
// Static-export CSP check (SP3-4 spec 14, 16; plan ticket 16).
// For every out/**/*.html: (1) no <script> without src (except type="application/json"),
// no <style>, no style= attribute; (2) the CSP <meta> comes before the first <script>; (3) no
// page-level stylesheet (data-n-p): on a move between tabs Next's pages router re-adds a page's CSS
// as an inline <style>, which style-src 'self' blocks, so every style must come with _app.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function htmlFiles(dir) {
  const found = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) found.push(...htmlFiles(path));
    else if (name.endsWith(".html")) found.push(path);
  }
  return found.sort();
}

const lineOf = (html, index) => html.slice(0, index).split("\n").length;
const attr = (tag, name) => {
  const m = tag.match(new RegExp(`\\s${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, "i"));
  return m ? (m[2] ?? m[3] ?? m[4] ?? "") : null;
};

export function checkHtml(html) {
  const problems = [];
  let inlineScripts = 0;
  let inlineStyles = 0;
  let firstScript = -1;

  for (const m of html.matchAll(/<script\b[^>]*>/gi)) {
    if (firstScript < 0) firstScript = m.index;
    const tag = m[0];
    const type = (attr(tag, "type") ?? "").toLowerCase();
    if (attr(tag, "src") === null && type !== "application/json") {
      inlineScripts++;
      problems.push({ line: lineOf(html, m.index), what: "inline script" });
    }
  }
  for (const m of html.matchAll(/<style\b[^>]*>/gi)) {
    inlineStyles++;
    problems.push({ line: lineOf(html, m.index), what: "inline style element" });
  }
  for (const m of html.matchAll(/<[a-z][^>]*?\sstyle\s*=/gi)) {
    inlineStyles++;
    problems.push({ line: lineOf(html, m.index), what: "style attribute" });
  }

  for (const m of html.matchAll(/<link\b[^>]*\sdata-n-p\b[^>]*>/gi)) {
    inlineStyles++;
    problems.push({ line: lineOf(html, m.index), what: "page-level stylesheet" });
  }

  const metaMatch = html.match(/<meta\b[^>]*http-equiv\s*=\s*["']?Content-Security-Policy[^>]*>/i);
  const meta = metaMatch ? metaMatch.index : -1;
  const firstSheet = html.search(/<link\b[^>]*rel\s*=\s*["']?stylesheet/i);
  if (meta < 0) problems.push({ line: 1, what: "CSP meta missing" });
  else {
    if (firstScript >= 0 && meta > firstScript) {
      problems.push({ line: lineOf(html, meta), what: "CSP meta after first <script>" });
    }
    if (firstSheet >= 0 && meta > firstSheet) {
      problems.push({ line: lineOf(html, meta), what: "CSP meta after first stylesheet" });
    }
    const policy = (attr(metaMatch[0], "content") ?? "").replace(/&#x27;|&#39;/g, "'");
    for (const need of ["script-src 'self'", "style-src 'self'"]) {
      if (!policy.includes(need)) problems.push({ line: lineOf(html, meta), what: `CSP lacks ${need}` });
    }
    if (/connect-src 'self'\s*(;|$)/.test(policy)) {
      problems.push({ line: lineOf(html, meta), what: "CSP connect-src has no BE source" });
    }
  }
  return { problems, inlineScripts, inlineStyles };
}

/** The pictogram sprite (pages/_document) is drawn once, as the first element of <body>; null when it is. */
export function checkSprite(html) {
  const sprites = [...html.matchAll(/class\s*=\s*["']?pictogram-sprite(?![\w-])/gi)].length;
  if (sprites !== 1) return `has ${sprites} sprites`;
  const body = html.match(/<body\b[^>]*>\s*/i);
  const rest = body ? html.slice(body.index + body[0].length) : "";
  return /^<svg\b[^>]*class\s*=\s*["']?pictogram-sprite(?![\w-])/i.test(rest) ? null : "is not the first child of <body>";
}

export function checkDir(dir) {
  const files = htmlFiles(dir);
  const problems = [];
  for (const file of files) {
    const rel = relative(dir, file).split("\\").join("/");
    const html = readFileSync(file, "utf8");
    for (const p of checkHtml(html).problems) {
      problems.push(`${rel}:${p.line}: ${p.what}`);
    }
    const sprite = checkSprite(html);
    if (sprite) problems.push(`pictogram sprite: ${rel} ${sprite}`);
  }
  return { files: files.length, problems };
}

function main() {
  const dir = resolve(process.argv[2] ?? "out");
  let result;
  try {
    result = checkDir(dir);
  } catch (err) {
    console.error(`CSP check could not read ${dir}: ${err.message}`);
    return 1;
  }
  if (result.files === 0) {
    console.error(`CSP check found no HTML in ${dir}`);
    return 1;
  }
  if (result.problems.length > 0) {
    for (const p of result.problems) console.error(p);
    return 1;
  }
  console.log("CSP OK: 0 inline scripts, 0 inline styles, meta first");
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}

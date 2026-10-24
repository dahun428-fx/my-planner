// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const script = fileURLToPath(new URL("./check-csp.mjs", import.meta.url));
const META = `<meta http-equiv="Content-Security-Policy" content="default-src 'self'"/>`;
const DATA = `<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>`;
const page = (head, body = "") =>
  `<!DOCTYPE html><html lang="ko"><head><meta charSet="utf-8"/>${head}</head><body><div id="__next">${body}</div>${DATA}</body></html>`;

let dirs = [];
function exportDir(files) {
  const dir = mkdtempSync(join(tmpdir(), "csp-"));
  dirs.push(dir);
  for (const [name, html] of Object.entries(files)) {
    const path = join(dir, name);
    mkdirSync(join(path, ".."), { recursive: true });
    writeFileSync(path, html);
  }
  return dir;
}
function run(dir) {
  const r = spawnSync(process.execPath, [script, dir], { encoding: "utf8" });
  return { code: r.status, out: r.stdout + r.stderr };
}
afterEach(() => {
  for (const d of dirs) rmSync(d, { recursive: true, force: true });
  dirs = [];
});

const clean = page(`${META}<script src="/_next/a.js" defer=""></script>`, "<main></main>");

describe("check-csp", () => {
  it("passes clean export", () => {
    const r = run(exportDir({ "index.html": clean, "todos/index.html": clean }));
    expect(r.code).toBe(0);
    expect(r.out).toContain("CSP OK: 0 inline scripts, 0 inline styles, meta first");
  });

  it("fails on inline script", () => {
    const bad = page(`${META}<script src="/a.js"></script>`, "<script>alert(1)</script>");
    const r = run(exportDir({ "index.html": clean, "todos/index.html": bad }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/todos\/index\.html:1: inline script/);
  });

  it("fails on a page-level stylesheet (Next inlines it as <style> on a client move)", () => {
    const bad = page(`${META}<link rel="stylesheet" href="/_next/static/css/p.css" data-n-p=""/><script src="/a.js"></script>`);
    const r = run(exportDir({ "index.html": clean, "todos/index.html": bad }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/todos\/index\.html:1: page-level stylesheet/);
  });

  it("fails on inline style element", () => {
    const bad = page(`${META}<style>body{}</style><script src="/a.js"></script>`);
    const r = run(exportDir({ "index.html": bad }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/index\.html:1: inline style/);
  });

  it("fails on style attribute", () => {
    const bad = page(`${META}<script src="/a.js"></script>`, `\n<div style="color:red"></div>`);
    const r = run(exportDir({ "index.html": bad }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/index\.html:2: style attribute/);
  });

  it("fails when meta after script", () => {
    const bad = page(`<script src="/a.js"></script>${META}`);
    const r = run(exportDir({ "index.html": bad }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/index\.html:1: CSP meta/);
  });

  it("fails when meta missing", () => {
    const bad = page(`<script src="/a.js"></script>`);
    const r = run(exportDir({ "index.html": bad }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/CSP meta missing/);
  });
});

// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";
import { firstScreenChunks } from "./size.mjs";

const script = fileURLToPath(new URL("./size.mjs", import.meta.url));
let dirs = [];
afterEach(() => {
  dirs.forEach((d) => rmSync(d, { recursive: true, force: true }));
  dirs = [];
});

function outWith(chunks) {
  const dir = mkdtempSync(join(tmpdir(), "size-"));
  dirs.push(dir);
  mkdirSync(join(dir, "_next/static/chunks"), { recursive: true });
  const tags = Object.entries(chunks).map(([name, bytes]) => {
    writeFileSync(join(dir, "_next/static/chunks", name), bytes);
    return `<script src="/_next/static/chunks/${name}" defer=""></script>`;
  });
  writeFileSync(join(dir, "index.html"), `<html><head>${tags.join("")}</head></html>`);
  return dir;
}
const run = (dir) => spawnSync(process.execPath, [script, dir], { encoding: "utf8" });

describe("size", () => {
  it("counts the chunks the first screen loads, not nomodule polyfills or other assets", () => {
    const html =
      '<script defer="" noModule="" src="/_next/static/chunks/polyfills-1.js"></script>' +
      '<script src="/_next/static/chunks/main-1.js" defer=""></script>' +
      '<script src="/_next/static/chunks/pages/index-1.js" defer=""></script>' +
      '<script src="/_next/static/abc/_buildManifest.js" defer=""></script>';
    expect(firstScreenChunks(html)).toEqual(["/_next/static/chunks/main-1.js", "/_next/static/chunks/pages/index-1.js"]);
  });

  it("passes under 180KB gzip and fails over it", () => {
    const small = run(outWith({ "a.js": "x".repeat(400_000) })); // compresses to almost nothing
    expect(small.status).toBe(0);
    expect(small.stdout).toMatch(/^OK [\d.]+KB ≤ 180KB/m);
    const big = run(outWith({ "a.js": randomBytes(120 * 1024), "b.js": randomBytes(70 * 1024) }));
    expect(big.status).toBe(1);
    expect(big.stderr).toMatch(/^OVER [\d.]+KB > 180KB/m);
  });
});

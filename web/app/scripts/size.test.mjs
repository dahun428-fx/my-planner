// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { gzipSync } from "node:zlib";
import { afterEach, describe, expect, it } from "vitest";
import { CHAT_PARTS_MARKER, firstScreenChunks } from "./size.mjs";

const script = fileURLToPath(new URL("./size.mjs", import.meta.url));
let dirs = [];
afterEach(() => {
  dirs.forEach((d) => rmSync(d, { recursive: true, force: true }));
  dirs = [];
});

function outWith(chunks, later = {}) {
  const dir = mkdtempSync(join(tmpdir(), "size-"));
  dirs.push(dir);
  mkdirSync(join(dir, "_next/static/chunks"), { recursive: true });
  const tags = Object.entries(chunks).map(([name, bytes]) => {
    writeFileSync(join(dir, "_next/static/chunks", name), bytes);
    return `<script src="/_next/static/chunks/${name}" defer=""></script>`;
  });
  // Chunks the first screen does not load (the chat sheet's, read with import() later).
  for (const [name, bytes] of Object.entries(later)) {
    mkdirSync(join(dir, "_next/static/chunks", name, ".."), { recursive: true });
    writeFileSync(join(dir, "_next/static/chunks", name), bytes);
  }
  writeFileSync(join(dir, "index.html"), `<html><head>${tags.join("")}</head></html>`);
  return dir;
}
const run = (dir) => spawnSync(process.execPath, [script, dir], { encoding: "utf8" });

describe("size", () => {
  it("counts every /_next/static script the first screen loads, not nomodule polyfills or other assets", () => {
    const html =
      '<script defer="" noModule="" src="/_next/static/chunks/polyfills-1.js"></script>' +
      '<script src="/_next/static/chunks/main-1.js" defer=""></script>' +
      '<script src="/_next/static/chunks/pages/index-1.js" defer=""></script>' +
      '<script src="/_next/static/abc/_buildManifest.js" defer=""></script>' +
      '<script src="/_next/static/abc/_ssgManifest.js" defer=""></script>' +
      '<script src="/sw-register.js" defer=""></script>' +
      '<link rel="stylesheet" href="/_next/static/css/a.css"/>';
    expect(firstScreenChunks(html)).toEqual([
      "/_next/static/chunks/main-1.js",
      "/_next/static/chunks/pages/index-1.js",
      "/_next/static/abc/_buildManifest.js",
      "/_next/static/abc/_ssgManifest.js",
    ]);
  });

  it("passes under 180KB gzip and fails over it", () => {
    const small = run(outWith({ "a.js": "x".repeat(400_000) })); // compresses to almost nothing
    expect(small.status).toBe(0);
    expect(small.stdout).toMatch(/^OK [\d.]+KB ≤ 180KB/m);
    const big = run(outWith({ "a.js": randomBytes(120 * 1024), "b.js": randomBytes(70 * 1024) }));
    expect(big.status).toBe(1);
    expect(big.stderr).toMatch(/^OVER [\d.]+KB > 180KB/m);
  });

  it("prints chat chunk line", () => {
    const chat = `self.x=1;registerParts({},"sp6-chat-parts");${"y".repeat(5000)}`;
    const r = run(outWith({ "a.js": "self.a=1" }, { "b.js": chat, "c.js": "self.c=1" }));
    expect(r.status).toBe(0);
    const kb = (gzipSync(Buffer.from(chat), { level: 9 }).length / 1024).toFixed(1);
    const line = r.stdout.split("\n").find((l) => l.startsWith("chat sheet chunk:"));
    expect(line).toBe(`chat sheet chunk: ${kb} KB (chunks/b.js)`);
    // It comes right after the first-screen total.
    const lines = r.stdout.trim().split("\n");
    expect(lines[lines.length - 2]).toMatch(/^OK /);
    expect(lines[lines.length - 1]).toBe(line);
  });

  it("unknown when no chunk has the marker", () => {
    const r = run(outWith({ "a.js": "self.a=1" }, { "b.js": "self.b=1" }));
    expect(r.status).toBe(0);
    expect(r.stdout).toMatch(/^chat sheet chunk: unknown$/m);
  });

  it("first-screen chunk with marker is not counted", () => {
    const r = run(outWith({ "a.js": 'x("sp6-chat-parts")' }, { "nested/b.js": 'y("sp6-chat-parts")' }));
    expect(r.status).toBe(0);
    expect(r.stdout).toMatch(/^chat sheet chunk: [\d.]+ KB \(chunks\/nested\/b\.js\)$/m);
    const only = run(outWith({ "a.js": 'x("sp6-chat-parts")' }));
    expect(only.stdout).toMatch(/^chat sheet chunk: unknown$/m);
  });

  it("the chat line never changes the exit code", () => {
    const big = run(outWith({ "a.js": randomBytes(190 * 1024) }, { "b.js": '"sp6-chat-parts"' }));
    expect(big.status).toBe(1);
    expect(big.stdout).toMatch(/^chat sheet chunk: /m);
  });

  it("looks for the marker registerChatParts writes", () => {
    // Two copies of one string (a .mjs script cannot import the app's TypeScript): they must agree.
    const src = readFileSync(fileURLToPath(new URL("../src/ui/chat/registerChatParts.ts", import.meta.url)), "utf8");
    expect(src.match(/export const CHAT_PARTS_MARKER = "([^"]+)";/)?.[1]).toBe(CHAT_PARTS_MARKER);
  });
});

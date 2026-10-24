#!/usr/bin/env node
// Spec 9장: the JavaScript the first screen (`/`) loads is at most 180KB gzip. Reads every script
// out/index.html asks for under /_next/static/ (chunks, _buildManifest, _ssgManifest) and sums
// their gzip sizes.
// Chunks loaded later (the chat sheet) and `nomodule` polyfills are not counted. Exit 1 when over.
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

export const LIMIT = 180 * 1024;

// `nomodule` scripts (Next's polyfills) are skipped by every browser that runs modules, iOS Safari included.
export function firstScreenChunks(html) {
  return [...html.matchAll(/<script\b[^>]*>/gi)]
    .map((m) => m[0])
    .filter((tag) => !/\snomodule\b/i.test(tag))
    .map((tag) => tag.match(/\ssrc="([^"]+)"/i)?.[1] ?? "")
    .filter((src) => src.startsWith("/_next/static/") && src.endsWith(".js"));
}

function main() {
  const out = resolve(process.argv[2] ?? "out");
  const index = join(out, "index.html");
  if (!existsSync(index)) {
    console.error(`size: ${index} not found. Run npm run build first.`);
    return 1;
  }
  const chunks = firstScreenChunks(readFileSync(index, "utf8"));
  if (chunks.length === 0) {
    console.error("size: out/index.html loads no chunks");
    return 1;
  }
  let total = 0;
  for (const src of chunks) {
    const bytes = gzipSync(readFileSync(join(out, src)), { level: 9 }).length;
    total += bytes;
    console.log(`${(bytes / 1024).toFixed(1).padStart(7)} KB  ${src.replace("/_next/static/", "")}`);
  }
  const kb = (total / 1024).toFixed(1);
  if (total > LIMIT) {
    console.error(`OVER ${kb}KB > 180KB (gzip, / first load)`);
    return 1;
  }
  console.log(`OK ${kb}KB ≤ 180KB (gzip, / first load, ${chunks.length} files)`);
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}

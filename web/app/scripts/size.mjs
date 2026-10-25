#!/usr/bin/env node
// Spec 9장: the JavaScript the first screen (`/`) loads is at most 180KB gzip. Reads every script
// out/index.html asks for under /_next/static/ (chunks, _buildManifest, _ssgManifest) and sums
// their gzip sizes.
// Chunks loaded later (the chat sheet) and `nomodule` polyfills are not counted. Exit 1 when over.
// SP6 11.7: the next line names the chat sheet's chunk and its gzip size, for the PR only (no exit
// code). `loadChatSheet` is a bare import(), not next/dynamic, so no manifest lists it: it is the
// chunk outside the first screen that holds registerChatParts' marker.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

export const LIMIT = 180 * 1024;
export const CHAT_PARTS_MARKER = "sp6-chat-parts";

// `nomodule` scripts (Next's polyfills) are skipped by every browser that runs modules, iOS Safari included.
export function firstScreenChunks(html) {
  return [...html.matchAll(/<script\b[^>]*>/gi)]
    .map((m) => m[0])
    .filter((tag) => !/\snomodule\b/i.test(tag))
    .map((tag) => tag.match(/\ssrc="([^"]+)"/i)?.[1] ?? "")
    .filter((src) => src.startsWith("/_next/static/") && src.endsWith(".js"));
}

function jsFiles(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return jsFiles(path);
    return name.endsWith(".js") ? [path] : [];
  });
}

/** `chat sheet chunk: <n> KB (<files>)`, or `unknown` when no later chunk holds the marker. */
export function chatChunkLine(out, firstScreen) {
  const chunksDir = join(out, "_next/static/chunks");
  const skip = new Set(firstScreen.map((src) => join(out, src)));
  const found = jsFiles(chunksDir).filter((file) => !skip.has(file) && readFileSync(file, "utf8").includes(CHAT_PARTS_MARKER));
  if (found.length === 0) return "chat sheet chunk: unknown";
  const bytes = found.reduce((n, file) => n + gzipSync(readFileSync(file), { level: 9 }).length, 0);
  const names = found.map((file) => relative(join(out, "_next/static"), file).split("\\").join("/")).join(", ");
  return `chat sheet chunk: ${(bytes / 1024).toFixed(1)} KB (${names})`;
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
  const over = total > LIMIT;
  if (over) console.error(`OVER ${kb}KB > 180KB (gzip, / first load)`);
  else console.log(`OK ${kb}KB ≤ 180KB (gzip, / first load, ${chunks.length} files)`);
  console.log(chatChunkLine(out, chunks));
  return over ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}

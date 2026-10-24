#!/usr/bin/env node
// After `next build`: write out/sw-manifest.json ({buildId, files: every out/_next/static/** path})
// for the service worker's install step, and put the build id in out/sw.js's first line so each
// deploy ships different worker bytes (the browser then installs the new worker and its cache
// `app-<BUILD_ID>`). Also drops test files that Next copied from public/.
import { readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PLACEHOLDER = 'const BUILD_ID = "dev";';

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

export function writeSwManifest(outDir, nextDir) {
  const buildId = readFileSync(join(nextDir, "BUILD_ID"), "utf8").trim();
  if (!/^[A-Za-z0-9_-]+$/.test(buildId)) throw new Error("unexpected build id in .next/BUILD_ID");

  const staticDir = join(outDir, "_next/static");
  const files = walk(staticDir)
    .map((p) => "/" + relative(outDir, p).split("\\").join("/"))
    .sort();
  writeFileSync(join(outDir, "sw-manifest.json"), JSON.stringify({ buildId, files }) + "\n");

  const swPath = join(outDir, "sw.js");
  const sw = readFileSync(swPath, "utf8");
  const nl = sw.indexOf("\n");
  if (nl < 0 || sw.slice(0, nl) !== PLACEHOLDER) throw new Error(`out/sw.js must start with: ${PLACEHOLDER} (BUILD_ID line)`);
  writeFileSync(swPath, `const BUILD_ID = "${buildId}";` + sw.slice(nl));

  for (const name of readdirSync(outDir)) {
    if (/\.test\.[cm]?[jt]sx?$/.test(name)) rmSync(join(outDir, name));
  }
  return { buildId, files: files.length };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const appRoot = resolve(fileURLToPath(import.meta.url), "../..");
  const r = writeSwManifest(join(appRoot, "out"), join(appRoot, ".next"));
  console.log(`sw-manifest: build ${r.buildId}, ${r.files} static files`);
}

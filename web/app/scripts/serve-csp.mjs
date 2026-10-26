#!/usr/bin/env node
// Serves the built `out/` on 127.0.0.1:4173 for the Playwright runs (A10), with the same CSP the
// pages carry in their first <meta> (read back from out/index.html, so the two cannot drift) and
// the headers vercel.json sets, all as response headers. Build first with
// NEXT_PUBLIC_CONNECT_SRC="https://*.example.ts.net" so the fixture BE is inside connect-src.
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const root = resolve(here, "..", "out");
const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT ?? 4173);
const FIXTURE_BE = "https://gp76.example.ts.net";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".webmanifest": "application/manifest+json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".woff2": "font/woff2",
};

export function metaCsp(html) {
  const tag = html.match(/<meta\b[^>]*http-equiv\s*=\s*["']?Content-Security-Policy[^>]*>/i)?.[0];
  const content = tag?.match(/\scontent\s*=\s*"([^"]*)"/i)?.[1];
  if (!content) throw new Error("out/index.html has no CSP <meta>");
  return content.replaceAll("&#x27;", "'").replaceAll("&#39;", "'").replaceAll("&quot;", '"').replaceAll("&amp;", "&");
}

/** vercel.json headers for a path: later matching rules add to (or replace) earlier ones. */
export function vercelHeaders(config, path) {
  const out = [];
  for (const rule of config.headers ?? []) {
    const re = new RegExp(`^${rule.source.replace(/\(\.\*\)/g, "(.*)")}$`);
    if (re.test(path)) for (const h of rule.headers) out.push([h.key, h.value]);
  }
  return out;
}

function fileFor(urlPath) {
  const clean = normalize(decodeURIComponent(urlPath)).replace(/^([/\\])+/, "");
  const full = join(root, clean);
  if (full !== root && !full.startsWith(root + sep)) return null;
  if (existsSync(full) && statSync(full).isDirectory()) {
    const index = join(full, "index.html");
    return existsSync(index) ? index : null;
  }
  return existsSync(full) ? full : null;
}

function main() {
  if (!existsSync(join(root, "index.html"))) {
    console.error(`serve-csp: ${root} has no index.html. Run: NEXT_PUBLIC_CONNECT_SRC="https://*.example.ts.net" npm run build`);
    return 1;
  }
  const csp = metaCsp(readFileSync(join(root, "index.html"), "utf8"));
  const connect = csp.split(";").map((d) => d.trim()).find((d) => d.startsWith("connect-src")) ?? "";
  if (!connect.includes(".example.ts.net")) {
    console.error(`serve-csp: out/ was built without the fixture BE in connect-src (${connect}). Rebuild with NEXT_PUBLIC_CONNECT_SRC="https://*.example.ts.net".`);
    return 1;
  }
  const vercel = JSON.parse(readFileSync(resolve(here, "..", "vercel.json"), "utf8"));

  createServer((req, res) => {
    const path = new URL(req.url ?? "/", `http://${HOST}`).pathname;
    // trailingSlash export: /todos -> /todos/ (as Vercel does).
    if (!path.endsWith("/") && !extname(path) && fileFor(`${path}/`)) {
      res.writeHead(308, { Location: `${path}/` });
      res.end();
      return;
    }
    let file = fileFor(path);
    let status = 200;
    if (!file) {
      file = join(root, "404.html");
      status = 404;
    }
    // Two CSP headers: the page policy and vercel.json's frame-ancestors; the browser applies both.
    const headers = vercelHeaders(vercel, path);
    const cspValues = [csp, ...headers.filter(([k]) => k.toLowerCase() === "content-security-policy").map(([, v]) => v)];
    for (const [k, v] of headers) if (k.toLowerCase() !== "content-security-policy") res.setHeader(k, v);
    res.setHeader("Content-Security-Policy", cspValues);
    res.setHeader("Content-Type", TYPES[extname(file)] ?? "application/octet-stream");
    res.writeHead(status);
    res.end(readFileSync(file));
  }).listen(PORT, HOST, () => {
    console.log(`serve-csp: ${root} on http://${HOST}:${PORT} (connect-src for ${FIXTURE_BE})`);
  });
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const code = main();
  if (code !== 0) process.exitCode = code;
}

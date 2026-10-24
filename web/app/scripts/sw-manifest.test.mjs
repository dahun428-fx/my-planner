import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { writeSwManifest } from "./sw-manifest.mjs";

const SW = readFileSync(join(import.meta.dirname, "../public/sw.js"), "utf8");
const dirs = [];
afterEach(() => dirs.splice(0).forEach((d) => rmSync(d, { recursive: true, force: true })));

// A made-up `next build` result: .next/BUILD_ID and out/ with sw.js and some static files.
function fakeBuild(buildId) {
  const root = mkdtempSync(join(tmpdir(), "sw-manifest-"));
  dirs.push(root);
  mkdirSync(join(root, ".next"));
  writeFileSync(join(root, ".next/BUILD_ID"), buildId);
  mkdirSync(join(root, "out/_next/static/chunks/pages"), { recursive: true });
  mkdirSync(join(root, `out/_next/static/${buildId}`), { recursive: true });
  writeFileSync(join(root, "out/_next/static/chunks/pages/index-abc.js"), "x");
  writeFileSync(join(root, `out/_next/static/${buildId}/_buildManifest.js`), "x");
  writeFileSync(join(root, "out/sw.js"), SW);
  writeFileSync(join(root, "out/sw.test.ts"), "test file copied from public/");
  return root;
}

describe("sw-manifest", () => {
  it("writes the static file list and the build id", () => {
    const root = fakeBuild("build-one");
    writeSwManifest(join(root, "out"), join(root, ".next"));
    const manifest = JSON.parse(readFileSync(join(root, "out/sw-manifest.json"), "utf8"));
    expect(manifest).toEqual({
      buildId: "build-one",
      files: ["/_next/static/build-one/_buildManifest.js", "/_next/static/chunks/pages/index-abc.js"],
    });
    expect(readFileSync(join(root, "out/sw.js"), "utf8").split("\n")[0]).toBe('const BUILD_ID = "build-one";');
    expect(existsSync(join(root, "out/sw.test.ts"))).toBe(false);
  });

  it("two builds give different sw.js", () => {
    const a = fakeBuild("aaa111");
    const b = fakeBuild("bbb222");
    writeSwManifest(join(a, "out"), join(a, ".next"));
    writeSwManifest(join(b, "out"), join(b, ".next"));
    const la = readFileSync(join(a, "out/sw.js"), "utf8").split("\n");
    const lb = readFileSync(join(b, "out/sw.js"), "utf8").split("\n");
    expect(la[0]).not.toBe(lb[0]);
    expect(la.slice(1)).toEqual(lb.slice(1));
    expect(la.slice(1)).toEqual(SW.split("\n").slice(1));
  });

  it("refuses a sw.js whose first line was changed", () => {
    const root = fakeBuild("ccc333");
    writeFileSync(join(root, "out/sw.js"), "// moved\n" + SW);
    expect(() => writeSwManifest(join(root, "out"), join(root, ".next"))).toThrow(/BUILD_ID/);
  });

  it("refuses a strange build id", () => {
    const root = fakeBuild('x"; alert(1); "');
    expect(() => writeSwManifest(join(root, "out"), join(root, ".next"))).toThrow(/build id/);
  });
});

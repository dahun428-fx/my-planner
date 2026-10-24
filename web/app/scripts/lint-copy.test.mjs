// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const script = fileURLToPath(new URL("./lint-copy.mjs", import.meta.url));
let dirs = [];
function srcDir(files) {
  const dir = mkdtempSync(join(tmpdir(), "copy-"));
  dirs.push(dir);
  for (const [name, body] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, name)), { recursive: true });
    writeFileSync(join(dir, name), body);
  }
  return dir;
}
const run = (dir) => {
  const r = spawnSync(process.execPath, [script, dir], { encoding: "utf8" });
  return { code: r.status, out: r.stdout + r.stderr };
};
afterEach(() => {
  for (const d of dirs) rmSync(d, { recursive: true, force: true });
  dirs = [];
});

describe("lint-copy", () => {
  it("passes when Korean is only in allowed places", () => {
    const r = run(
      srcDir({
        "lib/copy.ts": `export const copy = { a: "오늘" };`,
        "api/types.gen.ts": `/** 설명 */ export type A = "가";`,
        "lib/x.test.ts": `const s = "테스트";`,
        "test/render.tsx": `const s = "고정";`,
        "pages/index.tsx": `// 한국어 주석은 된다\nexport default () => <p title="ok">{"ok"}</p>;`,
      }),
    );
    expect(r.out).toBe("");
    expect(r.code).toBe(0);
  });

  it("fails on Hangul string literal", () => {
    const r = run(srcDir({ "screens/A.tsx": `export const a = 1;\nconst t = \`오늘 \${a}\`;` }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/screens\/A\.tsx:2/);
  });

  it("fails on JSX text and attribute", () => {
    const r = run(srcDir({ "pages/b.tsx": `export default () => (\n  <p aria-label="닫기">\n    안녕\n  </p>\n);` }));
    expect(r.code).toBe(1);
    expect(r.out).toMatch(/pages\/b\.tsx:2/);
    expect(r.out).toMatch(/pages\/b\.tsx:3/);
  });
});

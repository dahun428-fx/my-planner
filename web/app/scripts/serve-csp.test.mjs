// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { metaCsp, vercelHeaders } from "./serve-csp.mjs";

const vercel = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));

describe("serve-csp", () => {
  it("reads the page CSP back from the first <meta>, entities decoded", () => {
    const html = `<head><meta charSet="utf-8"/><meta http-equiv="Content-Security-Policy" content="default-src &#x27;self&#x27;; connect-src &#x27;self&#x27; https://*.example.ts.net"/></head>`;
    expect(metaCsp(html)).toBe("default-src 'self'; connect-src 'self' https://*.example.ts.net");
    expect(() => metaCsp("<head></head>")).toThrow(/no CSP/);
  });

  it("adds vercel.json headers by path", () => {
    const page = Object.fromEntries(vercelHeaders(vercel, "/todos/"));
    expect(page).toMatchObject({
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "Content-Security-Policy": "frame-ancestors 'none'",
    });
    expect(page["Cache-Control"]).toBeUndefined();
    expect(Object.fromEntries(vercelHeaders(vercel, "/sw.js"))["Cache-Control"]).toBe("no-cache");
  });
});

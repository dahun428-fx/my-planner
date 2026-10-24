import { defineConfig, devices } from "@playwright/test";

// A10: the built `out/` served with its CSP as response headers (scripts/serve-csp.mjs). Build it
// first with NEXT_PUBLIC_CONNECT_SRC="https://*.example.ts.net" (`npm run e2e` does).
export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/.results",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 390, height: 844 },
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    // A service worker would answer fetches itself and slip past page.route; sw.test.ts covers it.
    serviceWorkers: "block",
  },
  webServer: {
    command: "node scripts/serve-csp.mjs",
    url: "http://127.0.0.1:4173/",
    reuseExistingServer: false,
    stdout: "ignore",
  },
});

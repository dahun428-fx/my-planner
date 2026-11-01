import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { standingCopy } from "../src/lib/copyStanding";
import { mockBe, seedConn } from "./routes";

// SP13 14장 T12: status screen → "객관적 위치 자세히 ›" → the detail screen with its radar SVG,
// against the fixture BE (the Task 3 fake person). Light and dark; no sideways scroll at 390px and
// no CSP report (the radar and bars use drawing attributes only).
const OUT = process.env.STANDING_SHOTS ?? "e2e/__screens__/sp13";

for (const scheme of ["light", "dark"] as const) {
  test.describe(`standing ${scheme}`, () => {
    test.use({ colorScheme: scheme });

    test("status, detail link, detail screen with radar", async ({ page }) => {
      const csp: string[] = [];
      page.on("console", (m) => {
        if (/Content Security Policy/i.test(m.text())) csp.push(m.text());
      });
      await seedConn(page);
      await mockBe(page, { standing: true });
      await page.goto("/status/");
      await expect(page.getByRole("heading", { level: 1, name: copy.statusScreen.heading })).toBeVisible();
      await expect(page.getByText("위치 79 (IT 63)")).toBeVisible();
      await expect(page.getByRole("heading", { level: 2, name: copy.statusScreen.innateHeading })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
      await page.screenshot({ path: `${OUT}/status-${scheme}.png`, fullPage: true });

      await page.getByRole("link", { name: copy.statusScreen.standingLink }).click();
      await expect(page).toHaveURL(/\/status\/standing\/$/);
      await expect(page.getByRole("heading", { level: 1, name: standingCopy.title })).toBeVisible();
      const radar = page.getByRole("img", { name: standingCopy.radarLabel });
      await expect(radar).toBeVisible();
      expect(await radar.evaluate((el) => el.tagName.toLowerCase())).toBe("svg");
      await expect(radar.locator("line[data-axis]")).toHaveCount(9);
      await expect(page.getByRole("heading", { level: 2, name: standingCopy.measuresHeading })).toBeVisible();
      await expect(page.getByText(standingCopy.krw(62_000_000))).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
      await page.screenshot({ path: `${OUT}/standing-${scheme}.png`, fullPage: true });
      expect(csp).toEqual([]);
    });
  });
}

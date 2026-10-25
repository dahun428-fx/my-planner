import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { PALETTE_GROUND, PALETTES } from "../src/lib/theme";
import { mockBe, seedConn } from "./routes";

// Every colour preset with every theme, under both system schemes (6 × 3 × 2): the page's --ground
// and the theme-color metas are that palette's ground for the mode in effect, and each swatch in
// Settings shows its own palette whatever the page has.
const ground = (page: import("@playwright/test").Page, sel: string) =>
  page.locator(sel).evaluateAll((els) => els.map((el) => getComputedStyle(el).getPropertyValue("--ground").trim()));

for (const scheme of ["light", "dark"] as const) {
  test.describe(`system ${scheme}`, () => {
    test.use({ colorScheme: scheme });
    for (const theme of ["system", "light", "dark"] as const) {
      test(`theme ${theme}: each palette applies`, async ({ page }) => {
        const mode = theme === "system" ? scheme : theme;
        await page.addInitScript((t) => localStorage.setItem("mp.theme", t), theme);
        await seedConn(page);
        await mockBe(page);
        await page.goto("/settings/");
        const group = page.getByRole("radiogroup", { name: copy.settings.palette });
        await expect(group).toBeVisible();
        for (const p of PALETTES) {
          await group.getByRole("radio", { name: copy.settings.palettes[p] }).click();
          await expect(group.getByRole("radio", { name: copy.settings.palettes[p] })).toHaveAttribute("aria-checked", "true");
          expect(await ground(page, ":root"), p).toEqual([PALETTE_GROUND[p][mode]]);
          const metas = await page.locator('meta[name="theme-color"]').evaluateAll((ms) => ms.map((m) => m.getAttribute("content")));
          expect(metas, p).toEqual(theme === "system" ? [PALETTE_GROUND[p].light, PALETTE_GROUND[p].dark] : [PALETTE_GROUND[p][mode], PALETTE_GROUND[p][mode]]);
          expect(await ground(page, "[role=radiogroup] [data-palette]"), p).toEqual(PALETTES.map((q) => PALETTE_GROUND[q][mode]));
        }
        // The choice stays after a reload.
        await page.reload();
        await expect(group.getByRole("radio", { name: copy.settings.palettes.lavender })).toHaveAttribute("aria-checked", "true");
        expect(await ground(page, ":root")).toEqual([PALETTE_GROUND.lavender[mode]]);
      });
    }
  });
}

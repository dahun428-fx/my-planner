import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { AGENT_NOTE_LINE, mockBe, seedConn } from "./routes";

// SP14 10장: "새로 본 것 n개" under the mate, the brief's observation line with its pictogram, and
// More › "비서 메모" opened in place. Fake BE data only. AGENT_SHOTS=<dir> saves the light screens.
const SHOTS = process.env.AGENT_SHOTS;

for (const scheme of ["light", "dark"] as const) {
  test.describe(`agent notes ${scheme}`, () => {
    test.use({ colorScheme: scheme });

    test("picker hint, brief line, more row", async ({ page }) => {
      await seedConn(page);
      await mockBe(page, { agentNotes: true });
      await page.goto("/");

      // The brief: the observation under the body, with the dumbbell, not in the Markdown.
      const line = page.locator("li", { hasText: AGENT_NOTE_LINE });
      await expect(line).toBeVisible();
      await expect(line.locator('use[href="#p-dumbbell"]')).toHaveCount(1);
      await expect(line.getByText(copy.agentNames.mate)).toBeVisible();
      if (SHOTS && scheme === "light") await page.screenshot({ path: `${SHOTS}/today-brief-note-light.png` });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

      // The partner pick: the count under the mate, its name unchanged.
      await page.getByRole("button", { name: copy.chat.launcher }).click();
      const mate = page.getByRole("radio", { name: copy.chat.agents.mate, exact: true });
      await expect(mate).toHaveAccessibleDescription(copy.chat.agents.unseen(3));
      await expect(page.getByText(copy.chat.agents.unseen(3))).toBeVisible();
      if (SHOTS && scheme === "light") await page.screenshot({ path: `${SHOTS}/chat-picker-hint-light.png` });
      await page.getByRole("button", { name: copy.chat.close }).first().click();

      // More › 비서 메모 opens in place.
      await page.getByRole("link", { name: copy.more.title }).click();
      const row = page.getByRole("button", { name: copy.more.agentNotes });
      await row.click();
      await expect(row).toHaveAttribute("aria-expanded", "true");
      const panel = page.getByRole("main");
      await expect(panel.getByText(AGENT_NOTE_LINE)).toBeVisible();
      await expect(panel.getByText("10/24")).toBeVisible();
      await expect(page).toHaveURL(/\/more\/$/);
      if (SHOTS && scheme === "light") await page.screenshot({ path: `${SHOTS}/more-agent-notes-light.png` });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    });
  });
}

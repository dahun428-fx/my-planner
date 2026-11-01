import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { copyPanel } from "../src/lib/copyPanel";
import { managerSse, mockBe, PANEL_SUGGESTION, seedConn } from "./routes";

// SP15 11장: the life manager in the partner pick (compass), its budget line and chips, an answer with
// a panel suggestion card and the folded expert notes, under the real CSP. The card's and the notes'
// stylesheets come with the chat sheet's chunk. Fake BE data only. LIFE_SHOTS=<dir> saves the light screens.
const SHOTS = process.env.LIFE_SHOTS;

for (const scheme of ["light", "dark"] as const) {
  test.describe(`life manager ${scheme}`, () => {
    test.use({ colorScheme: scheme });

    test("pick, chips, suggestion card, expert notes", async ({ page }) => {
      const problems: string[] = [];
      page.on("console", (m) => {
        if (/content.security.policy|CSP/i.test(m.text())) problems.push(`console ${m.type()}: ${m.text()}`);
      });
      await seedConn(page);
      const { chatBodies } = await mockBe(page, { manager: true, chat: [{ body: managerSse() }] });
      await page.goto("/");
      await page.getByRole("button", { name: copy.chat.launcher }).click();

      const manager = page.getByRole("radio", { name: copy.agentNames.manager, exact: true });
      await expect(manager.locator('use[href="#p-compass"]')).toHaveCount(1);
      await expect(manager).toHaveAccessibleDescription(copy.chat.agents.unseen(2));
      await manager.click();
      await expect(page.getByRole("heading", { level: 2, name: copy.agentNames.manager })).toBeVisible();
      await expect(page.getByText(copyPanel.budget(1))).toBeVisible();
      const chips = page.getByRole("group", { name: copy.chat.chipsLabel });
      await expect(chips.getByRole("button")).toHaveText([copyPanel.chips.manager_full, copyPanel.chips.manager_week, copyPanel.chips.manager_upload]);
      if (SHOTS && scheme === "light") await page.screenshot({ path: `${SHOTS}/manager-picker-light.png` });

      const input = page.getByRole("textbox", { name: copyPanel.manager.inputLabel });
      await expect(input).toBeEnabled();
      await input.fill("오후에 너무 졸려요");
      await page.getByRole("button", { name: copy.chat.send }).click();
      await expect(page.getByRole("heading", { name: PANEL_SUGGESTION.title })).toBeVisible();
      expect(chatBodies[0]).toMatchObject({ agent: "manager" });
      if (SHOTS && scheme === "light") {
        await page.getByRole("heading", { name: PANEL_SUGGESTION.title }).scrollIntoViewIfNeeded();
        await page.screenshot({ path: `${SHOTS}/manager-card-light.png` });
      }

      // The card's stylesheet is there (CSP style-src 'self'): the meta line is a flex row with the dot.
      const meta = page.locator("p[data-meta]");
      await expect(meta).toHaveCSS("display", "flex");
      await expect(page.locator('.area-dot[data-area="health"]')).toBeVisible();
      await page.getByText(copyPanel.card.evidence).click();
      await expect(page.getByText(copyPanel.card.groups.external)).toBeVisible();
      await expect(page.getByRole("link", { name: PANEL_SUGGESTION.evidence[0].note })).toBeVisible();

      const notes = page.getByText(copyPanel.expertNotes(2));
      await expect(notes).toBeVisible();
      await expect(notes).toHaveCSS("min-height", "44px"); // ExpertNotes.module.css
      await notes.click();
      await expect(page.getByText(copyPanel.experts.health, { exact: true })).toBeVisible();
      await page.getByRole("log").evaluate((el) => el.scrollTo(0, el.scrollHeight));
      if (SHOTS && scheme === "light") await page.screenshot({ path: `${SHOTS}/manager-answer-light.png` });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

      await page.getByRole("button", { name: copyPanel.card.dismiss }).click();
      const sheet = page.getByRole("dialog", { name: copyPanel.reasonTitle });
      await expect(sheet.getByRole("button", { name: copyPanel.reasons.too_big })).toBeVisible();
      if (SHOTS && scheme === "light") await page.waitForTimeout(400); // the sheet's slide (280ms) is over
      if (SHOTS && scheme === "light") await page.screenshot({ path: `${SHOTS}/manager-dismiss-reasons-light.png` });
      expect(problems).toEqual([]);
    });
  });
}

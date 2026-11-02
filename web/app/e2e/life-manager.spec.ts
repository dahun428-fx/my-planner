import { expect, type Page, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { copyPanel } from "../src/lib/copyPanel";
import { managerSse, mockBe, OLD_REPORT_LINE, OWNER_STATEMENTS, PANEL_SUGGESTION, REPORT_WEEK_TITLE, seedConn } from "./routes";

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

// SP15 10장, 5.4: the card's 받기, the status screen's line to the life report (a client move: its
// chunk's stylesheet comes as a <link> under style-src 'self'), and the more screen's "내가 한 말".
// Fake BE data only. No CSP report, no sideways scroll at 390px, light and dark.
const T = copyPanel.report;
async function watchCsp(page: Page): Promise<() => Promise<string[]>> {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (/content.security.policy|CSP/i.test(m.text())) problems.push(`console ${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __csp: string[] }).__csp = seen;
    document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  return async () => [...problems, ...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp))];
}

test("받기 on the panel suggestion card", async ({ page }) => {
  await seedConn(page);
  const { actionBodies } = await mockBe(page, { manager: true, chat: [{ body: managerSse() }] });
  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  await page.getByRole("radio", { name: copy.agentNames.manager, exact: true }).click();
  const input = page.getByRole("textbox", { name: copyPanel.manager.inputLabel });
  await expect(input).toBeEnabled();
  await input.fill("오후에 너무 졸려요");
  await page.getByRole("button", { name: copy.chat.send }).click();
  await expect(page.getByText(copyPanel.expertNotes(2))).toBeVisible();
  await page.getByRole("button", { name: copyPanel.card.accept }).click();
  await expect(page.getByText(copyPanel.card.accepted, { exact: true })).toBeVisible();
  expect(actionBodies).toMatchObject([{ action: "accept_suggestion", args: { id: PANEL_SUGGESTION.id } }]);
  await expect(page.getByRole("button", { name: copy.activity.undo })).toBeVisible();
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`life report ${scheme}`, () => {
    test.use({ colorScheme: scheme });

    test("status line, report screen, past report", async ({ page }) => {
      const problems = await watchCsp(page);
      await seedConn(page);
      await mockBe(page, { manager: true, standing: true });
      await page.goto("/status/");
      await expect(page.getByRole("heading", { level: 1, name: copy.statusScreen.heading })).toBeVisible();
      await page.getByRole("link", { name: T.link }).click();
      await expect(page).toHaveURL(/\/status\/report\/$/);
      await expect(page.getByRole("heading", { level: 1, name: T.title })).toBeVisible();
      await expect(page.getByRole("heading", { level: 2, name: T.sections.summary })).toBeVisible();
      // LifeReport.module.css came with the chunk (not blocked): the past dates are 44px buttons, the
      // score board draws its dots.
      await expect(page.getByRole("button", { name: "2026.08.02" })).toHaveCSS("min-height", "44px");
      await expect(page.locator('li[data-axis] circle[data-cohort="national"]')).toHaveCount(6);
      await expect(page.getByRole("img", { name: T.radarLabel })).toBeVisible();
      await expect(page.getByText(REPORT_WEEK_TITLE)).toBeVisible(); // 이번 주, the titles saved with the report
      const health = page.locator('details[data-expert="health"]');
      await health.getByText(copyPanel.experts.health, { exact: true }).click();
      await expect(health.getByText(T.avoid)).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/life-report-${scheme}.png`, fullPage: true });

      await page.getByRole("button", { name: "2026.08.02" }).click();
      await expect(page.getByText(OLD_REPORT_LINE)).toBeVisible();
      await page.waitForLoadState("networkidle");
      expect(await problems()).toEqual([]);
    });

    test("the report page opened cold has its styles too", async ({ page }) => {
      const problems = await watchCsp(page);
      await seedConn(page);
      await mockBe(page, { manager: true });
      await page.goto("/status/report/");
      await expect(page.getByRole("button", { name: "2026.10.31" })).toHaveCSS("min-height", "44px");
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
      expect(await problems()).toEqual([]);
    });

    test("more: 내가 한 말 opens, 지우기 retires a line", async ({ page }) => {
      const problems = await watchCsp(page);
      await seedConn(page);
      const { actionBodies } = await mockBe(page, { manager: true });
      await page.goto("/more/");
      const row = page.getByRole("button", { name: copyPanel.statements.title });
      await row.click();
      await expect(row).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByText(OWNER_STATEMENTS[0].text)).toBeVisible();
      const line = page.locator("li", { hasText: OWNER_STATEMENTS[1].text });
      const retire = line.getByRole("button", { name: copyPanel.statements.retire });
      await expect(retire).toHaveCSS("min-height", "44px"); // OwnerStatements.module.css, from its chunk
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/statements-${scheme}.png`, fullPage: true });
      await retire.click();
      await expect(page.getByText(OWNER_STATEMENTS[1].text)).toHaveCount(0);
      expect(actionBodies).toMatchObject([{ action: "retire_statement", args: { id: OWNER_STATEMENTS[1].id } }]);
      await expect(page.getByRole("button", { name: copy.activity.undo })).toBeVisible();
      expect(await problems()).toEqual([]);
    });

    test("more: /more/#statements comes in open", async ({ page }) => {
      await seedConn(page);
      await mockBe(page, { manager: true });
      await page.goto("/more/#statements");
      await expect(page.getByRole("button", { name: copyPanel.statements.title })).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByText(OWNER_STATEMENTS[0].text)).toBeVisible();
    });
  });
}

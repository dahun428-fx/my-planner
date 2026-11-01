import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { matePlanSse, mockBe, seedConn, WORKOUT_PLAN_TITLE } from "./routes";

// SP12 spec 13장 17: the fake BE answers a talk with the mate with a plan card; the more screen
// then has a "운동" row and the workout screen shows the same plan. Light and dark.
for (const scheme of ["light", "dark"] as const) {
  test.describe(`workout mate ${scheme}`, () => {
    test.use({ colorScheme: scheme });

    test("mate chat, plan card, more, workout screen", async ({ page }) => {
      await seedConn(page);
      const be = await mockBe(page, { mate: true, chat: [{ body: matePlanSse() }] });
      await page.goto("/");
      await page.getByRole("button", { name: copy.chat.launcher }).click();
      await page.getByRole("radio", { name: copy.chat.agents.mate }).click();
      const input = page.getByRole("textbox", { name: copy.chat.mate.inputLabel });
      await expect(input).toBeEnabled();
      await input.fill("주 2번, 한 번에 40분 정도로 짜줘");
      await page.getByRole("button", { name: copy.chat.send }).click();
      await expect(page.getByText(WORKOUT_PLAN_TITLE).first()).toBeVisible();
      expect((be.chatBodies[0] as { agent?: string }).agent).toBe("mate");
      await page.getByRole("button", { name: copy.chat.close }).first().click();

      await page.getByRole("link", { name: copy.more.title }).click();
      await page.getByRole("link", { name: copy.more.workout }).click();
      await expect(page.getByRole("heading", { level: 1, name: copy.workout.title })).toBeVisible();
      // The sheet's card may still be sliding away: look inside the screen's own main.
      const screen = page.getByRole("main");
      await expect(screen.getByText(WORKOUT_PLAN_TITLE)).toBeVisible();
      await screen.getByRole("button", { name: copy.workout.expandLabel("하체") }).click();
      await expect(screen.getByText("고블릿 스쿼트")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    });
  });
}

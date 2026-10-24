import { mkdirSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { golden, LONG_TITLE, mockBe, seedConn } from "./routes";

// DESIGN.md direction A "종이와 잉크", as the screens spec does it: Today, Todos, the chat (my message,
// a Markdown answer and a generative card) and Settings, light and dark, in the default paper
// palette, and Today in the ink preset. Saved to $DESIGN_SHOTS (default e2e/__screens__/design/,
// not committed) for the PR.
const OUT = process.env.DESIGN_SHOTS ?? "e2e/__screens__/design";
mkdirSync(OUT, { recursive: true });

const ANSWER = "## 이번 주\\n\\n**운동**과 *이력서 다듬기*만 해 두면 충분해요.\\n\\n- 물 마시기\\n- 스트레칭\\n\\n아래에서 골라 주세요.";
const chatSse = () => golden("chat_propose_tasks.sse").replace('"delta":"이번 주에 이 둘을 해 보면 어때요?"', `"delta":"${ANSWER}"`);

type Shot = { name: string; full?: boolean; open(page: Page): Promise<void> };
const heading = (page: Page, name: string) => page.getByRole("heading", { level: 1, name });

const SHOTS: Shot[] = [
  {
    name: "today",
    open: async (page) => {
      await page.goto("/");
      await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
    },
  },
  {
    name: "todos",
    open: async (page) => {
      await page.goto("/todos/");
      await expect(heading(page, copy.todos.title)).toBeVisible();
      await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
    },
  },
  {
    name: "chat",
    open: async (page) => {
      await page.goto("/");
      await page.getByRole("button", { name: copy.chat.launcher }).click();
      const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
      await expect(input).toBeEnabled();
      await input.fill("이번 주 할 일 정리해 줘");
      await page.getByRole("button", { name: copy.chat.send }).click();
      await expect(page.getByText(copy.parts.draftHeading)).toBeVisible();
      await expect(page.getByText("만 해 두면 충분해요.", { exact: false })).toBeVisible();
      // The field with a draft in it, so the ready outline shows too.
      await input.fill("고마워");
    },
  },
  {
    name: "settings",
    full: true,
    open: async (page) => {
      await page.goto("/settings/");
      await expect(heading(page, copy.settings.title)).toBeVisible();
    },
  },
];

async function shoot(page: Page, path: string, full = false) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path, fullPage: full });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`design ${scheme}`, () => {
    test.use({ colorScheme: scheme });
    for (const s of SHOTS) {
      test(`${s.name} paper (${scheme})`, async ({ page }) => {
        await seedConn(page);
        await mockBe(page, { chat: [{ body: chatSse() }] });
        await s.open(page);
        expect(await page.evaluate(() => document.documentElement.dataset.palette ?? "paper")).toBe("paper");
        await shoot(page, `${OUT}/${s.name}-${scheme}.png`, s.full);
      });
    }
    test(`today ink (${scheme})`, async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("mp.palette", "ink"));
      await seedConn(page);
      await mockBe(page);
      await SHOTS[0].open(page);
      expect(await page.evaluate(() => document.documentElement.dataset.palette)).toBe("ink");
      await shoot(page, `${OUT}/today-ink-${scheme}.png`);
    });
  });
}

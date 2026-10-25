import { mkdirSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { PALETTES } from "../src/lib/theme";
import { LONG_TITLE, beUnreachable, mockBe, seedConn } from "./routes";

// Spec 13장 "눈으로": the canvas screens (and the SP7 habits screen with its detail sheet) at 390×844, light and dark, saved to
// e2e/__screens__/ (not committed) to be read next to the mockups. Each screen also must not
// scroll sideways, with a 200-character todo title in the fixtures (spec 9장).

type Screen = { name: string; seed: boolean; open(page: Page): Promise<void> };

const heading = (page: Page, name: string) => page.getByRole("heading", { level: 1, name });

const SCREENS: Screen[] = [
  {
    name: "today",
    seed: true,
    open: async (page) => {
      await page.goto("/");
      await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
    },
  },
  {
    name: "chat",
    seed: true,
    open: async (page) => {
      await page.goto("/");
      await page.getByRole("button", { name: copy.chat.launcher }).click();
      const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
      await expect(input).toBeEnabled();
      await input.fill("이번 주 할 일 정리해 줘");
      await page.getByRole("button", { name: copy.chat.send }).click();
      await expect(page.getByText(copy.parts.draftHeading)).toBeVisible();
    },
  },
  {
    // SP9 9.5: the list screen inside the chat sheet, and the quick chip row in the chat.
    name: "conversations",
    seed: true,
    open: async (page) => {
      await page.goto("/");
      await page.getByRole("button", { name: copy.chat.launcher }).click();
      await expect(page.getByRole("group", { name: copy.chat.chipsLabel })).toBeVisible();
      await page.getByRole("button", { name: copy.chat.pastConversations }).click();
      await expect(page.getByText("치과 예약")).toBeVisible();
      await expect(page.getByText(copy.chat.checkinTag, { exact: true })).toBeVisible();
    },
  },
  {
    name: "checkin",
    seed: true,
    open: async (page) => {
      await page.goto("/checkin/?id=341");
      await expect(heading(page, copy.loops.evening_checkin)).toBeVisible();
      await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
    },
  },
  {
    name: "offline",
    seed: true,
    open: async (page) => {
      // A first visit keeps the snapshot; then the laptop goes away.
      await page.goto("/");
      await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await beUnreachable(page);
      await page.reload();
      await expect(page.getByText(copy.offline.lead)).toBeVisible();
      await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
    },
  },
  {
    name: "todos",
    seed: true,
    open: async (page) => {
      await page.goto("/todos/");
      await expect(heading(page, copy.todos.title)).toBeVisible();
      await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
    },
  },
  {
    name: "activity",
    seed: true,
    open: async (page) => {
      await page.goto("/activity/");
      await expect(heading(page, copy.activity.title)).toBeVisible();
      await expect(page.getByRole("button", { name: copy.activity.undo }).first()).toBeVisible();
    },
  },
  {
    name: "settings",
    seed: true,
    open: async (page) => {
      await page.goto("/settings/");
      await expect(heading(page, copy.settings.title)).toBeVisible();
      await page.waitForLoadState("networkidle");
    },
  },
  {
    name: "habits",
    seed: true,
    open: async (page) => {
      await page.goto("/habits/");
      await expect(heading(page, copy.habits.heading)).toBeVisible();
      await page.getByRole("button", { name: copy.habits.archived }).click();
      await expect(page.getByText("피아노")).toBeVisible();
    },
  },
  {
    name: "habit-detail",
    seed: true,
    open: async (page) => {
      await page.goto("/habits/");
      await page.getByRole("button", { name: /운동/ }).click();
      await expect(page.getByRole("group", { name: copy.habits.gridLabel })).toBeVisible();
      await expect(page.getByText(copy.habits.week(2), { exact: true })).toBeVisible();
    },
  },
  {
    name: "status",
    seed: true,
    open: async (page) => {
      await page.goto("/status/");
      await expect(heading(page, copy.statusScreen.heading)).toBeVisible();
      await expect(page.getByRole("heading", { level: 2, name: copy.statusScreen.recentHeading })).toBeVisible();
      await expect(page.getByRole("heading", { level: 2, name: copy.statusScreen.momentsHeading })).toBeVisible();
      await expect(page.getByText("포트폴리오 사례 하나를 끝까지 다듬었어요")).toBeVisible();
      await page.getByRole("button", { name: copy.statusScreen.hiddenGroup(1) }).click();
      await expect(page.getByText("조용히 숨긴 순간이에요")).toBeVisible();
    },
  },
  {
    name: "connect",
    seed: false,
    open: async (page) => {
      await page.goto("/connect/");
      await expect(heading(page, copy.connect.title)).toBeVisible();
    },
  },
];

for (const scheme of ["light", "dark"] as const) {
  test.describe(scheme, () => {
    test.use({ colorScheme: scheme });
    for (const s of SCREENS) {
      test(`${s.name} (${scheme})`, async ({ page }) => {
        if (s.seed) await seedConn(page);
        await mockBe(page);
        await s.open(page);
        await page.waitForLoadState("networkidle");
        const width = await page.evaluate(() => document.documentElement.scrollWidth);
        expect(width).toBeLessThanOrEqual(390);
        await page.screenshot({ path: `e2e/__screens__/${s.name}-${scheme}.png` });
        // The whole page too, for what lies below the fold (fixed bars land where the first view ends).
        await page.screenshot({ path: `e2e/__screens__/full/${s.name}-${scheme}.png`, fullPage: true });
      });
    }
  });
}

// Each colour preset (Settings › 색감): Today and the whole of Settings, light and dark, saved to
// e2e/__screens__/palettes/ to be compared side by side.
for (const scheme of ["light", "dark"] as const) {
  test.describe(`palettes ${scheme}`, () => {
    test.use({ colorScheme: scheme });
    for (const palette of PALETTES) {
      test(`${palette} (${scheme})`, async ({ page }) => {
        await page.addInitScript((p) => localStorage.setItem("mp.palette", p), palette);
        await seedConn(page);
        await mockBe(page);
        await page.goto("/");
        await expect(page.getByText(LONG_TITLE).first()).toBeVisible();
        await page.waitForLoadState("networkidle");
        expect(await page.evaluate(() => document.documentElement.dataset.palette ?? "paper")).toBe(palette);
        await page.screenshot({ path: `e2e/__screens__/palettes/today-${palette}-${scheme}.png` });
        await page.goto("/settings/");
        await expect(page.getByRole("radiogroup", { name: copy.settings.palette })).toBeVisible();
        await page.waitForLoadState("networkidle");
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
        await page.screenshot({ path: `e2e/__screens__/palettes/settings-${palette}-${scheme}.png`, fullPage: true });
      });
    }
  });
}

// SP6 13장 "눈으로": G-BE2's chat_gallery answer in the chat sheet at 390×844. (1) Each of the seven
// cards on its own, paper light and dark (14), to e2e/__screens__/sp6/cards/; (2) the whole sheet
// in each colour preset, light and dark (12), to e2e/__screens__/sp6/palettes/. The page never
// scrolls sideways (Review Focus 2), and once more at 320px wide.
const SP6_OUT = "e2e/__screens__/sp6";
mkdirSync(`${SP6_OUT}/cards`, { recursive: true });
mkdirSync(`${SP6_OUT}/palettes`, { recursive: true });

const SP6_CARDS: { name: string; has: (page: Page) => ReturnType<Page["getByText"]> }[] = [
  { name: "ui_date_choice", has: (page) => page.getByText("치과 예약은 언제 할까요?") },
  { name: "ui_result", has: (page) => page.getByRole("img", { name: copy.parts.changeAria("10월 25일 (일)", "10월 26일 (월)") }) },
  { name: "ui_period_list", has: (page) => page.getByRole("heading", { name: copy.parts.nextWeek }) },
  { name: "ui_block", has: (page) => page.getByRole("heading", { name: "이번 주 운동" }) },
  { name: "ui_todo_list", has: (page) => page.getByRole("heading", { name: "꾸민 목록" }) },
  { name: "ui_choice", has: (page) => page.getByText("어느 쪽이 좋아요?") },
  { name: "ui_summary_card", has: (page) => page.getByRole("heading", { name: "꾸민 정리" }) },
];

async function openGallery(page: Page) {
  await seedConn(page);
  await mockBe(page, { chat: ["chat_gallery.sse"] });
  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
  await expect(input).toBeEnabled();
  await input.fill("전부 보여 줘");
  await page.getByRole("button", { name: copy.chat.send }).click();
  await expect(page.getByText("꾸민 갤러리예요.")).toBeVisible();
  await expect(page.getByText(copy.parts.unknown)).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
}
const pageWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth);

for (const scheme of ["light", "dark"] as const) {
  test.describe(`sp6 cards ${scheme}`, () => {
    test.use({ colorScheme: scheme });
    test(`seven cards, paper (${scheme})`, async ({ page }) => {
      await openGallery(page);
      expect(await page.evaluate(() => document.documentElement.dataset.palette ?? "paper")).toBe("paper");
      const cards = page.getByRole("log").locator("section");
      await expect(cards).toHaveCount(SP6_CARDS.length);
      for (const c of SP6_CARDS) {
        const card = cards.filter({ has: c.has(page) });
        await expect(card, c.name).toHaveCount(1);
        await card.scrollIntoViewIfNeeded();
        expect(await pageWidth(page), c.name).toBeLessThanOrEqual(390);
        await card.screenshot({ path: `${SP6_OUT}/cards/${c.name}-${scheme}.png` });
      }
    });
  });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`sp6 palettes ${scheme}`, () => {
    test.use({ colorScheme: scheme });
    for (const palette of PALETTES) {
      test(`sheet ${palette} (${scheme})`, async ({ page }) => {
        await page.addInitScript((p) => localStorage.setItem("mp.palette", p), palette);
        await openGallery(page);
        expect(await page.evaluate(() => document.documentElement.dataset.palette ?? "paper")).toBe(palette);
        expect(await pageWidth(page)).toBeLessThanOrEqual(390);
        // The whole sheet: the window grows until the conversation fits without scrolling inside it.
        const log = page.getByRole("log");
        const extra = await log.evaluate((el) => el.scrollHeight - el.clientHeight);
        await page.setViewportSize({ width: 390, height: 844 + Math.max(0, extra) });
        await log.evaluate((el) => el.scrollTo(0, 0));
        expect(await pageWidth(page)).toBeLessThanOrEqual(390);
        await page.getByRole("dialog").screenshot({ path: `${SP6_OUT}/palettes/sheet-${palette}-${scheme}.png` });
      });
    }
  });
}

test("sp6 cards do not scroll sideways at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await openGallery(page);
  await expect(page.getByRole("log").locator("section")).toHaveCount(SP6_CARDS.length);
  expect(await pageWidth(page)).toBeLessThanOrEqual(320);
  const widest = await page.getByRole("log").locator("section").evaluateAll((els) => Math.max(...els.map((e) => e.getBoundingClientRect().right)));
  expect(widest).toBeLessThanOrEqual(320);
  await page.screenshot({ path: `${SP6_OUT}/sheet-320.png` });
});


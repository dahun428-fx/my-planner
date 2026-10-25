import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { markdownSse, mockBe, seedConn } from "./routes";

// Spec 13장 "CSP 실행": under the real CSP headers, the chat part is drawn (the json-schema check
// and zod run without eval) and nothing breaks the policy. Two tests, so a failure says which.

test.beforeEach(async ({ page }) => {
  await seedConn(page);
});

test("chat part renders under CSP", async ({ page }) => {
  await mockBe(page, { chat: ["chat_propose_tasks.sse"] });
  const res = await page.goto("/");
  // The policy really arrives as a response header (serve-csp), not only as the <meta>.
  const csp = (await res!.headerValue("content-security-policy")) ?? "";
  expect(csp).toContain("script-src 'self'");
  expect(csp).toContain("font-src 'self'");
  expect(csp).toContain("connect-src 'self' https://*.example.ts.net");
  expect(csp).toContain("frame-ancestors 'none'");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
  await expect(input).toBeEnabled();
  await input.fill("내일 치과 추가해 줘");
  await page.getByRole("button", { name: copy.chat.send }).click();
  await expect(page.getByText(copy.parts.draftHeading)).toBeVisible();
  await expect(page.getByRole("button", { name: copy.parts.confirmCount(2) })).toBeVisible();
  await expect(page.getByText(copy.parts.unknown)).toHaveCount(0);
});

test("no CSP violations", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (/content.security.policy|CSP/i.test(m.text())) problems.push(`console ${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __csp: string[] }).__csp = seen;
    document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI} at ${e.sourceFile}:${e.lineNumber}:${e.columnNumber}`));
  });
  await mockBe(page);

  const screens: [string, string][] = [
    ["/", copy.today.title],
    ["/todos/", copy.todos.title],
    ["/activity/", copy.activity.title],
    ["/memos/", copy.memos.title],
    ["/settings/", copy.settings.title],
    ["/checkin/?id=341", copy.loops.evening_checkin],
  ];
  for (const [path, title] of screens) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const violations = await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp);
    problems.push(...violations.map((v) => `${path}: securitypolicyviolation ${v}`));
  }
  // The chat sheet's chunk and its part too.
  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  await page.getByRole("textbox", { name: copy.chat.inputLabel }).fill("내일 치과 추가해 줘");
  await page.getByRole("button", { name: copy.chat.send }).click();
  await expect(page.getByText(copy.parts.draftHeading)).toBeVisible();
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).map((v) => `chat: securitypolicyviolation ${v}`));

  expect(problems).toEqual([]);
});

// The secretary's Markdown (its parser comes in its own chunk) draws a table, a code block and a
// link under the CSP, and raw HTML in it stays text.
test("markdown answer renders with no CSP violations", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (/content.security.policy|CSP/i.test(m.text())) problems.push(`console ${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __csp: string[] }).__csp = seen;
    document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI} at ${e.sourceFile}:${e.lineNumber}`));
  });
  await mockBe(page, { chat: [{ body: markdownSse() }] });
  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
  await expect(input).toBeEnabled();
  await input.fill("이번 주 정리해 줘");
  await page.getByRole("button", { name: copy.chat.send }).click();

  const answer = page.locator('[data-message="m-md"]');
  await expect(answer.locator("table td").first()).toHaveText("월");
  await expect(answer.locator("pre code")).toContainText("const week");
  await expect(answer.locator("strong").first()).toHaveText("이번 주 정리");
  await expect(answer.getByRole("link", { name: "달력" })).toHaveAttribute("rel", "noopener noreferrer");
  await expect(answer.getByRole("checkbox")).toHaveCount(2);
  await expect(answer.locator("img")).toHaveCount(0);
  await expect(answer).toContainText("<img src=x onerror=alert(1)>");
  // Aligned columns come as classes: no element in the answer carries a style attribute.
  await expect(answer.locator("[style]")).toHaveCount(0);
  const aligns = await answer.locator("tbody tr").first().locator("td").evaluateAll((tds) => tds.map((td) => getComputedStyle(td).textAlign));
  expect(aligns).toEqual(["center", "left", "right"]);
  // The table and the code block scroll inside the answer; the page itself does not.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  for (const sel of ["pre", "table"]) {
    const box = await answer.locator(sel).evaluate((el) => {
      const scroller = el.tagName === "PRE" ? el : el.parentElement!;
      return { overflow: getComputedStyle(scroller).overflowX, fits: scroller.getBoundingClientRect().right <= 390 };
    });
    expect(box, sel).toEqual({ overflow: "auto", fits: true });
  }
  await page.waitForLoadState("networkidle");
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).map((v) => `securitypolicyviolation ${v}`));
  expect(problems).toEqual([]);
  await page.screenshot({ path: "e2e/__screens__/chat-markdown.png" });
});

// Moving between tabs inside the app must keep each screen's styles: Next's pages router can carry
// a page's CSS as inline style tags on a client move, which style-src 'self' blocks.
test("screens keep their styles after moving between tabs", async ({ page }) => {
  const problems: string[] = [];
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __csp: string[] }).__csp = seen;
    document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await mockBe(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: copy.today.title })).toBeVisible();
  const tabs: [string, string][] = [
    [copy.tabs.todos, copy.todos.title],
    [copy.tabs.memos, copy.memos.title],
    [copy.tabs.settings, copy.settings.title],
    [copy.tabs.today, copy.today.title],
  ];
  for (const [tab, title] of tabs) {
    await page.getByRole("navigation").getByRole("link", { name: tab }).click();
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const position = await page.getByRole("navigation").evaluate((el) => getComputedStyle(el).position);
    if (position !== "fixed") problems.push(`${tab}: tab bar is ${position}, styles missing`);
    const list = await page.getByRole("navigation").locator("ul").evaluate((el) => getComputedStyle(el).display);
    if (list !== "flex") problems.push(`${tab}: tab list is ${list}`);
  }
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)));
  expect(problems).toEqual([]);
});

// DESIGN.md Typography: Pretendard Variable comes from this origin (font-src 'self'), only the
// subsets the screen's letters need. The weight of the first load is printed for the PR.
test("Pretendard loads from this origin on the first screen", async ({ page }) => {
  const fonts: string[] = [];
  page.on("requestfinished", (r) => {
    if (r.url().includes("/fonts/pretendard/")) fonts.push(r.url());
  });
  await mockBe(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: copy.today.title })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.fonts.check('700 34px "Pretendard Variable"', "오늘"))).toBe(true);
  const family = await page.getByRole("heading", { level: 1 }).evaluate((el) => getComputedStyle(el).fontFamily);
  expect(family).toMatch(/^"Pretendard Variable"/);
  expect(fonts.length).toBeGreaterThan(0);
  expect(fonts.every((u) => new URL(u).origin === new URL(page.url()).origin)).toBe(true);
  const bytes = await page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .filter((e) => e.name.includes("/fonts/pretendard/"))
      .reduce((n, e) => n + (e as PerformanceResourceTiming).encodedBodySize, 0),
  );
  console.log(`fonts on the first screen: ${fonts.length} files, ${(bytes / 1024).toFixed(1)} KB`);
});

import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { mockBe, seedConn } from "./routes";

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

import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { APP_ORIGIN, BE_URL, markdownSse, mockBe, seedConn } from "./routes";

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
  // SP10 7.3: photos are shown from blob: addresses (fetched with the key in the header).
  expect(csp).toContain("img-src 'self' data: blob:");
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

// SP6 13장 "CSP 실행": G-BE2's chat_gallery answer (every brain part in one answer) draws the four
// new cards from their primitives under the real CSP.
async function openGallery(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
  await expect(input).toBeEnabled();
  await input.fill("전부 보여 줘");
  await page.getByRole("button", { name: copy.chat.send }).click();
  await expect(page.getByText("꾸민 갤러리예요.")).toBeVisible();
}

test("SP6 cards render under CSP", async ({ page }) => {
  await mockBe(page, { chat: ["chat_gallery.sse"] });
  await openGallery(page);
  const log = page.getByRole("log");
  // ui_date_choice: a button per candidate date.
  await expect(log.getByRole("button", { name: "10월 28일 (수) 오전이 비어요" })).toBeVisible();
  await expect(log.getByRole("button", { name: "10월 29일 (목)" })).toBeVisible();
  // ui_result: the change pill.
  await expect(log.getByText(copy.parts.changeChip.moved, { exact: true })).toBeVisible();
  // ui_period_list: a day head of the week.
  await expect(log.getByText(copy.parts.dayHead(26, "월"), { exact: true })).toBeVisible();
  // ui_block: its title and its progress bar.
  await expect(log.getByRole("heading", { name: "이번 주 운동" })).toBeVisible();
  await expect(log.locator("progress").first()).toBeAttached();
  await expect(page.getByText(copy.parts.unknown)).toHaveCount(0);
});

test("SP6 gallery has no CSP violations", async ({ page }) => {
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
  await mockBe(page, { chat: ["chat_gallery.sse"] });
  await openGallery(page);
  await expect(page.getByRole("log").getByRole("heading", { name: "이번 주 운동" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).map((v) => `chat: securitypolicyviolation ${v}`));
  // Then Today and Todos, in the same page (a client move keeps the cards' stylesheet loaded).
  await page.keyboard.press("Escape");
  await expect(page.getByRole("log")).toHaveCount(0);
  for (const [tab, title] of [
    [copy.tabs.todos, copy.todos.title],
    [copy.tabs.today, copy.today.title],
  ] as const) {
    await page.getByRole("navigation").getByRole("link", { name: tab }).click();
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await page.waitForLoadState("networkidle");
  }
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).map((v) => `screens: securitypolicyviolation ${v}`));
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
  // SP9 9.2: the schedule tab's large title is the month it shows ("10월").
  const tabs: [string, string | RegExp][] = [
    [copy.tabs.todos, copy.todos.title],
    [copy.tabs.schedule, new RegExp(`^${copy.schedule.month(0).replace("0", "\\d+")}$`)],
    [copy.tabs.memos, copy.memos.title],
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

// SP10 12장 (Playwright): with the fixture BE, a photo picked in a new memo is shrunk in the real
// browser, joins the photo row (a blob: image under img-src blob:), and the save request carries
// photo_ids. 16장: it is not read on its own; the viewer's "글자 읽기" puts its text into the body.
// No CSP violation on the way.
test("memo photo: pick, row, create_memo has photo_ids, 글자 읽기 puts the text in, under CSP", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __csp: string[] }).__csp = seen;
    document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await mockBe(page);
  const uploads: string[] = [];
  let reads = 0;
  const actions: { action: string; args: Record<string, unknown> }[] = [];
  const headers = {
    "Access-Control-Allow-Origin": APP_ORIGIN,
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
    "content-type": "application/json",
  };
  // Registered after mockBe, so these answer first; anything else falls back to it.
  await page.route(`${BE_URL}/api/v1/**`, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace(/^\/api\/v1/, "");
    if (req.method() === "POST" && path === "/photos") {
      uploads.push(req.headers()["content-type"] ?? "");
      const body = req.postDataBuffer()?.toString("latin1") ?? "";
      for (const part of ["image", "thumb", "origin", "client_msg_id"]) if (!body.includes(`name="${part}"`)) uploads.push(`missing ${part}`);
      if (!/name="image"; filename="[^"]*"\r\nContent-Type: image\/jpeg/.test(body)) uploads.push("image not jpeg");
      return route.fulfill({ status: 201, headers, body: JSON.stringify({ id: 12, width: 2048, height: 1365, bytes: 1000 }) });
    }
    if (req.method() === "POST" && path === "/photos/12/read") {
      reads++;
      return route.fulfill({ status: 200, headers, body: JSON.stringify({ text: "사진 속 글", unreadable: false }) });
    }
    if (req.method() === "POST" && path === "/actions") {
      const b = req.postDataJSON() as { action: string; args: Record<string, unknown> };
      actions.push({ action: b.action, args: b.args });
      const result = { id: 7, title: "책 메모", area: null, pinned: false, updated_at: "2026-10-24T05:00:00Z" };
      return route.fulfill({ status: 200, headers, body: JSON.stringify({ status: "applied", activity_id: 900, undo_id: 900, result, confirmation: copy.photos.created("책 메모", 1) }) });
    }
    return route.fallback();
  });

  await page.goto("/memos/view/?new=1");
  const box = page.getByRole("textbox", { name: copy.memos.body });
  await expect(box).toBeVisible();
  await box.fill("책 메모");
  // A 3000x2000 photo drawn in the page (as a phone photo would be, larger than 2,048).
  const png = await page.evaluate(() => {
    const c = document.createElement("canvas");
    c.width = 3000;
    c.height = 2000;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#88aa66";
    ctx.fillRect(0, 0, 3000, 2000);
    return c.toDataURL("image/png").split(",")[1];
  });
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: copy.photos.button }).click();
  await (await chooser).setFiles({ name: "IMG_0001.png", mimeType: "image/png", buffer: Buffer.from(png, "base64") });

  const strip = page.getByRole("list", { name: copy.photos.strip });
  const img = strip.locator("img");
  await expect(img).toHaveAttribute("src", /^blob:/);
  await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await expect.poll(() => actions.find((a) => a.action === "create_memo")?.args, { timeout: 5000 }).toEqual({ body: "책 메모", photo_ids: [12] });
  expect(reads).toBe(0);
  await expect(box).toHaveValue("책 메모");
  // The viewer's 글자 읽기: it closes, and the text goes in at the caret (the end) and is saved.
  await strip.getByRole("button").first().click();
  const viewer = page.getByRole("dialog", { name: copy.photos.viewer });
  await viewer.getByRole("button", { name: copy.photos.readText }).click();
  await expect(viewer).toHaveCount(0);
  await expect(box).toHaveValue("책 메모\n사진 속 글");
  await expect(page.getByText(copy.photos.inserted)).toBeVisible();
  await expect.poll(() => actions.find((a) => a.action === "update_memo")?.args.body, { timeout: 5000 }).toBe("책 메모\n사진 속 글");
  expect(reads).toBe(1);
  expect(uploads).toHaveLength(1);
  expect(uploads[0]).toMatch(/^multipart\/form-data; boundary=/);
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).map((v) => `securitypolicyviolation ${v}`));
  expect(problems).toEqual([]);
});

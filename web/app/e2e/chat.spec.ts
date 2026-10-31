import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { APP_ORIGIN, BE_URL, markdownSse, mockBe, seedConn } from "./routes";

// The chat input's buttons in the built app (CSP on): the stop button while an answer is slow to come.
test("stop: the send button stops a slow answer, asks the BE, and the field is usable again", async ({ page }) => {
  await seedConn(page);
  const be = await mockBe(page, { chatHangs: true });
  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
  await expect(input).toBeEnabled();
  // The × in the field empties it and keeps the focus there.
  await input.fill("지울 글");
  await page.getByRole("button", { name: copy.chat.clearInput }).click();
  await expect(input).toHaveValue("");
  await expect(input).toBeFocused();
  await expect(page.getByRole("button", { name: copy.chat.clearInput })).toHaveCount(0);
  await input.fill("길게 말해 줘");
  await page.getByRole("button", { name: copy.chat.send }).click();
  const stop = page.getByRole("button", { name: copy.chat.stop });
  await expect(stop).toBeEnabled();
  await expect(input).toHaveValue("");
  await page.waitForTimeout(700); // past the guard against a double tap on send
  await stop.click();
  await expect(page.getByText(copy.chat.stopped)).toBeVisible();
  await expect.poll(() => be.stopBodies).toEqual([{ client_msg_id: (be.chatBodies[0] as { client_msg_id: string }).client_msg_id }]);
  await expect(page.getByText(copy.chat.notReceived)).toHaveCount(0);
  await expect(stop).toHaveCount(0);
  await input.fill("다음");
  await expect(page.getByRole("button", { name: copy.chat.send })).toBeEnabled();
  expect(be.chatBodies).toHaveLength(1); // the stop is not a cut: nothing is sent again
});

// SP10 7.5 in the built app (CSP on): photos picked from the library wait in the tray, are shrunk in
// the page, go up as JPEG (origin chat) one by one, and the message carries data-photo parts after
// the text; my bubble shows them from blob: addresses.
test("chat photos: pick two, tray, send uploads in order and sends data-photo parts, bubble grid, under CSP", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __csp: string[] }).__csp = seen;
    document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await seedConn(page);
  const be = await mockBe(page, { chat: [{ body: markdownSse("받았어요") }] });
  const uploads: string[] = [];
  let nextId = 12;
  const headers = {
    "Access-Control-Allow-Origin": APP_ORIGIN,
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
    "content-type": "application/json",
  };
  // Registered after mockBe, so this answers first; anything else falls back to it.
  await page.route(`${BE_URL}/api/v1/**`, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace(/^\/api\/v1/, "");
    if (req.method() === "POST" && path === "/photos") {
      const body = req.postDataBuffer()?.toString("latin1") ?? "";
      if (!/name="image"; filename="[^"]*"\r\nContent-Type: image\/jpeg/.test(body)) uploads.push("image not jpeg");
      uploads.push(/name="origin"\r\n\r\n(\w+)/.exec(body)?.[1] ?? "no origin");
      return route.fulfill({ status: 201, headers, body: JSON.stringify({ id: nextId++, width: 2048, height: 1365, bytes: 1000 }) });
    }
    return route.fallback();
  });

  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
  await expect(input).toBeEnabled();
  await expect(page.getByRole("button", { name: copy.chat.attach })).toBeVisible();
  // Two photos drawn in the page, larger than 2,048 (as a phone's would be).
  const png = await page.evaluate(() => {
    const c = document.createElement("canvas");
    c.width = 3000;
    c.height = 2000;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#88aa66";
    ctx.fillRect(0, 0, 3000, 2000);
    return c.toDataURL("image/png").split(",")[1];
  });
  const file = (name: string) => ({ name, mimeType: "image/png", buffer: Buffer.from(png, "base64") });
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: copy.chat.attach }).click();
  await page.getByRole("menuitem", { name: copy.photos.button }).click();
  const fc = await chooser;
  expect(fc.isMultiple()).toBe(true);
  await fc.setFiles([file("IMG_0001.png"), file("IMG_0002.png")]);
  const tray = page.getByRole("list", { name: copy.chat.tray });
  await expect(tray.locator("img")).toHaveCount(2);
  await expect.poll(() => tray.locator("img").first().evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await input.fill("영수증 두 장");
  await page.getByRole("button", { name: copy.chat.send }).click();
  await expect(page.getByText("받았어요")).toBeVisible();
  expect(uploads).toEqual(["chat", "chat"]);
  const sent = be.chatBodies[0] as { message: { parts: unknown[] } };
  expect(sent.message.parts).toEqual([
    { type: "text", text: "영수증 두 장" },
    { type: "data-photo", data: { photo_id: 12 } },
    { type: "data-photo", data: { photo_id: 13 } },
  ]);
  await expect(tray).toHaveCount(0);
  const grid = page.getByRole("list", { name: copy.photos.strip });
  await expect(grid.locator("img")).toHaveCount(2);
  await expect(grid.locator("img").first()).toHaveAttribute("src", /^blob:/);
  await expect.poll(() => grid.locator("img").first().evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).map((v) => `securitypolicyviolation ${v}`));
  expect(problems).toEqual([]);
});

// SP10 16장 in the built app (CSP on): a photo alone makes a photo memo (the answer's data-photo-memo);
// "글자 읽기" goes first in the chip row, reads the photo into the memo with update_memo, toasts, and
// goes. Nothing more is sent to /chat.
test("chat 글자 읽기: a photo alone, then the chip reads it into the memo, under CSP", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __csp: string[] }).__csp = seen;
    document.addEventListener("securitypolicyviolation", (e) => seen.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  await seedConn(page);
  const ev = (o: unknown) => `data: ${JSON.stringify(o)}\n\n`;
  const photoMemo = [
    ev({ type: "start", messageId: "m-pm", messageMetadata: { conversation_id: 1, channel: "app", kind: "chat", checkin_id: null } }),
    ev({ type: "start-step" }),
    ev({ type: "finish-step" }),
    ev({ type: "data-photo-memo", data: { memo_id: 40, photo_ids: [12] } }),
    ev({ type: "data-activity", data: { activity_ids: [70], undo_ids: [70], confirmation: copy.photos.created("사진", 1) } }),
    ev({ type: "finish", messageMetadata: { conversation_id: 1, channel: "app", kind: "chat" } }),
    "data: [DONE]\n\n",
  ].join("");
  const be = await mockBe(page, { chat: [{ body: photoMemo }] });
  const headers = {
    "Access-Control-Allow-Origin": APP_ORIGIN,
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
    "content-type": "application/json",
  };
  const reads: string[] = [];
  const actions: { action: string; args: Record<string, unknown> }[] = [];
  await page.route(`${BE_URL}/api/v1/**`, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace(/^\/api\/v1/, "");
    if (req.method() === "POST" && path === "/photos") {
      return route.fulfill({ status: 201, headers, body: JSON.stringify({ id: 12, width: 2048, height: 1365, bytes: 1000 }) });
    }
    if (req.method() === "POST" && path === "/photos/12/read") {
      reads.push(path);
      return route.fulfill({ status: 200, headers, body: JSON.stringify({ text: "영수증 글", unreadable: false }) });
    }
    if (req.method() === "GET" && path === "/memos/40") {
      const memo = { id: 40, title: "사진", body: "사진", area: null, pinned: false, origin: "user", created_at: "2026-10-31T01:00:00Z", updated_at: "2026-10-31T01:00:00Z", photos: [{ id: 12, width: 2048, height: 1365 }] };
      return route.fulfill({ status: 200, headers, body: JSON.stringify(memo) });
    }
    if (req.method() === "POST" && path === "/actions") {
      const b = req.postDataJSON() as { action: string; args: Record<string, unknown> };
      actions.push({ action: b.action, args: b.args });
      const result = { id: 40, title: "영수증 글", area: null, pinned: false, updated_at: "2026-10-31T01:05:00Z" };
      return route.fulfill({ status: 200, headers, body: JSON.stringify({ status: "applied", activity_id: 901, undo_id: null, result, confirmation: copy.memos.confirm.updated("영수증 글") }) });
    }
    return route.fallback();
  });

  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  await expect(page.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled();
  const png = await page.evaluate(() => {
    const c = document.createElement("canvas");
    c.width = 800;
    c.height = 600;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "#88aa66";
    ctx.fillRect(0, 0, 800, 600);
    return c.toDataURL("image/png").split(",")[1];
  });
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: copy.chat.attach }).click();
  await page.getByRole("menuitem", { name: copy.photos.button }).click();
  await (await chooser).setFiles({ name: "IMG_0001.png", mimeType: "image/png", buffer: Buffer.from(png, "base64") });
  await expect(page.getByRole("list", { name: copy.chat.tray }).locator("img")).toHaveCount(1);
  await page.getByRole("button", { name: copy.chat.send }).click();
  const chips = page.getByRole("group", { name: copy.chat.chipsLabel });
  const chip = chips.getByRole("button", { name: copy.chat.readChip });
  await expect(chip).toBeVisible();
  await expect(chips.getByRole("button").first()).toHaveText(copy.chat.readChip);
  await chip.click();
  await expect(page.getByText(copy.photos.readInto("영수증 글"))).toBeVisible();
  await expect(chip).toHaveCount(0);
  expect(reads).toHaveLength(1);
  expect(actions).toEqual([{ action: "update_memo", args: { id: 40, body: "영수증 글", updated_at: "2026-10-31T01:00:00Z" } }]);
  expect(be.chatBodies).toHaveLength(1);
  problems.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).map((v) => `securitypolicyviolation ${v}`));
  expect(problems).toEqual([]);
});

// A message held down in the built app (CSP on): the "복사" menu opens over it, one tap copies the
// text the reader sees, the toast says so. Mine and the secretary's alike.
test("hold to copy: my bubble and the secretary's answer", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: "http://127.0.0.1:4173" });
  await seedConn(page);
  await mockBe(page, { chat: [{ body: markdownSse("**내일 9시**에 치과 예약을 넣었어요.") }] });
  await page.goto("/");
  await page.getByRole("button", { name: copy.chat.launcher }).click();
  const input = page.getByRole("textbox", { name: copy.chat.inputLabel });
  await input.fill("내일 9시 치과 예약 넣어 줘");
  await page.getByRole("button", { name: copy.chat.send }).click();
  const answer = page.getByText("에 치과 예약을 넣었어요.");
  await expect(answer).toBeVisible();

  // A finger held down: pointer events of a touch, past HOLD_MS (a mouse opens it by right-click).
  const holdOn = async (text: string) => {
    const target = page.getByText(text);
    const box = (await target.boundingBox())!;
    const at = { pointerType: "touch", button: 0, clientX: box.x + 8, clientY: box.y + box.height / 2, bubbles: true };
    await target.dispatchEvent("pointerdown", at);
    await page.waitForTimeout(600);
    await target.dispatchEvent("pointerup", at);
  };

  await holdOn("내일 9시 치과 예약 넣어 줘");
  const item = page.getByRole("menuitem", { name: copy.chat.copy });
  await expect(item).toBeVisible();
  if (process.env.COPY_SHOTS) await page.screenshot({ path: `${process.env.COPY_SHOTS}/hold-mine.png` });
  await item.click();
  await expect(page.getByText(copy.chat.copied)).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("내일 9시 치과 예약 넣어 줘");

  await page.getByText("에 치과 예약을 넣었어요.").click({ button: "right" });
  await expect(item).toBeVisible();
  if (process.env.COPY_SHOTS) await page.screenshot({ path: `${process.env.COPY_SHOTS}/hold-theirs.png` });
  await item.click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("내일 9시에 치과 예약을 넣었어요.");
  await expect(item).toHaveCount(0);
});

import { expect, test } from "@playwright/test";
import { copy } from "../src/lib/copy";
import { mockBe, seedConn } from "./routes";

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

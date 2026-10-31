import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { clearPhotoCache, peekPhoto, photoCacheSize, photoKey } from "../lib/photoCache";
import { PhotoUnopenable, shrinkPhoto } from "../lib/shrinkPhoto";
import { gatedResponse, type HistoryItem, serveChat, serveHistory, sse, sseResponse } from "../test/chat";
import todayJson from "../test/fixtures/today.json";
import { renderWithProviders, TEST_BE_URL } from "../test/render";
import { BASE, server } from "../test/server";
import { ChatSheet } from "./ChatSheet";
import { sheetState } from "./sheetContext";

// SP10 12장 앱 (채팅 쪽, 7.5): 사진 대기·4장 상한·사진만 보내기·올리기 실패 시 안 보냄·보낸 `parts`에
// `data-photo`, 카메라는 바로 보냄, 다시 연 대화의 말풍선 사진, 8장 응답→문구(채팅 자리).
// jsdom has no image decoder: shrinkPhoto (its own tests fake the bitmap) stands in here.
vi.mock("../lib/shrinkPhoto", async (orig) => {
  const real = await orig<typeof import("../lib/shrinkPhoto")>();
  return {
    ...real,
    shrinkPhoto: vi.fn(async () => ({
      image: new Blob([new Uint8Array(300)], { type: "image/jpeg" }),
      thumb: new Blob([new Uint8Array(30)], { type: "image/jpeg" }),
    })),
  };
});

beforeEach(() => {
  clearPhotoCache();
  server.use(http.get(`${BASE}/today`, () => HttpResponse.json(todayJson)));
});

afterEach(async () => {
  vi.mocked(shrinkPhoto).mockClear();
  await clear();
});

const answer = (messageId: string, conversationId: number, text: string) =>
  sse([
    { type: "start", messageId, messageMetadata: { conversation_id: conversationId, channel: "app", kind: "chat", checkin_id: null } },
    { type: "start-step" },
    { type: "text-start", id: "t1" },
    { type: "text-delta", id: "t1", delta: text },
    { type: "text-end", id: "t1" },
    { type: "finish-step" },
    { type: "finish", messageMetadata: { conversation_id: conversationId, channel: "app", kind: "chat" } },
    "[DONE]",
  ]);

/** Part name → its text, or "file <type>" for a file part (as api/photos.test.ts reads them). */
function multipart(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  const CRLF = "\r\n";
  const boundary = body.slice(0, body.indexOf(CRLF));
  for (const chunk of body.split(boundary)) {
    const [head, ...rest] = chunk.split(CRLF + CRLF);
    const name = head.match(/name="([^"]+)"/)?.[1];
    if (!name) continue;
    const type = head.match(/Content-Type: (\S+)/i)?.[1];
    const text = rest.join(CRLF + CRLF);
    out[name] = /filename=/.test(head) ? `file ${type}` : text.endsWith(CRLF) ? text.slice(0, -2) : text;
  }
  return out;
}

interface Upload {
  origin: string;
  clientMsgId: string;
  hasImage: boolean;
  hasThumb: boolean;
}

/** POST /photos (ids from 12, or the given answers in turn) and GET /photos/{id}. */
function photoBe(opts: { upload?: (n: number) => Response | Promise<Response> | undefined } = {}) {
  const uploads: Upload[] = [];
  const gets: string[] = [];
  let nextId = 12;
  server.use(
    http.post(`${BASE}/photos`, async ({ request }) => {
      const form = multipart(await request.text());
      uploads.push({ origin: form.origin, clientMsgId: form.client_msg_id, hasImage: form.image === "file image/jpeg", hasThumb: form.thumb === "file image/jpeg" });
      const custom = await opts.upload?.(uploads.length);
      if (custom) return custom;
      return HttpResponse.json({ id: nextId++, width: 2048, height: 1536, bytes: 300 }, { status: 201 });
    }),
    http.get(`${BASE}/photos/:id`, ({ request, params }) => {
      gets.push(`${params.id}:${new URL(request.url).searchParams.get("size")}`);
      return new HttpResponse(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), { headers: { "Content-Type": "image/jpeg" } });
    }),
  );
  return { uploads, gets };
}

const picture = (n = 1) => new File([new Uint8Array(50)], `IMG_000${n}.jpg`, { type: "image/jpeg" });
const pickerInput = () => document.querySelector('input[type="file"][multiple]') as HTMLInputElement;
const cameraInput = () => document.querySelector('input[type="file"][capture]') as HTMLInputElement;
type Body = { client_msg_id: string; message: { id: string; parts: unknown[]; metadata?: Record<string, unknown> } };

async function openSheet(props: Partial<Parameters<typeof ChatSheet>[0]> = {}) {
  const user = userEvent.setup();
  renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} {...props} />);
  const input = await screen.findByRole("textbox", { name: copy.chat.inputLabel });
  await waitFor(() => expect(input).toBeEnabled());
  return { user, input };
}

/** Opens the (+) menu and gives its item `name` (copy.chat.camera or copy.photos.button). */
async function menuItem(user: ReturnType<typeof userEvent.setup>, name: string) {
  const plus = screen.getByRole("button", { name: copy.chat.attach });
  if (plus.getAttribute("aria-expanded") !== "true") await user.click(plus);
  return screen.getByRole("menuitem", { name });
}

/** Presses (+) → "사진" and picks `files` from the library. */
async function pick(user: ReturnType<typeof userEvent.setup>, files: File[]) {
  await user.click(await menuItem(user, copy.photos.button));
  await user.upload(pickerInput(), files);
}

const tray = () => screen.queryByRole("list", { name: copy.chat.tray });

describe("ChatSheet photos (SP10 7.5)", () => {
  it("a (+) at the field's leading edge opens a menu: 카메라 opens the camera only, 사진 the library with many; no in-app camera", async () => {
    const media = vi.fn();
    vi.stubGlobal("navigator", Object.assign(Object.create(navigator), { mediaDevices: { getUserMedia: media } }));
    const { user } = await openSheet();
    const plus = screen.getByRole("button", { name: copy.chat.attach });
    expect(plus).toHaveAttribute("aria-haspopup", "menu");
    expect(plus).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();
    // Inside the field's box, before the text.
    const field = screen.getByRole("textbox", { name: copy.chat.inputLabel });
    expect(plus.parentElement!.parentElement).toBe(field.parentElement);
    expect(plus.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const camera = await menuItem(user, copy.chat.camera);
    const photos = screen.getByRole("menuitem", { name: copy.photos.button });
    expect(plus).toHaveAttribute("aria-expanded", "true");
    expect(within(screen.getByRole("menu", { name: copy.chat.attach })).getAllByRole("menuitem")).toEqual([camera, photos]);
    expect(camera.querySelector("svg")).not.toBeNull();
    expect(photos.querySelector("svg")).not.toBeNull();
    expect(cameraInput()).toHaveAttribute("capture", "environment");
    expect(cameraInput()).toHaveAttribute("accept", "image/*");
    expect(cameraInput()).not.toHaveAttribute("multiple");
    expect(pickerInput()).toHaveAttribute("accept", "image/*");
    expect(pickerInput()).not.toHaveAttribute("capture");
    expect(document.querySelector("video")).toBeNull();
    expect(media).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("picked photos wait in the tray with ✕; send uploads them in order (origin chat) and sends text then data-photo parts", async () => {
    const be = photoBe();
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "받았어요")));
    const { user, input } = await openSheet();
    await pick(user, [picture(1), picture(2), picture(3)]);
    const t = await screen.findByRole("list", { name: copy.chat.tray });
    expect(within(t).getAllByRole("listitem")).toHaveLength(3);
    const thumbs = [...t.querySelectorAll("img")];
    expect(thumbs).toHaveLength(3);
    expect(thumbs.every((i) => i.getAttribute("src")?.startsWith("blob:"))).toBe(true);
    // ✕ takes the second one out.
    await user.click(within(t).getByRole("button", { name: copy.chat.unpick(2, 3) }));
    expect(within(t).getAllByRole("listitem")).toHaveLength(2);
    // Nothing goes until send is pressed.
    expect(be.uploads).toHaveLength(0);
    await user.type(input, "영수증");
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(be.uploads.map((u) => u.origin)).toEqual(["chat", "chat"]);
    expect(be.uploads.every((u) => u.hasImage && u.hasThumb)).toBe(true);
    expect(new Set(be.uploads.map((u) => u.clientMsgId)).size).toBe(2);
    const body = bodies[0] as unknown as Body;
    expect(body.message.parts).toEqual([
      { type: "text", text: "영수증" },
      { type: "data-photo", data: { photo_id: 12 } },
      { type: "data-photo", data: { photo_id: 13 } },
    ]);
    // The SP9 metadata rules stay: a new conversation, no check-in.
    expect(body.message.metadata).toEqual({ at: expect.any(String) });
    expect(await screen.findByText("받았어요")).toBeInTheDocument();
    expect(tray()).toBeNull();
    expect(input).toHaveValue("");
    // My bubble: the text and a grid of the two photos, from the bytes just sent (no GET).
    const mine = screen.getByText("영수증").closest("[data-message]") as HTMLElement;
    const grid = within(mine).getByRole("list", { name: copy.photos.strip });
    const imgs = within(grid).getAllByRole("button");
    expect(imgs).toHaveLength(2);
    await waitFor(() => expect(imgs.map((b) => b.querySelector("img")?.getAttribute("src") ?? "")).toEqual([expect.stringMatching(/^blob:/), expect.stringMatching(/^blob:/)]));
    expect(be.gets).toEqual([]);
  });

  it("photos only: send is ready with an empty field, and the message is data-photo parts alone", async () => {
    photoBe();
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "메모로 남겼어요")));
    const { user } = await openSheet();
    expect(screen.getByRole("button", { name: copy.chat.send })).toBeDisabled();
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    const send = screen.getByRole("button", { name: copy.chat.send });
    expect(send).toBeEnabled();
    await user.click(send);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0] as unknown as Body).message.parts).toEqual([{ type: "data-photo", data: { photo_id: 12 } }]);
    expect(await screen.findByText("메모로 남겼어요")).toBeInTheDocument();
  });

  it("Enter in the empty field sends the waiting photos too", async () => {
    photoBe();
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "네")));
    const { user, input } = await openSheet();
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(input);
    await user.keyboard("{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(1));
  });

  it("at most 4 wait: a fifth is not taken, with the 4장 sentence; 사진 is dimmed at 4 and says so", async () => {
    photoBe();
    const { user } = await openSheet();
    await pick(user, [picture(1), picture(2), picture(3), picture(4), picture(5)]);
    const t = await screen.findByRole("list", { name: copy.chat.tray });
    expect(within(t).getAllByRole("listitem")).toHaveLength(4);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.sendLimit));
    const button = await menuItem(user, copy.photos.button);
    expect(button).toHaveAttribute("aria-disabled", "true");
    vi.mocked(shrinkPhoto).mockClear();
    await user.click(button);
    expect(screen.getByRole("status")).toHaveTextContent(copy.photos.sendLimit);
    expect(within(t).getAllByRole("listitem")).toHaveLength(4);
    expect(shrinkPhoto).not.toHaveBeenCalled();
  });

  it("an upload that fails sends nothing: the tray and the text stay, with the failure sentence; the next send uploads again with new ids", async () => {
    const be = photoBe({ upload: (n) => (n === 2 ? HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) : undefined) });
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "받았어요")));
    const { user, input } = await openSheet();
    await pick(user, [picture(1), picture(2)]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.type(input, "둘");
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.uploadFailed));
    expect(bodies).toHaveLength(0);
    expect(within(tray()!).getAllByRole("listitem")).toHaveLength(2);
    expect(input).toHaveValue("둘");
    expect(screen.queryByText("둘", { selector: "p" })).toBeNull(); // no bubble
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(be.uploads).toHaveLength(4);
    expect(new Set(be.uploads.map((u) => u.clientMsgId)).size).toBe(4);
    expect((bodies[0] as unknown as Body).message.parts).toEqual([
      { type: "text", text: "둘" },
      { type: "data-photo", data: { photo_id: 13 } },
      { type: "data-photo", data: { photo_id: 14 } },
    ]);
  });

  it.each([
    [413, "photo_too_large", copy.photos.tooLarge],
    [415, "photo_not_jpeg", copy.photos.cannotOpen],
    [422, "photo_unreadable", copy.photos.cannotOpen],
    [429, "photo_limit", copy.photos.dailyLimit],
    [507, "disk_full", copy.photos.diskFull],
  ])("upload %i %s → its sentence (8장), nothing sent", async (status, code, text) => {
    photoBe({ upload: () => HttpResponse.json({ error: { code, message: "x" } }, { status }) });
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "x")));
    const { user } = await openSheet();
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(text));
    expect(bodies).toHaveLength(0);
    expect(tray()).not.toBeNull();
  });

  it("a photo that cannot be opened (the app's shrink) is not taken: 열 수 없어요", async () => {
    photoBe();
    vi.mocked(shrinkPhoto).mockRejectedValueOnce(new PhotoUnopenable());
    const { user } = await openSheet();
    await pick(user, [picture()]);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.cannotOpen));
    expect(tray()).toBeNull();
  });

  it("카메라: the photo taken goes at once with the text written, without the tray", async () => {
    const be = photoBe();
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "받았어요")));
    const { user, input } = await openSheet();
    await user.type(input, "칠판");
    await user.click(await menuItem(user, copy.chat.camera));
    await user.upload(cameraInput(), picture());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(be.uploads.map((u) => u.origin)).toEqual(["chat"]);
    expect((bodies[0] as unknown as Body).message.parts).toEqual([
      { type: "text", text: "칠판" },
      { type: "data-photo", data: { photo_id: 12 } },
    ]);
    expect(tray()).toBeNull();
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("카메라 with an empty field sends the photo alone", async () => {
    photoBe();
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "메모로 남겼어요")));
    const { user } = await openSheet();
    await user.upload(cameraInput(), picture());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0] as unknown as Body).message.parts).toEqual([{ type: "data-photo", data: { photo_id: 12 } }]);
  });

  it("카메라 whose upload fails leaves the photo in the tray with the failure sentence; send then sends it", async () => {
    const be = photoBe({ upload: (n) => (n === 1 ? HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 }) : undefined) });
    const bodies = serveChat(() => sseResponse(answer("m-1", 5, "받았어요")));
    const { user } = await openSheet();
    await user.upload(cameraInput(), picture());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(copy.photos.uploadFailed));
    expect(bodies).toHaveLength(0);
    expect(within(tray()!).getAllByRole("listitem")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(be.uploads).toHaveLength(2);
    expect((bodies[0] as unknown as Body).message.parts).toEqual([{ type: "data-photo", data: { photo_id: 12 } }]);
  });

  it.each([
    [400, "photo_not_found", copy.photos.uploadFailed],
    [422, "too_many_photos", copy.photos.sendLimit],
  ])("chat %i %s → its sentence (8장); the photos go back to the tray", async (status, code, text) => {
    photoBe();
    const bodies = serveChat(() => HttpResponse.json({ error: { code, message: text } }, { status }));
    const { user } = await openSheet();
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(await screen.findByText(text, { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByText(copy.chat.notReceived)).toBeNull();
    expect(within(tray()!).getAllByRole("listitem")).toHaveLength(1);
  });

  it("a reopened conversation draws my photos from /messages `photos` (no marks parsed), and a press shows it big", async () => {
    const be = photoBe();
    const items: HistoryItem[] = [
      { id: "u-5-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "", photos: [{ id: 31, width: 2048, height: 1536 }] },
      { id: "m-5-1", at: "2026-10-24T01:00:05Z", speaker: "secretary", text: "메모로 남겼어요" },
      { id: "u-5-2", at: "2026-10-24T01:01:00Z", speaker: "user", text: "이것도", photos: [{ id: 32, width: 10, height: 10 }, { id: 33, width: 10, height: 10 }] },
      { id: "u-5-3", at: "2026-10-24T01:02:00Z", speaker: "user", text: "[사진 #40] 그냥 글" },
    ];
    serveHistory({ conversations: [{ id: 5, last_message_at: "2026-10-24T01:02:00Z" }], messages: { 5: items } });
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText("메모로 남겼어요")).toBeInTheDocument();
    const first = document.querySelector('[data-message="u-5-1"]') as HTMLElement;
    expect(within(first).getAllByRole("button")).toHaveLength(1);
    // A photo-only line has no empty bubble.
    expect(first.querySelector("p")).toBeNull();
    const second = document.querySelector('[data-message="u-5-2"]') as HTMLElement;
    expect(within(second).getByText("이것도")).toBeInTheDocument();
    expect(within(second).getAllByRole("button")).toHaveLength(2);
    // A typed mark is text, never a photo.
    const third = document.querySelector('[data-message="u-5-3"]') as HTMLElement;
    expect(within(third).getByText("[사진 #40] 그냥 글")).toBeInTheDocument();
    expect(within(third).queryAllByRole("button")).toHaveLength(0);
    await waitFor(() => expect(be.gets.sort()).toEqual(["31:thumb", "32:thumb", "33:thumb"]));
    await user.click(within(second).getByRole("button", { name: copy.photos.photo(2, 2) }));
    const viewer = await screen.findByRole("dialog", { name: copy.photos.viewer });
    await waitFor(() => expect(be.gets).toContain("33:full"));
    // Only to look at: no "메모에서 빼기" in the chat, and no "글자 읽기" (the chip does that, 16장).
    expect(within(viewer).queryByRole("button", { name: copy.photos.detach })).toBeNull();
    expect(within(viewer).queryByRole("button", { name: copy.photos.readText })).toBeNull();
  });

  it("Escape closes the photo shown big, not the sheet under it", async () => {
    photoBe();
    serveHistory({
      conversations: [{ id: 5, last_message_at: "2026-10-24T01:00:00Z" }],
      messages: { 5: [{ id: "u-5-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "", photos: [{ id: 31, width: 10, height: 10 }] }] },
    });
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={onClose} />);
    await user.click(await screen.findByRole("button", { name: copy.photos.photo(1, 1) }));
    await screen.findByRole("dialog", { name: copy.photos.viewer });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: copy.photos.viewer })).toBeNull());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("offline: the (+) is off and no tray is taken", async () => {
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { conn: "offline" });
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.attach })).toBeDisabled());
  });

  it("the check-in screen's box has no photo buttons", async () => {
    renderWithProviders(<ChatSheet open embedded onClose={() => {}} conversationId={null} checkinId={341} />);
    await screen.findByRole("textbox", { name: copy.chat.inputLabel });
    expect(screen.queryByRole("button", { name: copy.chat.attach })).toBeNull();
  });
});

describe("ChatSheet (+) menu", () => {
  it("Escape closes the menu alone (not the sheet) and gives the focus back to the (+); arrows move between items", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={onClose} conversationId={null} />);
    const input = await screen.findByRole("textbox", { name: copy.chat.inputLabel });
    await waitFor(() => expect(input).toBeEnabled());
    const plus = screen.getByRole("button", { name: copy.chat.attach });
    plus.focus();
    await user.keyboard("{Enter}");
    const menu = screen.getByRole("menu");
    expect(plus).toHaveAttribute("aria-controls", menu.id);
    const [camera, photos] = within(menu).getAllByRole("menuitem");
    expect(camera).toHaveFocus();
    expect(camera).toHaveAttribute("tabindex", "-1");
    await user.keyboard("{ArrowDown}");
    expect(photos).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(camera).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(photos).toHaveFocus();
    await user.keyboard("{Home}");
    expect(camera).toHaveFocus();
    await user.keyboard("{End}");
    expect(photos).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(plus).toHaveFocus();
    expect(plus).toHaveAttribute("aria-expanded", "false");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a tap leaves the focus in the field; choosing from the keyboard gives it back to the (+)", async () => {
    photoBe();
    const { user, input } = await openSheet();
    await user.click(input);
    const plus = screen.getByRole("button", { name: copy.chat.attach });
    await user.click(plus);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(input).toHaveFocus();
    await user.click(plus);
    plus.focus();
    await user.keyboard("{Enter}");
    await user.keyboard("{ArrowDown}{Enter}"); // 사진
    expect(screen.queryByRole("menu")).toBeNull();
    expect(plus).toHaveFocus();
  });

  it("a press outside or a second press on (+) closes it; choosing an item closes it", async () => {
    photoBe();
    const { user, input } = await openSheet();
    const plus = screen.getByRole("button", { name: copy.chat.attach });
    await user.click(plus);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.click(plus);
    expect(screen.queryByRole("menu")).toBeNull();
    await user.click(plus);
    await user.click(input);
    expect(screen.queryByRole("menu")).toBeNull();
    await pick(user, [picture()]);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

// PH-07 fix round 1: the camera never loses a photo unseen, blob: addresses are let go (12장),
// the SP9 metadata stays with photos, a refused message's photos still open, Tab stays in the viewer.
describe("ChatSheet photos, fix round 1", () => {
  const pressCamera = async (user: ReturnType<typeof userEvent.setup>) => user.click(await menuItem(user, copy.chat.camera));

  it("카메라 with 4 waiting: dimmed, says the 4장 sentence, the camera does not open, and a late photo is not taken unseen", async () => {
    const be = photoBe();
    const { user } = await openSheet();
    await pick(user, [picture(1), picture(2), picture(3), picture(4)]);
    await waitFor(() => expect(within(tray()!).getAllByRole("listitem")).toHaveLength(4));
    const camera = await menuItem(user, copy.chat.camera);
    expect(camera).toHaveAttribute("aria-disabled", "true");
    const opened = vi.spyOn(cameraInput(), "click");
    await pressCamera(user);
    expect(opened).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(copy.photos.sendLimit);
    // A photo that comes back from a camera opened before the tray filled: said so, not sent, not lost unseen.
    await user.upload(cameraInput(), picture(5));
    expect(screen.getByRole("status")).toHaveTextContent(copy.photos.sendLimit);
    expect(be.uploads).toHaveLength(0);
    expect(within(tray()!).getAllByRole("listitem")).toHaveLength(4);
  });

  it("카메라 is off while an answer is coming and while photos go up", async () => {
    let releaseUpload!: () => void;
    const held = new Promise<void>((r) => (releaseUpload = r));
    photoBe({
      upload: async () => {
        await held;
        return HttpResponse.json({ id: 12, width: 10, height: 10, bytes: 9 }, { status: 201 });
      },
    });
    const gate = gatedResponse(answer("m-1", 5, "받았어요"), [1]);
    serveChat(() => gate.response());
    const { user } = await openSheet();
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    // The menu stays open from here: its 카메라 follows the sending, 사진 stays on.
    const camera = await menuItem(user, copy.chat.camera);
    // Off stays focusable (a menu item that goes away would drop the focus behind the sheet).
    await waitFor(() => expect(camera).toHaveAttribute("aria-disabled", "true")); // uploading
    expect(screen.getByRole("menuitem", { name: copy.photos.button })).not.toHaveAttribute("aria-disabled");
    const opened = vi.spyOn(cameraInput(), "click");
    await user.click(camera);
    expect(opened).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
    releaseUpload();
    await screen.findByRole("button", { name: copy.chat.stop });
    expect(camera).toHaveAttribute("aria-disabled", "true"); // answering
    gate.release();
    expect(await screen.findByText("받았어요")).toBeInTheDocument();
    await waitFor(() => expect(camera).not.toHaveAttribute("aria-disabled"));
  });

  it("✕ revokes that photo's tray address", async () => {
    photoBe();
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const { user } = await openSheet();
    await pick(user, [picture(1), picture(2)]);
    const t = await screen.findByRole("list", { name: copy.chat.tray });
    await waitFor(() => expect(t.querySelectorAll("img")).toHaveLength(2));
    const [first, second] = [...t.querySelectorAll("img")].map((i) => i.getAttribute("src")!);
    await user.click(within(t).getByRole("button", { name: copy.chat.unpick(2, 2) }));
    expect(revoke).toHaveBeenCalledWith(second);
    expect(revoke).not.toHaveBeenCalledWith(first);
  });

  it("sending revokes the tray addresses; once answered, the full-size pins are let go (thumbs stay in the 60)", async () => {
    photoBe();
    const gate = gatedResponse(answer("m-1", 5, "받았어요"), [1]);
    serveChat(() => gate.response());
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const { user } = await openSheet();
    await pick(user, [picture(1), picture(2)]);
    const t = await screen.findByRole("list", { name: copy.chat.tray });
    await waitFor(() => expect(t.querySelectorAll("img")).toHaveLength(2));
    const urls = [...t.querySelectorAll("img")].map((i) => i.getAttribute("src")!);
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await screen.findByRole("button", { name: copy.chat.stop });
    for (const u of urls) expect(revoke).toHaveBeenCalledWith(u);
    // While the answer comes, the photos' own bytes (full and thumb) are held.
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).not.toBeNull();
    const before = photoCacheSize();
    expect(before).toBe(4);
    gate.release();
    expect(await screen.findByText("받았어요")).toBeInTheDocument();
    await waitFor(() => expect(photoCacheSize()).toBe(2));
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).toBeNull();
    expect(peekPhoto(photoKey(TEST_BE_URL, 13, "full"))).toBeNull();
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "thumb"))).not.toBeNull();
  });

  it("closing the sheet lets go of the tray's addresses and of the pins of a message still unanswered", async () => {
    photoBe();
    const gate = gatedResponse(answer("m-1", 5, "받았어요"), [1]);
    serveChat(() => gate.response());
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const user = userEvent.setup();
    const { unmount } = renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    await pick(user, [picture(1)]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await screen.findByRole("button", { name: copy.chat.stop });
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).not.toBeNull();
    // One more waits in the tray.
    await pick(user, [picture(2)]);
    const t = await screen.findByRole("list", { name: copy.chat.tray });
    await waitFor(() => expect(t.querySelectorAll("img")).toHaveLength(1));
    const waiting = t.querySelector("img")!.getAttribute("src")!;
    unmount();
    expect(revoke).toHaveBeenCalledWith(waiting);
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).toBeNull();
    gate.release();
  });

  it("with photos, a sheet opened for a check-in still sends its checkin_id and conversation", async () => {
    serveHistory({ messages: { 8: [{ id: "m-8-1", at: "2026-10-24T01:00:00Z", speaker: "secretary", text: "체크인 대화예요" }] } });
    photoBe();
    const bodies = serveChat(() => sseResponse(answer("m-8-2", 8, "네")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={8} checkinId={341} />);
    expect(await screen.findByText("체크인 대화예요")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ conversation_id: 8, checkin_id: 341 });
    expect(bodies[0]).not.toHaveProperty("resume_conversation_id");
    expect((bodies[0] as unknown as Body).message.parts).toEqual([{ type: "data-photo", data: { photo_id: 12 } }]);
  });

  it("with photos, a conversation reopened from the list still carries resume_conversation_id", async () => {
    serveHistory({
      messages: {
        3: [
          { id: "u-3-1", at: "2026-10-20T01:00:00Z", speaker: "user", text: "읽을 책 골라 줘" },
          { id: "m-3-1", at: "2026-10-20T01:05:00Z", speaker: "secretary", text: "사피엔스 어때요" },
        ],
      },
    });
    server.use(
      http.get(`${BASE}/conversations`, () =>
        HttpResponse.json({
          items: [{ id: 3, kind: "chat", channel: "app", run_id: null, opened_at: "2026-10-20T01:00:00Z", last_message_at: "2026-10-20T01:05:00Z", closed_at: "2026-10-20T01:35:00Z", title: "책 고르기", summary: null }],
          next_before: null,
        }),
      ),
    );
    photoBe();
    const bodies = serveChat(() => sseResponse(answer("m-3-2", 3, "이어서 말해요")));
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await user.click(await screen.findByRole("button", { name: copy.chat.pastConversations }));
    await user.click((await screen.findByText("책 고르기")).closest("button") as HTMLElement);
    expect(await screen.findByText("사피엔스 어때요")).toBeInTheDocument();
    expect(sheetState.pickedConversationId).toBe(3);
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.type(screen.getByRole("textbox", { name: copy.chat.inputLabel }), "이것도");
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ conversation_id: 3, resume_conversation_id: 3, checkin_id: null });
    expect((bodies[0] as unknown as Body).message.parts).toEqual([
      { type: "text", text: "이것도" },
      { type: "data-photo", data: { photo_id: 12 } },
    ]);
  });

  it("a refused message's photos still open big, from their own bytes (the BE never gives them out)", async () => {
    const be = photoBe();
    serveChat(() => HttpResponse.json({ error: { code: "photo_not_found", message: "x" } }, { status: 400 }));
    const { user } = await openSheet();
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    expect(await screen.findByText(copy.photos.uploadFailed, { selector: "span" })).toBeInTheDocument();
    const log = screen.getByRole("log", { name: copy.chat.messages });
    await user.click(within(log).getByRole("button", { name: copy.photos.photo(1, 1) }));
    const viewer = await screen.findByRole("dialog", { name: copy.photos.viewer });
    await waitFor(() => expect(viewer.querySelector("img")?.getAttribute("src")).toMatch(/^blob:/));
    expect(be.gets).toEqual([]);
  });
});

// PH-07 fix round 2: the sheet stays mounted while closed (_app), so a refused message's own bytes
// must go when it closes (or reads its conversation again), not only when it unmounts.
describe("ChatSheet photos, fix round 2", () => {
  const sheet = (open: boolean) => <ChatSheet open={open} onClose={() => {}} conversationId={null} />;

  it("refuse, close, reopen: the refused photo's own bytes are let go", async () => {
    photoBe();
    serveChat(() => HttpResponse.json({ error: { code: "photo_not_found", message: "x" } }, { status: 400 }));
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(sheet(true));
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    expect(await screen.findByText(copy.photos.uploadFailed, { selector: "span" })).toBeInTheDocument();
    const held = photoCacheSize();
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).not.toBeNull();
    rerender(sheet(false));
    await waitFor(() => expect(photoCacheSize()).toBeLessThan(held));
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).toBeNull();
    rerender(sheet(true));
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).toBeNull();
    expect(photoCacheSize()).toBeLessThan(held);
  });

  it("a refusal that lands after the sheet closed keeps nothing pinned", async () => {
    photoBe();
    let answer!: () => void;
    const late = new Promise<void>((r) => (answer = r));
    serveChat(async () => {
      await late;
      return HttpResponse.json({ error: { code: "photo_not_found", message: "x" } }, { status: 400 });
    });
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(sheet(true));
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await screen.findByRole("button", { name: copy.chat.stop });
    // While it is out, its bytes are held (it may show again on reopening).
    rerender(sheet(false));
    expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).not.toBeNull();
    answer();
    await waitFor(() => expect(peekPhoto(photoKey(TEST_BE_URL, 12, "full"))).toBeNull());
  });

  it("Tab goes round the viewer's buttons, never to the sheet behind it", async () => {
    photoBe();
    serveHistory({
      conversations: [{ id: 5, last_message_at: "2026-10-24T01:00:00Z" }],
      messages: { 5: [{ id: "u-5-1", at: "2026-10-24T01:00:00Z", speaker: "user", text: "", photos: [{ id: 31, width: 10, height: 10 }, { id: 32, width: 10, height: 10 }] }] },
    });
    const user = userEvent.setup();
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    await user.click(await screen.findByRole("button", { name: copy.photos.photo(1, 2) }));
    const viewer = await screen.findByRole("dialog", { name: copy.photos.viewer });
    for (let i = 0; i < 5; i++) {
      await user.tab();
      expect(viewer.contains(document.activeElement)).toBe(true);
    }
    for (let i = 0; i < 3; i++) {
      await user.tab({ shift: true });
      expect(viewer.contains(document.activeElement)).toBe(true);
    }
  });
});

// SP10 16장: a photo-only message makes a photo memo without the brain; its answer carries
// data-photo-memo, and "글자 읽기" goes first in the chip row until another send, a read that is done,
// or another conversation.
describe("글자 읽기 chip (SP10 16장)", () => {
  const photoMemoAnswer = (messageId: string, conversationId: number, memoId: number, ids: number[]) =>
    sse([
      { type: "start", messageId, messageMetadata: { conversation_id: conversationId, channel: "app", kind: "chat", checkin_id: null } },
      { type: "start-step" },
      { type: "finish-step" },
      { type: "data-photo-memo", data: { memo_id: memoId, photo_ids: ids } },
      { type: "data-activity", data: { activity_ids: [70], undo_ids: [70], confirmation: copy.photos.created("사진", ids.length) } },
      { type: "finish", messageMetadata: { conversation_id: conversationId, channel: "app", kind: "chat" } },
      "[DONE]",
    ]);

  interface Sent {
    action: string;
    args: Record<string, unknown>;
  }

  /** Memo 40 (each read of it a new updated_at), the photo reads and /actions. */
  function memoBe(opts: { body?: string; reads?: (id: number, n: number) => Response | undefined; actions?: (n: number) => Response | undefined } = {}) {
    const reads: number[] = [];
    const sent: Sent[] = [];
    let memoGets = 0;
    server.use(
      http.get(`${BASE}/memos/:id`, ({ params }) => {
        memoGets++;
        return HttpResponse.json({
          id: Number(params.id),
          title: "사진",
          body: opts.body ?? "사진",
          area: null,
          pinned: false,
          origin: "user",
          created_at: "2026-10-31T01:00:00Z",
          updated_at: `2026-10-31T01:00:0${memoGets}Z`,
          photos: [],
        });
      }),
      http.post(`${BASE}/photos/:id/read`, ({ params }) => {
        const id = Number(params.id);
        reads.push(id);
        return opts.reads?.(id, reads.length) ?? HttpResponse.json({ text: `영수증 ${id}`, unreadable: false });
      }),
      http.post(`${BASE}/actions`, async ({ request }) => {
        const b = (await request.json()) as Sent;
        sent.push({ action: b.action, args: b.args });
        const custom = opts.actions?.(sent.length);
        if (custom) return custom;
        const title = String(b.args.body).split("\n")[0];
        return HttpResponse.json({
          status: "applied",
          activity_id: 900,
          undo_id: null,
          result: { id: 40, title, area: null, pinned: false, updated_at: "2026-10-31T01:05:00Z" },
          confirmation: copy.memos.confirm.updated(title),
        });
      }),
    );
    return { reads, sent, memoGets: () => memoGets };
  }

  const chipRow = () => screen.getByRole("group", { name: copy.chat.chipsLabel });
  const chipLabels = () => within(chipRow()).getAllByRole("button").map((b) => b.textContent);
  const readChip = () => within(chipRow()).queryByRole("button", { name: copy.chat.readChip });
  const toastSays = (text: string) => screen.queryAllByRole("status").some((s) => s.textContent?.includes(text));

  /** Sends photos alone and waits for the photo memo's answer. */
  async function sendPhotoOnly(user: ReturnType<typeof userEvent.setup>, n = 1) {
    await pick(user, Array.from({ length: n }, (_, i) => picture(i + 1)));
    await waitFor(() => expect(within(tray()!).getAllByRole("listitem")).toHaveLength(n));
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(toastSays(copy.photos.created("사진", n))).toBe(true));
  }

  it("after a photo-only message's photo memo it goes first (before the front chip); a press reads each photo into 사진, with no message and no bubble", async () => {
    photoBe();
    const bodies = serveChat(() => sseResponse(photoMemoAnswer("m-1", 5, 40, [12, 13])));
    const be = memoBe();
    const { user } = await openSheet();
    const before = chipLabels();
    expect(readChip()).toBeNull();
    await sendPhotoOnly(user, 2);
    await waitFor(() => expect(chipLabels()).toEqual([copy.chat.readChip, ...before]));
    expect(readChip()!.querySelector("svg")).not.toBeNull();
    const bubbles = document.querySelectorAll("[data-message]").length;
    await user.click(readChip()!);
    await waitFor(() => expect(be.sent).toHaveLength(1));
    expect(be.reads).toEqual([12, 13]);
    expect(be.sent[0]).toEqual({ action: "update_memo", args: { id: 40, body: "영수증 12\n\n영수증 13", updated_at: "2026-10-31T01:00:01Z" } });
    await waitFor(() => expect(toastSays(copy.photos.readInto("영수증 12"))).toBe(true));
    // Done: the chip goes. Nothing went to the brain and no bubble was made.
    await waitFor(() => expect(readChip()).toBeNull());
    expect(bodies).toHaveLength(1);
    expect(document.querySelectorAll("[data-message]")).toHaveLength(bubbles);
  });

  it("a body changed by hand: the text goes after it; a 409 reads it again and tries once more", async () => {
    photoBe();
    serveChat(() => sseResponse(photoMemoAnswer("m-1", 5, 40, [12])));
    const be = memoBe({
      body: "사진 영수증",
      actions: (n) => (n === 1 ? HttpResponse.json({ error: { code: "memo_conflict", message: "x" } }, { status: 409 }) : undefined),
    });
    const { user } = await openSheet();
    await sendPhotoOnly(user);
    await user.click(await within(chipRow()).findByRole("button", { name: copy.chat.readChip }));
    await waitFor(() => expect(be.sent).toHaveLength(2));
    expect(be.memoGets()).toBe(2);
    expect(be.sent.map((s) => s.args)).toEqual([
      { id: 40, body: "사진 영수증\n\n영수증 12", updated_at: "2026-10-31T01:00:01Z" },
      { id: 40, body: "사진 영수증\n\n영수증 12", updated_at: "2026-10-31T01:00:02Z" },
    ]);
    await waitFor(() => expect(readChip()).toBeNull());
  });

  it("a read that does not go through: it says so, the chip stays, and a second press reads again", async () => {
    photoBe();
    serveChat(() => sseResponse(photoMemoAnswer("m-1", 5, 40, [12])));
    const be = memoBe({ reads: (_id, n) => (n === 1 ? HttpResponse.json({ error: { code: "unavailable", message: "x" } }, { status: 503 }) : undefined) });
    const { user } = await openSheet();
    await sendPhotoOnly(user);
    await user.click(await within(chipRow()).findByRole("button", { name: copy.chat.readChip }));
    await waitFor(() => expect(toastSays(copy.actions.failed)).toBe(true));
    expect(be.sent).toEqual([]);
    expect(readChip()).not.toBeNull();
    await user.click(readChip()!);
    await waitFor(() => expect(be.sent).toHaveLength(1));
    await waitFor(() => expect(readChip()).toBeNull());
  });

  it("all unreadable: the unreadable sentence, and nothing is written", async () => {
    photoBe();
    serveChat(() => sseResponse(photoMemoAnswer("m-1", 5, 40, [12])));
    const be = memoBe({ reads: () => HttpResponse.json({ text: "", unreadable: true }) });
    const { user } = await openSheet();
    await sendPhotoOnly(user);
    await user.click(await within(chipRow()).findByRole("button", { name: copy.chat.readChip }));
    await waitFor(() => expect(toastSays(copy.photos.unreadable)).toBe(true));
    expect(be.sent).toEqual([]);
  });

  it("another message sent takes it away", async () => {
    photoBe();
    serveChat(
      () => sseResponse(photoMemoAnswer("m-1", 5, 40, [12])),
      () => sseResponse(answer("m-2", 5, "네")),
    );
    const { user, input } = await openSheet();
    await sendPhotoOnly(user);
    await within(chipRow()).findByRole("button", { name: copy.chat.readChip });
    await user.type(input, "고마워");
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    await waitFor(() => expect(readChip()).toBeNull());
    expect(await screen.findByText("네")).toBeInTheDocument();
    expect(readChip()).toBeNull();
  });

  it("a new conversation takes it away", async () => {
    photoBe();
    serveChat(() => sseResponse(photoMemoAnswer("m-1", 5, 40, [12])));
    server.use(http.post(`${BASE}/conversations/new`, () => HttpResponse.json({ closed: [5] })));
    const { user } = await openSheet();
    await sendPhotoOnly(user);
    await within(chipRow()).findByRole("button", { name: copy.chat.readChip });
    await user.click(screen.getByRole("button", { name: copy.chat.newConversation }));
    await waitFor(() => expect(readChip()).toBeNull());
  });

  it("an answer to a photo with words brings no chip", async () => {
    photoBe();
    serveChat(() => sseResponse(answer("m-1", 5, "받았어요")));
    const { user, input } = await openSheet();
    await pick(user, [picture()]);
    await screen.findByRole("list", { name: copy.chat.tray });
    await user.type(input, "영수증");
    await user.click(screen.getByRole("button", { name: copy.chat.send }));
    expect(await screen.findByText("받았어요")).toBeInTheDocument();
    expect(readChip()).toBeNull();
  });

  it("a reopened conversation shows no chip, even with a photo memo's line (photo_memo_id)", async () => {
    photoBe();
    const items = [
      { id: "u-5-1", at: "2026-10-31T01:00:00Z", speaker: "user", text: "", photos: [{ id: 31, width: 10, height: 10 }], photo_memo_id: 40 },
      { id: "m-5-1", at: "2026-10-31T01:00:01Z", speaker: "secretary", text: copy.photos.created("사진", 1) },
    ] as HistoryItem[];
    serveHistory({ conversations: [{ id: 5, last_message_at: "2026-10-31T01:00:01Z" }], messages: { 5: items } });
    renderWithProviders(<ChatSheet open onClose={() => {}} />);
    expect(await screen.findByText(copy.photos.created("사진", 1))).toBeInTheDocument();
    expect(readChip()).toBeNull();
  });

  it("closing and opening the sheet again takes it away", async () => {
    photoBe();
    serveChat(() => sseResponse(photoMemoAnswer("m-1", 5, 40, [12])));
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    await sendPhotoOnly(user);
    await within(chipRow()).findByRole("button", { name: copy.chat.readChip });
    rerender(<ChatSheet open={false} onClose={() => {}} conversationId={null} />);
    rerender(<ChatSheet open onClose={() => {}} conversationId={null} />);
    await waitFor(() => expect(screen.getByRole("textbox", { name: copy.chat.inputLabel })).toBeEnabled());
    expect(readChip()).toBeNull();
  });
});

import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copy } from "../lib/copy";
import { clearPhotoCache } from "../lib/photoCache";
import { PhotoUnopenable, shrinkPhoto } from "../lib/shrinkPhoto";
import { type HistoryItem, serveChat, serveHistory, sse, sseResponse } from "../test/chat";
import todayJson from "../test/fixtures/today.json";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { ChatSheet } from "./ChatSheet";

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
function photoBe(opts: { upload?: (n: number) => Response | undefined } = {}) {
  const uploads: Upload[] = [];
  const gets: string[] = [];
  let nextId = 12;
  server.use(
    http.post(`${BASE}/photos`, async ({ request }) => {
      const form = multipart(await request.text());
      uploads.push({ origin: form.origin, clientMsgId: form.client_msg_id, hasImage: form.image === "file image/jpeg", hasThumb: form.thumb === "file image/jpeg" });
      const custom = opts.upload?.(uploads.length);
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

/** Presses "사진" and picks `files` from the library. */
async function pick(user: ReturnType<typeof userEvent.setup>, files: File[]) {
  await user.click(screen.getByRole("button", { name: copy.photos.button }));
  await user.upload(pickerInput(), files);
}

const tray = () => screen.queryByRole("list", { name: copy.chat.tray });

describe("ChatSheet photos (SP10 7.5)", () => {
  it("two buttons left of the field: 카메라 opens the camera only, 사진 the library with many; no in-app camera", async () => {
    const media = vi.fn();
    vi.stubGlobal("navigator", Object.assign(Object.create(navigator), { mediaDevices: { getUserMedia: media } }));
    await openSheet();
    const camera = screen.getByRole("button", { name: copy.chat.camera });
    const photos = screen.getByRole("button", { name: copy.photos.button });
    // Both sit before the field in the composer.
    const field = screen.getByRole("textbox", { name: copy.chat.inputLabel });
    expect(camera.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(photos.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
    const button = screen.getByRole("button", { name: copy.photos.button });
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
    await user.click(screen.getByRole("button", { name: copy.chat.camera }));
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
    // Only to look at: no "메모에서 빼기" in the chat.
    expect(within(viewer).queryByRole("button", { name: copy.photos.detach })).toBeNull();
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

  it("offline: both buttons are off and no tray is taken", async () => {
    renderWithProviders(<ChatSheet open onClose={() => {}} conversationId={null} />, { conn: "offline" });
    await waitFor(() => expect(screen.getByRole("button", { name: copy.chat.camera })).toBeDisabled());
    expect(screen.getByRole("button", { name: copy.photos.button })).toBeDisabled();
  });

  it("the check-in screen's box has no photo buttons", async () => {
    renderWithProviders(<ChatSheet open embedded onClose={() => {}} conversationId={null} checkinId={341} />);
    await screen.findByRole("textbox", { name: copy.chat.inputLabel });
    expect(screen.queryByRole("button", { name: copy.chat.camera })).toBeNull();
    expect(screen.queryByRole("button", { name: copy.photos.button })).toBeNull();
  });
});

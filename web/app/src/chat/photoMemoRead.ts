import type { UIMessage } from "ai";
import { failureText, runAction } from "../api/actions";
import { apiGet } from "../api/client";
import { readLimitText, readPhoto } from "../api/photos";
import type { Memo } from "../api/types.gen";
import type { Conn } from "../lib/connection";
import { copy } from "../lib/copy";
import { notifyDataChanged } from "../lib/push";
import { BODY_MAX_CODE_POINTS, codePoints } from "../lib/shiftAnchor";

// SP10 16장 "글자 읽기" 퀵 칩: a photo-only chat message makes a photo memo with no read (its answer
// carries `data-photo-memo`); the chip reads the photos into that memo on request. Nothing goes to the
// brain and no bubble is made.

/** The memo a photo-only message made, and its photos in the order they were sent. */
export interface PhotoMemo {
  memoId: number;
  photoIds: number[];
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The `data-photo-memo` part of an answer (`{memo_id, photo_ids}`), or null. */
export function photoMemoOf(m: UIMessage): PhotoMemo | null {
  for (const p of m.parts) {
    if (p.type !== "data-photo-memo") continue;
    const d = (p as { data?: unknown }).data;
    if (!isObj(d) || typeof d.memo_id !== "number" || !Array.isArray(d.photo_ids)) return null;
    const ids = d.photo_ids.filter((x): x is number => typeof x === "number");
    return ids.length > 0 && ids.length === d.photo_ids.length ? { memoId: d.memo_id, photoIds: ids } : null;
  }
  return null;
}

/**
 * The memo's body with the read text in: in place of the default body "사진" when it is still that,
 * else at the end after one blank line. What would take it over 20,000 code points is left out (`cut`);
 * `noRoom`: nothing fits at all, and the body is as it was.
 */
export function fillPhotoMemo(body: string, read: string): { body: string; cut: boolean; noRoom: boolean } {
  const base = body === copy.photos.defaultBody ? "" : `${body.replace(/\n+$/, "")}\n\n`;
  const room = BODY_MAX_CODE_POINTS - codePoints(base);
  const chars = Array.from(read);
  if (chars.length <= room) return { body: base + read, cut: false, noRoom: false };
  if (room <= 0) return { body, cut: true, noRoom: true };
  return { body: base + chars.slice(0, room).join(""), cut: true, noRoom: false };
}

/** The toast's title: its first 20 (16장). */
const title20 = (t: string) => Array.from(t).slice(0, 20).join("");

/**
 * Reads the photos (`POST /photos/{id}/read`, in order) into the memo and saves it with update_memo;
 * a 409 reads the memo again and tries once more. `done` false: nothing was written, and the chip
 * stays to be pressed again. `text`: the toast.
 */
export async function readIntoPhotoMemo(conn: Conn, memoId: number, photoIds: number[]): Promise<{ done: boolean; text: string }> {
  const texts: string[] = [];
  for (const id of photoIds) {
    const r = await readPhoto(conn, id);
    if (r.kind !== "ok") return { done: false, text: readLimitText(r) ?? failureText(r) };
    const t = r.data.text.replace(/^\n+|\n+$/g, "");
    if (!r.data.unreadable && t.trim()) texts.push(t);
  }
  if (texts.length === 0) return { done: true, text: copy.photos.unreadable };
  const read = texts.join("\n\n");
  for (let attempt = 0; attempt < 2; attempt++) {
    const m = await apiGet<Memo>(`/memos/${memoId}`, "Memo");
    if (m.kind !== "ok") {
      if (m.kind === "error" && m.status === 404) return { done: true, text: copy.memos.errors.notFound };
      return { done: false, text: failureText(m) };
    }
    // Already there: an earlier save was applied though its answer was lost (the chip stayed). Not twice.
    if (m.data.body.includes(read)) return { done: true, text: copy.photos.readInto(title20(m.data.title)) };
    const next = fillPhotoMemo(m.data.body, read);
    if (next.noRoom) return { done: true, text: copy.photos.cut };
    const out = await runAction("update_memo", { id: memoId, body: next.body, updated_at: m.data.updated_at });
    if (out.kind === "conflict") continue;
    if (out.kind === "applied") {
      notifyDataChanged(); // the memos tab behind reads again
      const r = out.result as { title?: unknown } | null;
      const title = typeof r?.title === "string" ? r.title : m.data.title;
      return { done: true, text: next.cut ? copy.photos.cut : copy.photos.readInto(title20(title)) };
    }
    if (out.kind === "rejected") return { done: false, text: out.message || copy.actions.failed };
    if (out.kind === "failed") return { done: false, text: failureText(out.result) };
    return { done: false, text: copy.actions.failed };
  }
  return { done: false, text: copy.actions.failed };
}

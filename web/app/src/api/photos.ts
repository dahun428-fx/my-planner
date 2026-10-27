import type { Conn } from "../lib/connection";
import { copy } from "../lib/copy";
import { type HeldPhoto, holdPhoto, type PhotoSize, photoKey, putPhoto, unpinPhoto } from "../lib/photoCache";
import { type ApiResult, apiFetch } from "./client";
import type { PhotoRead, PhotoUploaded } from "./types.gen";
import { failureText } from "./actions";

// SP10 5.3 / 7.3: the photo routes, on the same BE with the same key as every other call.

const UPLOAD_LIMITS: ReadonlySet<string> = new Set(["photo_limit"]);
const READ_LIMITS: ReadonlySet<string> = new Set(["photo_read_limit"]);
// Up to 5 MB over the tailnet, and a read waits on the brain: both take longer than a plain call.
const UPLOAD_TIMEOUT_MS = 60_000;
const READ_TIMEOUT_MS = 120_000;
const BLOB_TIMEOUT_MS = 30_000;

/**
 * `POST /photos` (multipart). `clientMsgId` is new for each upload the person starts; a network
 * failure is tried once more with the same id, so a lost answer does not store the photo twice.
 */
export async function uploadPhoto(
  conn: Conn,
  p: { image: Blob; thumb: Blob; origin: "memo" | "chat"; clientMsgId: string },
): Promise<ApiResult<PhotoUploaded>> {
  const send = () => {
    const form = new FormData();
    form.append("image", p.image, "photo.jpg");
    form.append("thumb", p.thumb, "thumb.jpg");
    form.append("origin", p.origin);
    form.append("client_msg_id", p.clientMsgId);
    return apiFetch<PhotoUploaded>("POST", "/photos", {
      conn,
      report: true,
      form,
      model: "PhotoUploaded",
      limitCodes: UPLOAD_LIMITS,
      timeoutMs: UPLOAD_TIMEOUT_MS,
    });
  };
  const first = await send();
  if (first.kind !== "offline") return first;
  return send();
}

/** `POST /photos/{id}/read` (5.4): works on a photo not attached yet (a new memo's). */
export function readPhoto(conn: Conn, id: number): Promise<ApiResult<PhotoRead>> {
  return apiFetch<PhotoRead>("POST", `/photos/${id}/read`, {
    conn,
    report: true,
    model: "PhotoRead",
    limitCodes: READ_LIMITS,
    timeoutMs: READ_TIMEOUT_MS,
  });
}

const inFlight = new Map<string, Promise<boolean>>();

/**
 * A blob: address of `GET /photos/{id}?size=`, through the memory cache (7.3), already held for the
 * caller: call `release` when it is not shown any more (a full-size one is revoked then). Null when
 * it cannot be had (offline, a photo not live any more, a missing file): a grey cell.
 */
export async function photoBlobUrl(conn: Conn, id: number, size: PhotoSize): Promise<HeldPhoto | null> {
  const key = photoKey(conn.beUrl, id, size);
  // Held at once when there; otherwise fetched and held right after. Should it go in between (the
  // 60 moved on), it is fetched once more.
  for (let i = 0; i < 2; i++) {
    const held = holdPhoto(key);
    if (held) return held;
    if (!(await fetchInto(conn, id, size, key))) return null;
    const got = holdPhoto(key);
    if (got) return got;
  }
  return null;
}

function fetchInto(conn: Conn, id: number, size: PhotoSize, key: string): Promise<boolean> {
  const going = inFlight.get(key);
  if (going) return going;
  const run = (async () => {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), BLOB_TIMEOUT_MS);
    try {
      const res = await fetch(`${conn.beUrl}/api/v1/photos/${id}?size=${size}`, {
        headers: { Authorization: `Bearer ${conn.token}`, Accept: "image/jpeg" },
        cache: "no-store",
        signal: ac.signal,
      });
      if (!res.ok) return false;
      putPhoto(key, await res.blob());
      return true;
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
      inFlight.delete(key);
    }
  })();
  inFlight.set(key, run);
  return run;
}

/**
 * Shows a photo just uploaded from its own bytes: the BE does not give it out until it is attached
 * (5.1). They stay pinned until `dropLocalPhoto` (attached, or taken out before it was).
 */
export function keepLocalPhoto(conn: Conn, id: number, image: Blob, thumb: Blob): void {
  putPhoto(photoKey(conn.beUrl, id, "full"), image, { pinned: true });
  putPhoto(photoKey(conn.beUrl, id, "thumb"), thumb, { pinned: true });
}

/** The photo is attached (the BE gives it out now) or gone: its own bytes are no longer pinned. */
export function dropLocalPhoto(conn: Conn, id: number): void {
  unpinPhoto(conn.beUrl, id);
}

// ---- 8장 "응답 → 문구" -------------------------------------------------------------------------

/** The sentence for an upload that did not go through. */
export function uploadFailureText(r: ApiResult<unknown>): string {
  if (r.kind === "offline") return copy.actions.offline;
  if (r.kind !== "error") return r.kind === "ok" ? copy.photos.uploadFailed : failureText(r);
  if (r.status === 413) return copy.photos.tooLarge;
  if (r.status === 415 || (r.status === 422 && r.code === "photo_unreadable")) return copy.photos.cannotOpen;
  if (r.status === 429 && r.code === "photo_limit") return copy.photos.dailyLimit;
  if (r.status === 507) return copy.photos.diskFull;
  return copy.photos.uploadFailed;
}

/** A read that did not go through: the daily limit has its sentence; anything else leaves "다시 읽기". */
export function readLimitText(r: ApiResult<unknown>): string | null {
  return r.kind === "error" && r.status === 429 && r.code === "photo_read_limit" ? copy.photos.readLimit : null;
}

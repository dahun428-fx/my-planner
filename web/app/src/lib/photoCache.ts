// SP10 7.3: photos are shown from blob: addresses (an <img> cannot send the Authorization header,
// and the BE answers no-store). Small photos: the latest 60 stay in memory while the app is open; one
// goes (revokeObjectURL) when it falls out of those 60 and no screen shows it. Full-size photos are
// not kept: one goes as soon as no screen shows it (the viewer closes or moves on). The exception is
// a photo just uploaded and not attached yet (the BE does not give it out, 5.1): its own bytes are
// pinned until it is attached or dropped. Nothing here is written to device storage (the offline
// copy has no photos).

export type PhotoSize = "thumb" | "full";
export const PHOTO_CACHE_MAX = 60;

interface Entry {
  url: string;
  /** Screens showing it now; an entry in use is never revoked. */
  refs: number;
  /** A just-uploaded photo's own bytes: kept whatever its size and refs, until unpinned. */
  pinned: boolean;
  size: PhotoSize;
}

/** A shown address and the call that lets it go (once). */
export interface HeldPhoto {
  url: string;
  release(): void;
}

// A Map keeps insertion order: the first entry is the one used longest ago.
const entries = new Map<string, Entry>();

export const photoKey = (beUrl: string, id: number, size: PhotoSize) => `${beUrl}|${id}|${size}`;
const sizeOfKey = (key: string): PhotoSize => (key.endsWith("|full") ? "full" : "thumb");

function drop(key: string, e: Entry): void {
  URL.revokeObjectURL(e.url);
  if (entries.get(key) === e) entries.delete(key);
}

/** Small photos over the 60, oldest first, skipping those shown or pinned. */
function evict(): void {
  let thumbs = 0;
  for (const e of entries.values()) if (e.size === "thumb" && !e.pinned) thumbs++;
  if (thumbs <= PHOTO_CACHE_MAX) return;
  for (const [key, e] of entries) {
    if (thumbs <= PHOTO_CACHE_MAX) break;
    if (e.size !== "thumb" || e.pinned || e.refs > 0) continue;
    drop(key, e);
    thumbs--;
  }
}

/** The address held for `key` without holding it (a first paint), or null. */
export function peekPhoto(key: string): string | null {
  return entries.get(key)?.url ?? null;
}

/** Holds `blob` under `key` and gives its address. `pinned`: a just-uploaded photo (see above). */
export function putPhoto(key: string, blob: Blob, opts: { pinned?: boolean } = {}): string {
  const old = entries.get(key);
  if (old) {
    entries.delete(key);
    // Shown elsewhere: its release revokes it. A new entry starts with no screens.
    if (old.refs === 0) URL.revokeObjectURL(old.url);
  }
  const url = URL.createObjectURL(blob);
  entries.set(key, { url, refs: 0, pinned: opts.pinned ?? false, size: sizeOfKey(key) });
  evict();
  return url;
}

/** A screen starts showing `key` (now the newest). Null when it is not held (fetch it again). */
export function holdPhoto(key: string): HeldPhoto | null {
  const e = entries.get(key);
  if (!e) return null;
  entries.delete(key);
  entries.set(key, e);
  e.refs++;
  let done = false;
  return {
    url: e.url,
    release: () => {
      if (done) return;
      done = true;
      e.refs--;
      if (e.refs > 0) return;
      if (entries.get(key) !== e) {
        URL.revokeObjectURL(e.url); // replaced or dropped while shown: this address is no one's now
        return;
      }
      if (e.size === "full" && !e.pinned) drop(key, e);
      else evict();
    },
  };
}

/** A just-uploaded photo is attached (or dropped): its bytes are an ordinary entry now. */
export function unpinPhoto(beUrl: string, id: number): void {
  for (const size of ["full", "thumb"] as const) {
    const key = photoKey(beUrl, id, size);
    const e = entries.get(key);
    if (!e || !e.pinned) continue;
    e.pinned = false;
    if (size === "full" && e.refs === 0) drop(key, e);
  }
  evict();
}

/** Every address goes (the device disconnects). */
export function clearPhotoCache(): void {
  for (const e of entries.values()) URL.revokeObjectURL(e.url);
  entries.clear();
}

export function photoCacheSize(): number {
  return entries.size;
}

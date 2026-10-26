// SP10 7.3: photos are shown from blob: addresses (an <img> cannot send the Authorization header,
// and the BE answers no-store). The latest 60 stay in memory while the app is open; an address
// goes (revokeObjectURL) when it falls out of those 60 and no screen shows it any more, and all go
// when the app is closed. Nothing here is written to device storage (the offline copy has no photos).

export type PhotoSize = "thumb" | "full";
export const PHOTO_CACHE_MAX = 60;

interface Entry {
  url: string;
  /** Screens showing it now; an entry in use is never revoked. */
  refs: number;
}

// A Map keeps insertion order: the first entry is the one used longest ago.
const entries = new Map<string, Entry>();

export const photoKey = (beUrl: string, id: number, size: PhotoSize) => `${beUrl}|${id}|${size}`;

function evict(): void {
  if (entries.size <= PHOTO_CACHE_MAX) return;
  for (const [key, e] of entries) {
    if (entries.size <= PHOTO_CACHE_MAX) break;
    if (e.refs > 0) continue;
    URL.revokeObjectURL(e.url);
    entries.delete(key);
  }
}

/** The address held for `key`, as the newest, or null. */
export function cachedPhoto(key: string): string | null {
  const e = entries.get(key);
  if (!e) return null;
  entries.delete(key);
  entries.set(key, e);
  return e.url;
}

/** Holds `blob` under `key` (a photo just uploaded is shown from its own bytes, spec 7.1) and gives its address. */
export function putPhoto(key: string, blob: Blob): string {
  const old = entries.get(key);
  const url = URL.createObjectURL(blob);
  if (old) {
    entries.delete(key);
    if (old.refs === 0) URL.revokeObjectURL(old.url);
  }
  entries.set(key, { url, refs: old?.refs ?? 0 });
  evict();
  return url;
}

/** A screen starts showing `key`. Returns the release, which may revoke it once it is out of the 60. */
export function holdPhoto(key: string): () => void {
  const e = entries.get(key);
  if (!e) return () => {};
  e.refs++;
  let done = false;
  return () => {
    if (done) return;
    done = true;
    e.refs--;
    if (entries.get(key) !== e) {
      // Replaced or dropped while shown: this address is no one's now.
      if (e.refs === 0) URL.revokeObjectURL(e.url);
      return;
    }
    evict();
  };
}

/** Every address goes (the app closes, or the device disconnects). */
export function clearPhotoCache(): void {
  for (const e of entries.values()) URL.revokeObjectURL(e.url);
  entries.clear();
}

export function photoCacheSize(): number {
  return entries.size;
}

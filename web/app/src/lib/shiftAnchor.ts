// SP10 7.4: where a photo's read text goes. The anchor is the caret when "사진" was pressed; while
// the photo is read the body may change, and the anchor follows it.

/** The memo body limit, in code points (the BE counts the same way, SP9 6.1). */
export const BODY_MAX_CODE_POINTS = 20_000;

export function codePoints(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

/**
 * Moves `anchor` (an index into `prev`) to the matching index in `next`. The changed span is what
 * is left after taking off the common start and the common end. Wholly before the anchor (ending at
 * it or earlier, a typing right at it included): the anchor moves by the length difference. Wholly
 * after it (starting at it or later): it stays. Covering it: it goes to the changed span's new end.
 */
export function shiftAnchor(prev: string, next: string, anchor: number): number {
  if (prev === next) return anchor;
  const min = Math.min(prev.length, next.length);
  let start = 0;
  while (start < min && prev.charCodeAt(start) === next.charCodeAt(start)) start++;
  let tail = 0;
  while (tail < min - start && prev.charCodeAt(prev.length - 1 - tail) === next.charCodeAt(next.length - 1 - tail)) tail++;
  const prevEnd = prev.length - tail;
  const nextEnd = next.length - tail;
  if (prevEnd <= anchor) return anchor + (next.length - prev.length);
  if (start >= anchor) return anchor;
  return nextEnd;
}

/**
 * Puts the read text in at `anchor`: a line break before it unless the anchor is at the start or
 * right after one, and the same after it. What would take the body over 20,000 code points is left
 * out (`cut`).
 */
export function placeRead(body: string, anchor: number, read: string): { body: string; cut: boolean } {
  const at = Math.max(0, Math.min(anchor, body.length));
  const text = read.replace(/^\n+|\n+$/g, "");
  const before = at > 0 && body[at - 1] !== "\n" ? "\n" : "";
  const after = at < body.length && body[at] !== "\n" ? "\n" : "";
  let insert = before + text + after;
  const room = BODY_MAX_CODE_POINTS - codePoints(body);
  let cut = false;
  if (codePoints(insert) > room) {
    cut = true;
    insert = Array.from(before + text).slice(0, Math.max(room, 0)).join("");
  }
  return { body: body.slice(0, at) + insert + body.slice(at), cut };
}

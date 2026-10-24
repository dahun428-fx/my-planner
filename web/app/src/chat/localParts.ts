import { del, get, getMany, keys } from "idb-keyval";
import { setForBe } from "../lib/snapshot";
import type { ViewPart } from "./parts";

// Spec 4.6/4.7: the BE's transcript has no screen parts, so the app keeps the `ui_*` parts it got
// per secretary message id (`parts:<messageId>`), the latest 200, for 7 days.
const PREFIX = "parts:";
const MAX = 200;
const MAX_AGE_MS = 7 * 86_400_000;

interface Stored {
  savedAt: number;
  parts: ViewPart[];
}

const fresh = (v: Stored | undefined, now: number): v is Stored => !!v && typeof v.savedAt === "number" && now - v.savedAt <= MAX_AGE_MS;

// A blocked IndexedDB (private mode, cleared site data) means "nothing kept", never an error.
// `beUrl` is the BE the answer came from.
export async function saveParts(messageId: string, parts: ViewPart[], beUrl: string, now = Date.now()): Promise<void> {
  const ui = parts.filter((p) => p.kind === "ui");
  if (ui.length === 0) return;
  try {
    await setForBe(PREFIX + messageId, { savedAt: now, parts: ui } satisfies Stored, beUrl);
    await pruneParts(now);
  } catch {
    // nothing to do
  }
}

export async function loadParts(messageId: string, now = Date.now()): Promise<ViewPart[] | null> {
  try {
    const v = (await get(PREFIX + messageId)) as Stored | undefined;
    if (!v) return null;
    if (!fresh(v, now)) {
      await del(PREFIX + messageId);
      return null;
    }
    return v.parts;
  } catch {
    return null;
  }
}

export async function pruneParts(now = Date.now()): Promise<void> {
  try {
    const names = ((await keys()) as IDBValidKey[]).filter((k): k is string => typeof k === "string" && k.startsWith(PREFIX));
    const values = (await getMany(names)) as (Stored | undefined)[];
    const kept: { key: string; savedAt: number }[] = [];
    for (let i = 0; i < names.length; i++) {
      const v = values[i];
      if (fresh(v, now)) kept.push({ key: names[i], savedAt: v.savedAt });
      else await del(names[i]);
    }
    kept.sort((a, b) => b.savedAt - a.savedAt);
    for (const old of kept.slice(MAX)) await del(old.key);
  } catch {
    // nothing to do
  }
}

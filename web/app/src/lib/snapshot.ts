import { del, get, keys, set } from "idb-keyval";
import { useCallback, useEffect, useRef, useState } from "react";
import { type ApiResult, apiGet } from "../api/client";
import { loadConn } from "./connection";
import type { ModelName } from "../api/validate";
import { useConnection } from "./ConnectionProvider";
import { usePolling } from "./polling";

// Spec 4.6: the last good GET /today and GET /week, kept on the device with the time they arrived
// and the BE address they came from. Only those two responses are ever stored.
export type SnapKey = "today" | "week";

interface Stored {
  data: unknown;
  savedAt: string;
  beUrl: string;
}

const MAX_AGE_MS = 7 * 86_400_000;
const idbKey = (key: SnapKey) => `snap:${key}`;

/**
 * Stores an answer that came from `beUrl`, unless the device is no longer connected there (it was
 * disconnected, or another BE was entered, while the answer was coming). Throws what `set` throws.
 */
export async function setForBe(key: string, value: unknown, beUrl: string): Promise<void> {
  if (loadConn()?.beUrl !== beUrl) return;
  await set(key, value);
}

// A blocked IndexedDB (private mode, cleared site data) is "nothing saved", never an error.
export async function saveSnap(key: SnapKey, data: unknown, beUrl: string, now = Date.now()): Promise<void> {
  try {
    const value: Stored = { data, savedAt: new Date(now).toISOString(), beUrl };
    await setForBe(idbKey(key), value, beUrl);
  } catch {
    // nothing to do
  }
}

export async function loadSnap<T>(key: SnapKey, beUrl: string, now = Date.now()): Promise<{ data: T; savedAt: string } | null> {
  try {
    const v = (await get(idbKey(key))) as Stored | undefined;
    if (!v) return null;
    const age = now - Date.parse(v.savedAt);
    if (v.beUrl !== beUrl || !(age <= MAX_AGE_MS)) {
      await del(idbKey(key));
      return null;
    }
    return { data: v.data as T, savedAt: v.savedAt };
  } catch {
    return null;
  }
}

// The 7-day sweep (spec 4.7), once at app start: snapshots and chat parts past that age go even if
// nothing reads them again (a read also drops its own stale copy). `savedAt` is ISO in a snapshot,
// epoch ms in chat parts. The read and the delete of a key are two transactions, so a fresh copy
// written in between can go with the old one. That is harmless: a snapshot is written again by the
// next good poll (and only read offline), and a lost chat part only leaves its line as text.
export async function pruneDeviceData(now = Date.now()): Promise<void> {
  try {
    for (const k of await keys()) {
      if (typeof k !== "string" || !(k.startsWith("snap:") || k.startsWith("parts:"))) continue;
      const at = ((await get(k)) as { savedAt?: unknown } | undefined)?.savedAt;
      const ms = typeof at === "number" ? at : typeof at === "string" ? Date.parse(at) : NaN;
      if (!(now - ms <= MAX_AGE_MS)) await del(k);
    }
  } catch {
    // blocked IndexedDB: nothing stored there
  }
}

// "이 기기 연결 해제" (spec 4.7): snapshots, chat parts, catalog and every mp.* key.
// The mp.* keys go first: from then on no connection is saved, so an answer still coming for the
// old BE is not written (setForBe) after IndexedDB was cleared.
export async function clearDeviceData(): Promise<void> {
  try {
    for (const k of Object.keys(localStorage)) if (k.startsWith("mp.")) localStorage.removeItem(k);
  } catch {
    // blocked localStorage
  }
  try {
    for (const k of await keys()) {
      if (typeof k === "string" && (k.startsWith("snap:") || k.startsWith("parts:") || k === "catalog")) await del(k);
    }
  } catch {
    // blocked IndexedDB: nothing stored there to clear
  }
}

export type SnapView<T> =
  | { kind: "live"; data: T }
  | { kind: "snapshot"; data: T; savedAt: string }
  | { kind: "none" }
  | { kind: "loading" }
  | { kind: "blocked"; result: ApiResult<T> };

// Every polled answer carries the BE address it came from, so an answer for the previous BE is
// never shown or stored after the connection changes while the screen stays mounted.
type Tagged<T> = ApiResult<T> & { beUrl: string | null };

// Online: the polled answer (and it is stored when good). Offline: the stored copy, read-only.
export function useSnapshotted<T>(
  key: SnapKey,
  path: string,
  model: ModelName,
): { view: SnapView<T>; refresh(): Promise<void> } {
  const { state, conn } = useConnection();
  const beUrl = conn?.beUrl;
  const load = useCallback(async (): Promise<ApiResult<T>> => {
    const from = loadConn()?.beUrl ?? null; // apiFetch sends with the saved connection
    const r = await apiGet<T>(path, model);
    return { ...r, beUrl: from } as Tagged<T>;
  }, [path, model]);
  const { result: raw, refresh } = usePolling<T>(load);
  const result = raw && (raw as Tagged<T>).beUrl === beUrl ? raw : null;
  const [snap, setSnap] = useState<{ data: T; savedAt: string } | null | undefined>(undefined);
  const lastLive = useRef<{ beUrl: string; data: T } | null>(null);
  if (lastLive.current && lastLive.current.beUrl !== beUrl) lastLive.current = null;

  const offline = state?.kind === "offline" || result?.kind === "offline";

  useEffect(() => {
    if (result?.kind === "ok" && beUrl) {
      lastLive.current = { beUrl, data: result.data };
      void saveSnap(key, result.data, beUrl);
    }
  }, [result, key, beUrl]);

  useEffect(() => {
    setSnap(undefined);
    if (!offline || !beUrl) return;
    let alive = true;
    void loadSnap<T>(key, beUrl).then((s) => {
      if (alive) setSnap(s);
    });
    return () => {
      alive = false;
    };
  }, [offline, key, beUrl]);

  let view: SnapView<T>;
  if (offline) {
    view = snap === undefined ? { kind: "loading" } : snap === null ? { kind: "none" } : { kind: "snapshot", ...snap };
  } else if (result === null) {
    view = { kind: "loading" };
  } else if (result.kind === "ok") {
    view = { kind: "live", data: result.data };
  } else if (result.kind === "error" && lastLive.current !== null) {
    // A failed refresh does not blank a screen that already has content; the next poll tries again.
    view = { kind: "live", data: lastLive.current.data };
  } else {
    view = { kind: "blocked", result };
  }
  return { view, refresh };
}

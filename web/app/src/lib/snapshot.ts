import { del, get, keys, set } from "idb-keyval";
import { useCallback, useEffect, useRef, useState } from "react";
import { type ApiResult, apiGet } from "../api/client";
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

// A blocked IndexedDB (private mode, cleared site data) is "nothing saved", never an error.
export async function saveSnap(key: SnapKey, data: unknown, beUrl: string, now = Date.now()): Promise<void> {
  try {
    const value: Stored = { data, savedAt: new Date(now).toISOString(), beUrl };
    await set(idbKey(key), value);
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

// "이 기기 연결 해제" and the 7-day sweep (spec 4.7): snapshots, chat parts, catalog and every mp.* key.
export async function clearDeviceData(): Promise<void> {
  try {
    for (const k of await keys()) {
      if (typeof k === "string" && (k.startsWith("snap:") || k.startsWith("parts:") || k === "catalog")) await del(k);
    }
  } catch {
    // blocked IndexedDB: nothing stored there to clear
  }
  try {
    for (const k of Object.keys(localStorage)) if (k.startsWith("mp.")) localStorage.removeItem(k);
  } catch {
    // blocked localStorage
  }
}

export type SnapView<T> =
  | { kind: "live"; data: T }
  | { kind: "snapshot"; data: T; savedAt: string }
  | { kind: "none" }
  | { kind: "loading" }
  | { kind: "blocked"; result: ApiResult<T> };

// Online: the polled answer (and it is stored when good). Offline: the stored copy, read-only.
export function useSnapshotted<T>(
  key: SnapKey,
  path: string,
  model: ModelName,
): { view: SnapView<T>; refresh(): Promise<void> } {
  const { state, conn } = useConnection();
  const beUrl = conn?.beUrl;
  const { result, refresh } = usePolling<T>(useCallback(() => apiGet<T>(path, model), [path, model]));
  const [snap, setSnap] = useState<{ data: T; savedAt: string } | null | undefined>(undefined);
  const lastLive = useRef<T | null>(null);

  const offline = state?.kind === "offline" || result?.kind === "offline";

  useEffect(() => {
    if (result?.kind === "ok" && beUrl) {
      lastLive.current = result.data;
      void saveSnap(key, result.data, beUrl);
    }
  }, [result, key, beUrl]);

  useEffect(() => {
    if (!offline || !beUrl) {
      setSnap(undefined);
      return;
    }
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
    view = { kind: "live", data: lastLive.current };
  } else {
    view = { kind: "blocked", result };
  }
  return { view, refresh };
}

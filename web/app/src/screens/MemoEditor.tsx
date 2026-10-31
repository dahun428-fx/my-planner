import Link from "next/link";
import { useRouter } from "next/router";
import { type ChangeEvent, type MouseEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { type ActionOutcome, failureText, runAction } from "../api/actions";
import type { ApiResult } from "../api/client";
import { apiGet } from "../api/client";
import { dropLocalPhoto, keepLocalPhoto, readLimitText, readPhoto, uploadFailureText, uploadPhoto } from "../api/photos";
import type { Memo, PhotoRef } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Markdown } from "../components/Markdown";
import { OfflineNotice } from "../components/OfflineNotice";
import { PhotoStrip } from "../components/PhotoStrip";
import { PhotoViewer } from "../components/PhotoViewer";
import { Sheet } from "../components/Sheet";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { loadConn } from "../lib/connection";
import { copy } from "../lib/copy";
import { newClientMsgId } from "../lib/ids";
import { checklistLabels, checklistLines, memoDay, toggleChecklistLine } from "../lib/memoText";
import { BODY_MAX_CODE_POINTS, codePoints, placeRead, shiftAnchor } from "../lib/shiftAnchor";
import { shrinkPhoto } from "../lib/shrinkPhoto";
import page from "../styles/page.module.css";
import styles from "./MemoEditor.module.css";
import { memoHref } from "./Memos";

type Area = NonNullable<Memo["area"]>;
const AREAS = Object.keys(copy.areas) as Area[];
const SAVE_AFTER_MS = 1000;
const BODY_MAX = BODY_MAX_CODE_POINTS;
/** SP10 5.1: photos on one memo. */
const PHOTOS_MAX = 10;

/** A photo of this memo. `attached` false: uploaded, waiting for create_memo's photo_ids (a new memo). */
interface Pic {
  id: number;
  attached: boolean;
}
/** Where a photo's read text goes (7.4): moved along by every change of the body. */
interface Anchor {
  pos: number;
}
interface Reading {
  id: number;
  anchor: Anchor;
  state: "reading" | "failed";
}

/** 8장 응답 → 문구 for the photo writes of /actions. */
function photoOutcomeText(out: ActionOutcome): string {
  if (out.kind === "rejected") {
    if (out.code === "too_many_photos") return copy.photos.memoLimit;
    if (out.code === "photo_not_found") return copy.photos.uploadFailed;
    return copy.actions.failed; // e.g. a photo no longer on the memo: a plain refusal (SP5 general sentence)
  }
  if (out.kind === "failed") return out.result.kind === "error" && out.result.code === "photo_in_use" ? copy.photos.inUse : failureText(out.result);
  return copy.actions.failed;
}

/** The BE's photos of the memo, then the ones only this screen holds yet. */
function mergePics(fromBe: PhotoRef[] | undefined, mine: Pic[]): Pic[] {
  const be = (fromBe ?? []).map((p) => ({ id: p.id, attached: true }));
  const seen = new Set(be.map((p) => p.id));
  return [...be, ...mine.filter((p) => !p.attached && !seen.has(p.id))];
}

/** What the BE last holds for this memo, as far as this screen knows. `id` null: not made yet. */
interface Saved {
  id: number | null;
  body: string;
  area: Area | null;
  updatedAt: string | null;
}

/** The /actions result of the memo writes (6.4): no body. */
interface MemoResult {
  id: number;
  title: string;
  area: Area | null;
  pinned: boolean;
  updated_at: string;
}

// SP9 9.4: a device's unsaved text, `mp.memoDraft.<id|new>`. `base` is the updated_at the text
// was written on; a draft whose base the BE has moved past is dropped (the memo changed elsewhere).
interface Draft {
  body: string;
  area: Area | null;
  base: string | null;
}
const draftKey = (id: number | null) => `mp.memoDraft.${id ?? "new"}`;
function readDraft(id: number | null): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(id));
    const v = raw ? (JSON.parse(raw) as Partial<Draft>) : null;
    return v && typeof v.body === "string" ? { body: v.body, area: (v.area ?? null) as Area | null, base: typeof v.base === "string" ? v.base : null } : null;
  } catch {
    return null;
  }
}
function writeDraft(id: number | null, d: Draft): void {
  try {
    localStorage.setItem(draftKey(id), JSON.stringify(d));
  } catch {
    // a device convenience only
  }
}
function dropDraft(id: number | null): void {
  try {
    localStorage.removeItem(draftKey(id));
  } catch {
    // nothing to do
  }
}

/** Puts `prefix` at the start of the caret's line (or takes it off when it is there). */
function prefixLine(text: string, caret: number, prefix: string): { text: string; caret: number } {
  const start = text.lastIndexOf("\n", caret - 1) + 1;
  if (text.startsWith(prefix, start)) return { text: text.slice(0, start) + text.slice(start + prefix.length), caret: Math.max(start, caret - prefix.length) };
  return { text: text.slice(0, start) + prefix + text.slice(start), caret: caret + prefix.length };
}

type Load = { kind: "loading" } | { kind: "ok" } | { kind: "gone" } | { kind: "offline" } | { kind: "error"; code: string };

/**
 * SP9 9.4 view/write screen (`/memos/view/?id=`, a new memo `?new=1`). A new memo opens writing;
 * a saved one opens rendered, and a press on the text starts writing. Saves on "완료", on leaving
 * the screen, and 1s after the typing stops. A box pressed while reading flips that line only.
 * Offline it only reads; the text being written waits in localStorage as a draft.
 */
/** `id`: the memo, null for a new one, NaN for an address that names none. */
export function MemoEditor({ id: givenId, onCreated }: { id: number | null; onCreated?: (id: number) => void }) {
  const router = useRouter();
  const toast = useToast();
  const { state, recheck } = useConnection();
  const [load, setLoad] = useState<Load>(givenId === null ? { kind: "ok" } : Number.isNaN(givenId) ? { kind: "gone" } : { kind: "loading" });
  const [origin, setOrigin] = useState<Memo["origin"]>("user");
  const [firstDraft] = useState(() => (givenId === null ? readDraft(null) : null));
  const startDraft = useRef(firstDraft);
  const [text, setText] = useState(startDraft.current?.body ?? "");
  const [area, setArea] = useState<Area | null>(startDraft.current?.area ?? null);
  const [mode, setMode] = useState<"read" | "write">(givenId === null ? "write" : "read");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [areaOpen, setAreaOpen] = useState(false);
  const [tooLong, setTooLong] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const caret = useRef<number | null>(null);
  // SP10 7.1: the memo's photos, the one shown big, the reads going on and the uploads before them.
  const [photos, setPhotosState] = useState<Pic[]>([]);
  const photosRef = useRef(photos);
  const setPhotos = useCallback((next: Pic[] | ((p: Pic[]) => Pic[])) => {
    photosRef.current = typeof next === "function" ? next(photosRef.current) : next;
    setPhotosState(photosRef.current);
  }, []);
  const [viewing, setViewing] = useState<number | null>(null);
  const [reads, setReads] = useState<Reading[]>([]);
  const [uploading, setUploading] = useState(0);
  // Picked photos not in the row yet (shrinking, uploading): they count toward the 10 (5.1).
  const uploadsRef = useRef(0);
  const readsRef = useRef(reads);
  readsRef.current = reads;
  const fileInput = useRef<HTMLInputElement>(null);
  // 16장: the caret when the viewer opened (writing), where its "글자 읽기" puts the text; null reading.
  const opened = useRef<{ at: number; base: string } | null>(null);
  const anchors = useRef(new Set<Anchor>());
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const attachRef = useRef<(id: number) => Promise<boolean>>(async () => true);
  const removePicRef = useRef<(id: number) => void>(() => {});

  const saved = useRef<Saved>({ id: givenId, body: "", area: null, updatedAt: null });
  const textRef = useRef(text);
  textRef.current = text;
  const areaRef = useRef(area);
  areaRef.current = area;
  // The area goes to update_memo only when changed here (6.4: left out keeps it, null clears it).
  const areaTouched = useRef(startDraft.current?.area != null);
  const offline = state?.kind === "offline" || load.kind === "offline";
  const writable = useWritable(load.kind === "ok" && !offline);
  const writableRef = useRef(writable);
  writableRef.current = writable;
  const alive = useRef(true);
  // Why the last save did not go through, for "완료" to say (an autosave stays quiet: the draft keeps the text).
  const failure = useRef<ApiResult<never> | null>(null);

  /** A new memo holding photos not sent yet (7.1 v2.7: it is made even with no text). */
  const photosWaiting = () => saved.current.id === null && photosRef.current.some((p) => !p.attached);
  const isDirty = () => {
    const s = saved.current;
    return textRef.current !== s.body || (areaTouched.current && areaRef.current !== s.area) || photosWaiting();
  };

  const take = useCallback((m: Memo) => {
    saved.current = { id: m.id, body: m.body, area: m.area, updatedAt: m.updated_at };
    areaTouched.current = false;
    textRef.current = m.body;
    areaRef.current = m.area;
    setText(m.body);
    setArea(m.area);
    setOrigin(m.origin);
    setUpdatedAt(m.updated_at);
    setPhotos((mine) => mergePics(m.photos, mine));
  }, [setPhotos]);

  const read = useCallback(async (id: number): Promise<"ok" | "gone" | "other"> => {
    const r = await apiGet<Memo>(`/memos/${id}`, "Memo");
    if (!alive.current) return "other";
    if (r.kind === "ok") {
      take(r.data);
      setLoad({ kind: "ok" });
      return "ok";
    }
    if (r.kind === "error" && r.status === 404) {
      setLoad({ kind: "gone" });
      return "gone";
    }
    setLoad(r.kind === "offline" ? { kind: "offline" } : { kind: "error", code: r.kind === "error" ? r.code : r.kind });
    return "other";
  }, [take]);

  // A saved memo: read it, then put back a draft written on what the BE still holds.
  useEffect(() => {
    if (givenId === null || Number.isNaN(givenId)) return;
    void read(givenId).then((how) => {
      if (how !== "ok") return;
      const d = readDraft(givenId);
      if (!d) return;
      if (d.base !== saved.current.updatedAt) {
        dropDraft(givenId);
        if (d.body !== saved.current.body) toast.show({ text: copy.memos.conflict });
        return;
      }
      if (d.body === saved.current.body && d.area === saved.current.area) {
        dropDraft(givenId);
        return;
      }
      textRef.current = d.body;
      areaRef.current = d.area;
      areaTouched.current = d.area !== saved.current.area;
      setText(d.body);
      setArea(d.area);
      setMode("write");
    });
    // Once per memo (the toast api is stable).
  }, [givenId, read]);

  // --- saving: one write at a time; changes made while one is out go in the next ---
  const inFlight = useRef<Promise<void> | null>(null);
  const again = useRef(false);
  const forced = useRef(false);
  const createFailed = useRef(false);

  const saveOnce = useCallback(async (auto: boolean): Promise<boolean> => {
    if (!isDirty()) return true;
    let body = textRef.current;
    const a = areaRef.current;
    const s = saved.current;
    let defaulted = false;
    if (!body.trim()) {
      if (!photosWaiting()) return false; // the BE takes no empty memo; nothing to keep
      // SP10 7.1 (v2.7): a new memo with only photos is made with the body "사진", so they are not
      // lost. The autosave waits while a photo is still read (its text is on the way); "완료" and
      // leaving the screen do not.
      if (auto && (uploadsRef.current > 0 || readsRef.current.some((r) => r.state === "reading"))) return false;
      body = copy.photos.defaultBody;
      defaulted = true;
    }
    if (codePoints(body) > BODY_MAX) {
      if (alive.current) setTooLong(true);
      return false;
    }
    if (!writableRef.current) return false; // offline: the draft holds it
    // A create that failed may still have been made (the answer lost): the 1s autosave does not send it
    // again; "완료" and leaving the screen do.
    if (s.id === null && auto && createFailed.current) return false;
    failure.current = null;
    if (s.id === null) {
      // SP10 7.1: a new memo's photos go with its creation, in order.
      const photoIds = photosRef.current.filter((p) => !p.attached).map((p) => p.id);
      const args: Record<string, unknown> = a !== null ? { body, area: a } : { body };
      if (photoIds.length > 0) args.photo_ids = photoIds;
      const out = await runAction("create_memo", args);
      createFailed.current = out.kind === "failed";
      if (out.kind === "applied") {
        const r = out.result as MemoResult;
        saved.current = { id: r.id, body, area: r.area, updatedAt: r.updated_at };
        if (defaulted && !textRef.current.trim()) {
          // The screen shows what was saved (and an anchor at 0 moves after it).
          textRef.current = body;
          if (alive.current) setText(body);
        }
        setPhotos((ps) => ps.map((p) => (photoIds.includes(p.id) ? { ...p, attached: true } : p)));
        const conn = loadConn();
        if (conn) for (const id of photoIds) dropLocalPhoto(conn, id);
        // A photo that came while the creation was out is attached on its own.
        for (const p of photosRef.current) if (!p.attached) void attachRef.current(p.id);
        areaTouched.current = areaRef.current !== r.area;
        dropDraft(null);
        if (isDirty()) writeDraft(r.id, { body: textRef.current, area: areaRef.current, base: r.updated_at });
        toast.show({ text: out.confirmation, undoId: out.undoId });
        if (alive.current) {
          setUpdatedAt(r.updated_at);
          onCreated?.(r.id);
          void router.replace(memoHref(r.id), undefined, { shallow: true });
        }
        return true;
      }
      if (out.kind === "rejected") toast.show({ text: out.message || copy.actions.failed });
      if (out.kind === "failed" && out.result.kind === "error" && out.result.code === "photo_in_use") {
        // 8장: a photo is already on another memo, so the memo was not made. The 409 does not say
        // which one, so the photos sent with it leave the row and the next save can make the memo.
        createFailed.current = false;
        for (const id of photoIds) removePicRef.current(id);
        toast.show({ text: photoOutcomeText(out) });
        return false;
      }
      if (out.kind === "failed") failure.current = out.result;
      return false;
    }
    const args: Record<string, unknown> = { id: s.id, body };
    if (areaTouched.current) args.area = a;
    args.updated_at = s.updatedAt;
    const out = await runAction("update_memo", args);
    if (out.kind === "applied") {
      const r = out.result as MemoResult;
      saved.current = { id: s.id, body, area: r.area, updatedAt: r.updated_at };
      areaTouched.current = areaRef.current !== r.area;
      if (isDirty()) writeDraft(s.id, { body: textRef.current, area: areaRef.current, base: r.updated_at });
      else dropDraft(s.id);
      if (alive.current) setUpdatedAt(r.updated_at);
      return true;
    }
    if (out.kind === "conflict") {
      // 6.4: say so and read again; what is there now wins, and this device's text goes.
      toast.show({ text: copy.memos.conflict });
      dropDraft(s.id);
      if (alive.current) {
        await read(s.id);
        setMode("read");
      }
      return false;
    }
    if (out.kind === "rejected") toast.show({ text: out.message || copy.actions.failed });
    if (out.kind === "failed") failure.current = out.result;
    return false;
  }, [onCreated, read, router, toast]);

  // `auto`: the 1s autosave (see createFailed). A press or leaving the screen is not auto.
  const save = useCallback(async (auto = false): Promise<boolean> => {
    if (inFlight.current) {
      again.current = true;
      if (!auto) forced.current = true;
      await inFlight.current;
      return !isDirty();
    }
    let ok = true;
    const run = (async () => {
      do {
        again.current = false;
        const quiet = auto && !forced.current;
        forced.current = false;
        ok = await saveOnce(quiet);
      } while (again.current && ok);
    })();
    inFlight.current = run;
    try {
      await run;
    } finally {
      inFlight.current = null;
    }
    return ok;
  }, [saveOnce]);
  const saveRef = useRef(save);
  saveRef.current = save;

  // The draft follows every change; the save follows 1s after the last one.
  useEffect(() => {
    if (!isDirty()) return;
    writeDraft(saved.current.id, { body: text, area, base: saved.current.updatedAt });
    if (codePoints(text) <= BODY_MAX) setTooLong(false);
    if (mode !== "write") return;
    if (!writable) return; // back online, this runs again and saves
    const t = setTimeout(() => void saveRef.current(true), SAVE_AFTER_MS);
    return () => clearTimeout(t);
    // photos and reads: a new memo with only a photo is saved once its read ends (7.1 v2.7).
  }, [text, area, mode, writable, photos, reads]);

  // Leaving: the tab goes to the background, or the screen goes away.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") void saveRef.current();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      alive.current = false;
      void saveRef.current().then(() => {
        // Photos this screen still held only as its own bytes go with it.
        const conn = loadConn();
        if (conn) for (const p of photosRef.current) if (!p.attached) dropLocalPhoto(conn, p.id);
      });
    };
  }, []);
  useEffect(() => {
    alive.current = true;
  }, []);

  // "되돌리기" of this memo's creation (the toast): the memo is gone, so is this screen.
  useEffect(
    () =>
      toast.onUndone(() => {
        const id = saved.current.id;
        if (id === null) return;
        void apiGet<Memo>(`/memos/${id}`, "Memo").then((r) => {
          // "되돌리기" of taking a photo out (detach_photo): it is back on the memo.
          if (r.kind === "ok" && alive.current) setPhotos((mine) => mergePics(r.data.photos, mine));
          if (r.kind === "error" && r.status === 404 && alive.current) {
            dropDraft(id);
            saved.current = { ...saved.current, body: textRef.current, area: areaRef.current }; // nothing left to save
            areaTouched.current = false;
            void router.replace("/memos/");
          }
        });
      }),
    [toast, router, setPhotos],
  );

  // Focus and caret after a tool button or on opening the write state.
  useLayoutEffect(() => {
    if (mode !== "write" || !box.current) return;
    if (caret.current !== null) {
      box.current.setSelectionRange(caret.current, caret.current);
      caret.current = null;
    }
  });
  useEffect(() => {
    if (mode === "write" && writable) box.current?.focus();
  }, [mode, writable]);
  // Offline it only reads.
  useEffect(() => {
    if (!writable && mode === "write" && givenId !== null && saved.current.id !== null && !isDirty()) setMode("read");
  }, [writable, mode, givenId]);

  const edit = (next: string, at: number) => {
    textRef.current = next;
    caret.current = at;
    setText(next);
    box.current?.focus();
  };
  const tool = (prefix: string) => {
    const el = box.current;
    const at = el ? el.selectionStart : text.length;
    const r = prefixLine(text, at, prefix);
    edit(r.text, r.caret);
  };
  const bold = () => {
    const el = box.current;
    const start = el ? el.selectionStart : text.length;
    const end = el ? el.selectionEnd : text.length;
    const picked = text.slice(start, end);
    edit(`${text.slice(0, start)}**${picked}**${text.slice(end)}`, start + 2 + picked.length);
  };
  // A tool press must not take the caret out of the text box.
  const keep = (e: MouseEvent) => e.preventDefault();

  // --- SP10 7.1 photos ---
  // Every change of the body moves the anchors of the photos being read (7.4).
  const seenText = useRef(text);
  const syncAnchors = useCallback(() => {
    const now = textRef.current;
    const prev = seenText.current;
    if (prev === now) return;
    for (const a of anchors.current) a.pos = shiftAnchor(prev, now, a.pos);
    seenText.current = now;
  }, []);
  useEffect(() => {
    syncAnchors();
  }, [text, syncAnchors]);

  const removePic = useCallback(
    (id: number) => {
      const pic = photosRef.current.find((p) => p.id === id);
      const conn = loadConn();
      if (pic && !pic.attached && conn) dropLocalPhoto(conn, id);
      // Its read, if one is going on or waiting for 다시 읽기, goes too.
      for (const r of readsRef.current) if (r.id === id) anchors.current.delete(r.anchor);
      setReads((rs) => rs.filter((r) => r.id !== id));
      setPhotos((ps) => ps.filter((p) => p.id !== id));
      const n = photosRef.current.length;
      setViewing((v) => (v === null || n === 0 ? null : Math.min(v, n - 1)));
    },
    [setPhotos],
  );
  removePicRef.current = removePic;

  // A saved memo takes the photo at once; a new one takes it with create_memo's photo_ids.
  const attach = useCallback(
    async (id: number): Promise<boolean> => {
      const memoId = saved.current.id;
      if (memoId === null) return true;
      const out = await runAction("attach_photo", { memo_id: memoId, photo_id: id });
      if (out.kind === "applied") {
        setPhotos((ps) => ps.map((p) => (p.id === id ? { ...p, attached: true } : p)));
        const conn = loadConn();
        if (conn) dropLocalPhoto(conn, id); // the BE gives it out now
        if (out.activityId !== null && out.confirmation) toast.show({ text: out.confirmation });
        return true;
      }
      removePic(id);
      toast.show({ text: photoOutcomeText(out) });
      return false;
    },
    [removePic, setPhotos, toast],
  );
  attachRef.current = attach;

  // POST /photos/{id}/read, then the text goes in at the anchor (7.4). In the read state it is saved at once.
  const readInto = useCallback(
    async (id: number, anchor: Anchor) => {
      setReads((rs) => [...rs.filter((r) => r.id !== id), { id, anchor, state: "reading" }]);
      const conn = loadConn();
      const r: ApiResult<{ text: string; unreadable: boolean }> = conn ? await readPhoto(conn, id) : { kind: "offline" };
      if (!alive.current) return;
      if (!photosRef.current.some((p) => p.id === id)) return; // taken out while it was read (removePic dropped its entry)
      if (r.kind !== "ok") {
        const limit = readLimitText(r);
        if (limit) {
          anchors.current.delete(anchor);
          setReads((rs) => rs.filter((x) => x.id !== id));
          toast.show({ text: limit });
        } else {
          setReads((rs) => rs.map((x) => (x.id === id ? { ...x, state: "failed" } : x)));
        }
        return;
      }
      anchors.current.delete(anchor);
      setReads((rs) => rs.filter((x) => x.id !== id));
      if (r.data.unreadable || !r.data.text.trim()) {
        toast.show({ text: copy.photos.unreadable });
        return;
      }
      syncAnchors();
      const out = placeRead(textRef.current, anchor.pos, r.data.text);
      textRef.current = out.body;
      setText(out.body);
      toast.show({ text: out.cut ? copy.photos.cut : copy.photos.inserted });
      if (modeRef.current === "read") void saveRef.current();
    },
    [syncAnchors, toast],
  );

  /** `inRow`: called once the photo is in the row (it stops counting as an upload). 16장: it is not read. */
  const addPhoto = async (file: File, inRow: () => void): Promise<void> => {
    let shrunk: { image: Blob; thumb: Blob };
    try {
      shrunk = await shrinkPhoto(file);
    } catch {
      toast.show({ text: copy.photos.cannotOpen });
      return;
    }
    const conn = loadConn();
    if (!conn) {
      toast.show({ text: copy.actions.offline });
      return;
    }
    // A new client_msg_id for every photo picked (uploadPhoto keeps it for its own retry only).
    const up = await uploadPhoto(conn, { ...shrunk, origin: "memo", clientMsgId: newClientMsgId() });
    if (up.kind !== "ok") {
      toast.show({ text: uploadFailureText(up) });
      return;
    }
    // The BE gives the photo out only once it is attached (5.1): until then it is shown from these bytes.
    keepLocalPhoto(conn, up.data.id, shrunk.image, shrunk.thumb);
    if (!alive.current) return;
    setPhotos((ps) => [...ps, { id: up.data.id, attached: false }]);
    inRow();
    await attach(up.data.id);
  };

  /** The photos of the memo and those on their way: two quick picks at 9 must not make 11. */
  const photoCount = () => photosRef.current.length + uploadsRef.current;
  const pickPhoto = () => {
    if (photoCount() >= PHOTOS_MAX) {
      toast.show({ text: copy.photos.memoLimit });
      return;
    }
    fileInput.current?.click();
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (photoCount() >= PHOTOS_MAX) {
      toast.show({ text: copy.photos.memoLimit });
      return;
    }
    uploadsRef.current++;
    let counted = true;
    const leaveUploads = () => {
      if (!counted) return;
      counted = false;
      uploadsRef.current--;
      if (alive.current) setUploading((n) => n - 1);
    };
    setUploading((n) => n + 1);
    try {
      await addPhoto(file, leaveUploads);
    } finally {
      leaveUploads();
    }
  };

  // 16장: the viewer opens on a photo; writing, the caret then is where its read text will go (7.4).
  const openViewer = (i: number) => {
    const el = box.current;
    opened.current = modeRef.current === "write" && el ? { at: el.selectionStart, base: textRef.current } : null;
    setViewing(i);
  };
  // 16장 "글자 읽기": closes the viewer and reads that photo: writing, at the caret of the opening (moved
  // along by what changed since); reading, at the end of the body.
  const readShown = (id: number) => {
    setViewing(null);
    if (readsRef.current.some((r) => r.id === id && r.state === "reading")) return;
    // A failed read of the same photo (its 다시 읽기) gives way to this one and its place.
    for (const r of readsRef.current) if (r.id === id) anchors.current.delete(r.anchor);
    syncAnchors();
    const at = opened.current;
    const pos = at && modeRef.current === "write" ? shiftAnchor(at.base, textRef.current, at.at) : textRef.current.length;
    const anchor: Anchor = { pos };
    anchors.current.add(anchor);
    void readInto(id, anchor);
  };

  const reread = () => {
    for (const r of reads) if (r.state === "failed") void readInto(r.id, r.anchor);
  };

  const detach = async (id: number) => {
    const pic = photosRef.current.find((p) => p.id === id);
    if (!pic) return;
    const memoId = saved.current.id;
    if (!pic.attached || memoId === null) {
      removePic(id); // only on this screen yet
      return;
    }
    const out = await runAction("detach_photo", { memo_id: memoId, photo_id: id });
    if (out.kind === "applied") {
      removePic(id);
      if (out.activityId !== null) toast.show({ text: out.confirmation, undoId: out.undoId });
      return;
    }
    toast.show({ text: photoOutcomeText(out) });
  };

  const done = async () => {
    const ok = await save();
    if (!alive.current) return;
    if (!ok && failure.current) toast.show({ text: failureText(failure.current) });
    if (saved.current.id !== null && !textRef.current.trim()) {
      toast.show({ text: copy.memos.errors.empty }); // a saved memo cannot become empty (6.1)
      return;
    }
    if (saved.current.id === null) {
      // A new memo with only a photo stays: its text is still to be written (or read, 16장).
      if (!textRef.current.trim() && photosRef.current.length === 0) void router.push("/memos/");
      return;
    }
    if (ok && !isDirty()) setMode("read");
  };

  const back = async (e: MouseEvent) => {
    e.preventDefault();
    await save();
    void router.push("/memos/");
  };

  const toggle = (line: number) => {
    const next = toggleChecklistLine(textRef.current, line);
    if (next === textRef.current) return;
    textRef.current = next;
    setText(next);
    void save();
  };

  const startWriting = (e: MouseEvent) => {
    const t = e.target as HTMLElement;
    if (!writable || t.closest("input, a, button")) return;
    setMode("write");
  };

  const photosFull = photos.length + uploading >= PHOTOS_MAX;
  // 16장: only a read shows the band (an upload is not read any more).
  const busy = reads.some((r) => r.state === "reading");
  const readFailed = reads.some((r) => r.state === "failed");
  // SP10 7.1: the line above the tool row while a photo is read; "다시 읽기" after a read that did not go through.
  const band =
    busy || readFailed ? (
      <div className={styles.band} aria-live="polite">
        {busy && <span>{copy.photos.reading}</span>}
        {readFailed && writable && (
          <button type="button" className={styles.reread} onClick={reread}>
            {copy.photos.reread}
          </button>
        )}
      </div>
    ) : null;

  let body: React.ReactNode;
  if (load.kind === "loading") {
    body = (
      <div className={styles.pad}>
        <Skeleton size="row" />
        <Skeleton size="row" />
      </div>
    );
  } else if (load.kind === "gone") {
    body = <p className={styles.line}>{copy.memos.errors.notFound}</p>;
  } else if (load.kind === "error") {
    body = <BlockError code={load.code} onRetry={() => givenId !== null && void read(givenId)} />;
  } else if (load.kind === "offline") {
    body = null;
  } else if (mode === "write") {
    body = (
      <>
        <textarea
          ref={box}
          className={styles.box}
          aria-label={copy.memos.body}
          value={text}
          readOnly={!writable}
          onChange={(e) => {
            textRef.current = e.target.value;
            setText(e.target.value);
          }}
        />
        {tooLong && (
          <p className={styles.note} role="status">
            {copy.memos.errors.tooLong}
          </p>
        )}
        {band}
        {writable && (
          <div className={styles.tools} role="toolbar" aria-label={copy.memos.toolbar.label}>
            <button type="button" className={styles.tool} onMouseDown={keep} onClick={() => tool("- ")}>
              {copy.memos.toolbar.list}
            </button>
            <button type="button" className={styles.tool} onMouseDown={keep} onClick={() => tool("- [ ] ")}>
              {copy.memos.toolbar.checkbox}
            </button>
            <button type="button" className={`${styles.tool} ${styles.bold}`} onMouseDown={keep} onClick={bold}>
              {copy.memos.toolbar.bold}
            </button>
            <button
              type="button"
              className={`${styles.tool} ${photosFull ? styles.dim : ""}`}
              aria-disabled={photosFull || undefined}
              onMouseDown={keep}
              onClick={pickPhoto}
            >
              {copy.photos.button}
            </button>
            <button type="button" className={styles.tool} onClick={() => setAreaOpen(true)}>
              {copy.memos.toolbar.area}
              {area && <span className={`area-dot ${styles.toolDot}`} data-area={area} aria-hidden="true" />}
            </button>
            <button type="button" className={`${styles.tool} ${styles.done}`} onClick={() => void done()}>
              {copy.memos.toolbar.done}
            </button>
          </div>
        )}
      </>
    );
  } else {
    const lines = checklistLines(text);
    body = (
      // A press on the text (not on a box or a link) starts writing; from the keyboard, Enter on it.
      <div
        className={`${styles.reading} ${writable ? styles.pressable : ""}`}
        onClick={startWriting}
        tabIndex={writable ? 0 : undefined}
        onKeyDown={(e) => {
          if (e.key === "Enter" && e.target === e.currentTarget && writable) setMode("write");
        }}
      >
        <Markdown text={text} className={styles.rendered} tasks={{ lines, labels: checklistLabels(text, lines), disabled: !writable, onToggle: toggle }} />
      </div>
    );
    if (band) {
      body = (
        <>
          {body}
          {band}
        </>
      );
    }
  }

  const meta: string[] = [];
  if (updatedAt) meta.push(memoDay(updatedAt));
  return (
    <main className={`${page.main} ${styles.main}`}>
      <nav className={styles.bar}>
        <Link href="/memos/" className={styles.back} onClick={(e) => void back(e)}>
          {copy.memos.back}
        </Link>
        {load.kind === "ok" && (meta.length > 0 || area || origin === "chat") && (
          <span className={styles.meta}>
            {area && (
              <span className={styles.area}>
                <span className="area-dot" data-area={area} aria-hidden="true" />
                {copy.areas[area]}
              </span>
            )}
            {origin === "chat" && <span className={styles.secretary}>{copy.memos.bySecretary}</span>}
            {meta.length > 0 && <span className="tnum">{meta.join(" · ")}</span>}
          </span>
        )}
      </nav>
      {offline && <OfflineNotice savedAt={null} onRetry={() => void recheck()} />}
      {load.kind === "ok" && <PhotoStrip photos={photos} onOpen={openViewer} />}
      {body}
      <input ref={fileInput} type="file" accept="image/*" hidden aria-label={copy.photos.button} onChange={(e) => void onFile(e)} />
      <PhotoViewer
        photos={photos}
        index={viewing}
        onIndex={setViewing}
        onClose={() => setViewing(null)}
        onDetach={writable ? (id) => void detach(id) : undefined}
        onRead={writable ? readShown : undefined}
      />
      <Sheet open={areaOpen} onClose={() => setAreaOpen(false)} title={copy.memos.toolbar.area}>
        <div className={styles.areas}>
          {[null, ...AREAS].map((a) => (
            <button
              key={a ?? "none"}
              type="button"
              className={styles.areaItem}
              aria-pressed={area === a}
              onClick={() => {
                areaRef.current = a;
                areaTouched.current = true;
                setArea(a);
                setAreaOpen(false);
              }}
            >
              {a && <span className="area-dot" data-area={a} aria-hidden="true" />}
              {a ? copy.areas[a] : copy.memos.noArea}
            </button>
          ))}
        </div>
      </Sheet>
    </main>
  );
}

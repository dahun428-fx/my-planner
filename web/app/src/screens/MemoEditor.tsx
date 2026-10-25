import Link from "next/link";
import { useRouter } from "next/router";
import { type MouseEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { failureText, runAction } from "../api/actions";
import type { ApiResult } from "../api/client";
import { apiGet } from "../api/client";
import type { Memo } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Markdown } from "../components/Markdown";
import { OfflineNotice } from "../components/OfflineNotice";
import { Sheet } from "../components/Sheet";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConnection, useWritable } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { checklistLabels, checklistLines, memoDay, toggleChecklistLine } from "../lib/memoText";
import page from "../styles/page.module.css";
import styles from "./MemoEditor.module.css";
import { memoHref } from "./Memos";

type Area = NonNullable<Memo["area"]>;
const AREAS = Object.keys(copy.areas) as Area[];
const SAVE_AFTER_MS = 1000;
const BODY_MAX = 20000;

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

  const isDirty = () => {
    const s = saved.current;
    return textRef.current !== s.body || (areaTouched.current && areaRef.current !== s.area);
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
  }, []);

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

  const saveOnce = useCallback(async (): Promise<boolean> => {
    if (!isDirty()) return true;
    const body = textRef.current;
    const a = areaRef.current;
    const s = saved.current;
    if (!body.trim()) return false; // the BE takes no empty memo; nothing to keep
    if (body.length > BODY_MAX) {
      if (alive.current) setTooLong(true);
      return false;
    }
    if (!writableRef.current) return false; // offline: the draft holds it
    failure.current = null;
    if (s.id === null) {
      const out = await runAction("create_memo", a !== null ? { body, area: a } : { body });
      if (out.kind === "applied") {
        const r = out.result as MemoResult;
        saved.current = { id: r.id, body, area: r.area, updatedAt: r.updated_at };
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

  const save = useCallback(async (): Promise<boolean> => {
    if (inFlight.current) {
      again.current = true;
      await inFlight.current;
      return !isDirty();
    }
    let ok = true;
    const run = (async () => {
      do {
        again.current = false;
        ok = await saveOnce();
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
    if (text.length <= BODY_MAX) setTooLong(false);
    if (mode !== "write") return;
    const t = setTimeout(() => void saveRef.current(), SAVE_AFTER_MS);
    return () => clearTimeout(t);
  }, [text, area, mode]);

  // Leaving: the tab goes to the background, or the screen goes away.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") void saveRef.current();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      alive.current = false;
      void saveRef.current();
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
          if (r.kind === "error" && r.status === 404 && alive.current) {
            dropDraft(id);
            saved.current = { ...saved.current, body: textRef.current, area: areaRef.current }; // nothing left to save
            areaTouched.current = false;
            void router.replace("/memos/");
          }
        });
      }),
    [toast, router],
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

  const done = async () => {
    const ok = await save();
    if (!alive.current) return;
    if (!ok && failure.current) toast.show({ text: failureText(failure.current) });
    if (saved.current.id === null) {
      if (!textRef.current.trim()) void router.push("/memos/");
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
        <div className={styles.tools} role="toolbar" aria-label={copy.memos.toolbar.label}>
          <button type="button" className={styles.tool} disabled={!writable} onMouseDown={keep} onClick={() => tool("- ")}>
            {copy.memos.toolbar.list}
          </button>
          <button type="button" className={styles.tool} disabled={!writable} onMouseDown={keep} onClick={() => tool("- [ ] ")}>
            {copy.memos.toolbar.checkbox}
          </button>
          <button type="button" className={`${styles.tool} ${styles.bold}`} disabled={!writable} onMouseDown={keep} onClick={bold}>
            {copy.memos.toolbar.bold}
          </button>
          <button type="button" className={styles.tool} disabled={!writable} onClick={() => setAreaOpen(true)}>
            {copy.memos.toolbar.area}
            {area && <span className={`area-dot ${styles.toolDot}`} data-area={area} aria-hidden="true" />}
          </button>
          <button type="button" className={`${styles.tool} ${styles.done}`} disabled={!writable} onClick={() => void done()}>
            {copy.memos.toolbar.done}
          </button>
        </div>
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
      {body}
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

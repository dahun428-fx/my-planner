import { useCallback, useEffect, useRef, useState } from "react";
import { failureText, useAction } from "../api/actions";
import { apiGet } from "../api/client";
import type { Moment, MomentsList } from "../api/types.gen";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Group } from "../components/Group";
import { Pictogram } from "../components/pictograms.gen";
import { SwipeRow } from "../components/SwipeRow";
import { useToast } from "../components/Toast";
import { useWritable } from "../lib/ConnectionProvider";
import { copy, momentDay } from "../lib/copy";
import { addDays } from "../lib/time";
import styles from "./Status.module.css";

const T = copy.statusScreen;
const FOLD_MS = 200;
const OLDER_DAYS = 14;

/** The moments by day, in the order they came (newest day first, a day's own order kept). */
function byDay(moments: Moment[]): { date: string; items: Moment[] }[] {
  const days: { date: string; items: Moment[] }[] = [];
  for (const m of moments) {
    const last = days.at(-1);
    if (last && last.date === m.date) last.items.push(m);
    else days.push({ date: m.date, items: [m] });
  }
  return days;
}

function Face({ moment }: { moment: Moment }) {
  return (
    <span className={styles.face}>
      <Pictogram name={moment.area ?? "memory"} size={20} />
    </span>
  );
}

// SP8 10.2: the moments the assistant leaves at the end of a day, one paper under a date head per day.
// A row swipes (or opens a sheet) to hide or delete it; hidden ones wait in a folded group and can
// come back. The moment's text is private: it goes to the screen only, never to a log.
export function StatusMoments({ moments, hiddenCount, onChanged }: { moments: Moment[]; hiddenCount: number; onChanged: () => void }) {
  const writable = useWritable();
  const toast = useToast();
  const { run } = useAction();
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  const [closing, setClosing] = useState<ReadonlySet<number>>(new Set());
  const [gone, setGone] = useState<ReadonlySet<number>>(new Set());
  const [older, setOlder] = useState<Moment[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [noMore, setNoMore] = useState(false);
  const [open, setOpen] = useState(false);
  const [hiddenList, setHiddenList] = useState<Moment[] | null>(null);
  const [again, setAgain] = useState(0);
  const [ask, setAsk] = useState<{ id: number; token: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // An undo (the toast's 되돌리기) puts rows back: forget what was folded and read the hidden group again.
  useEffect(
    () =>
      toast.onUndone(() => {
        setClosing(new Set());
        setGone(new Set());
        setAgain((n) => n + 1);
        onChangedRef.current();
      }),
    [toast],
  );

  // The hidden group reads when it opens and again when the count (or an undo) says it changed.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    void apiGet<MomentsList>("/moments?include_hidden=true", "MomentsList").then((r) => {
      if (!alive) return;
      if (r.kind === "ok") setHiddenList(r.data.items.filter((m) => m.hidden));
      else toast.show({ text: failureText(r) });
    });
    return () => {
      alive = false;
    };
  }, [open, hiddenCount, again, toast]);

  const fold = useCallback((id: number) => {
    setClosing((c) => new Set(c).add(id));
    setTimeout(() => setGone((g) => new Set(g).add(id)), FOLD_MS);
  }, []);

  const hide = async (m: Moment) => {
    const out = await run("hide_moment", { id: m.id }, { quiet: true });
    if (out?.kind === "applied") {
      fold(m.id);
      toast.show({ text: T.hidden, undoId: out.undoId });
      onChanged();
    } else if (out?.kind === "conflict" || out?.kind === "failed") onChanged();
  };

  const unhide = async (m: Moment) => {
    const out = await run("unhide_moment", { id: m.id }, { quiet: true });
    if (out?.kind === "applied") {
      setHiddenList((l) => (l ? l.filter((x) => x.id !== m.id) : l));
      toast.show({ text: T.unhidden, undoId: out.undoId });
      onChanged();
    } else if (out?.kind === "conflict" || out?.kind === "failed") onChanged();
  };

  const remove = async (m: Moment) => {
    const out = await run("delete_moment", { id: m.id });
    if (out?.kind === "needs_confirm") setAsk({ id: m.id, token: out.confirmToken });
    else if (out?.kind === "applied") {
      fold(m.id);
      onChanged();
    } else if (out?.kind === "conflict" || out?.kind === "failed") onChanged();
  };

  const confirmDelete = async () => {
    if (!ask || busy) return;
    setBusy(true);
    const out = await run("delete_moment", { id: ask.id }, { confirmToken: ask.token });
    setBusy(false);
    setAsk(null);
    if (out?.kind === "applied") {
      fold(ask.id);
      setHiddenList((l) => (l ? l.filter((x) => x.id !== ask.id) : l));
    }
    if (out?.kind === "applied" || out?.kind === "conflict" || out?.kind === "failed") onChanged();
  };

  const shown = [...moments, ...older.filter((o) => !moments.some((m) => m.id === o.id))].filter((m) => !gone.has(m.id));
  const earliest = [...moments, ...older].map((m) => m.date).sort()[0] ?? null;

  const loadOlder = async () => {
    // The first page asks from the day after the earliest shown day, so that day comes whole again: `GET /status`
    // stops at 20 moments and can cut a day in the middle. The rows already shown drop out by id below.
    const before = cursor ?? (earliest === null ? null : addDays(earliest, 1));
    if (loadingOlder) return;
    setLoadingOlder(true);
    // Nothing shown yet (a quiet week): ask for the last 14 days up to today, then page back from its `from`.
    const path = before === null ? `/moments?days=${OLDER_DAYS}` : `/moments?before=${before}&days=${OLDER_DAYS}`;
    const r = await apiGet<MomentsList>(path, "MomentsList");
    setLoadingOlder(false);
    if (r.kind === "ok") {
      // Nothing new (all already shown, or none): say so once, quietly, and keep the button.
      const fresh = r.data.items.filter((m) => !older.some((x) => x.id === m.id) && !moments.some((x) => x.id === m.id));
      setNoMore(fresh.length === 0);
      setOlder((o) => [...o, ...r.data.items.filter((m) => !o.some((x) => x.id === m.id))]);
      setCursor(r.data.from);
    } else toast.show({ text: failureText(r) });
  };

  return (
    <>
      <Group
        paper
        heading={
          <span className={styles.headWithIcon}>
            <Pictogram name="memory" size={16} />
            {T.momentsHeading}
          </span>
        }
      >
        {shown.length === 0 ? (
          <p className={styles.empty}>{T.momentsEmpty}</p>
        ) : (
          byDay(shown).map((day) => (
            <div key={day.date} className={styles.day}>
              <h3 className={styles.dayHead}>{momentDay(day.date)}</h3>
              <ul className={styles.list}>
                {day.items.map((m) => (
                  <li key={m.id} className={`${styles.collapse} ${closing.has(m.id) ? styles.closing : ""}`} data-area={m.area ?? undefined}>
                    <div className={styles.collapseInner}>
                      <SwipeRow
                        actions={[
                          { label: T.hide, tone: "neutral", onPress: () => void hide(m) },
                          { label: T.delete, tone: "negative", onPress: () => void remove(m) },
                        ]}
                        disabled={!writable}
                        moreLabel={`${T.more}, ${m.text}`}
                        moreVisible
                      >
                        <div className={styles.momentRow}>
                          <Face moment={m} />
                          <span className={styles.momentText}>{m.text}</span>
                        </div>
                      </SwipeRow>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
        <button type="button" className={styles.textButton} disabled={loadingOlder} onClick={() => void loadOlder()}>
          {T.older}
        </button>
        {noMore && (
          <p className={styles.empty} role="status">
            {T.olderNone}
          </p>
        )}
        {hiddenCount > 0 && (
          <div className={styles.hiddenGroup}>
            <button type="button" className={styles.textButton} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
              {T.hiddenGroup(hiddenCount)}
            </button>
            {open && hiddenList !== null && (
              <ul className={styles.list}>
                {hiddenList.map((m) => (
                  <li key={m.id} className={styles.hiddenItem} data-area={m.area ?? undefined}>
                    <Face moment={m} />
                    <span className={styles.momentText}>{m.text}</span>
                    {writable && (
                      <button type="button" className={styles.inlineAction} onClick={() => void unhide(m)}>
                        {T.unhide}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Group>
      {ask && (
        <ConfirmSheet
          summary={T.deleteAsk}
          keepLabel={T.deleteKeep}
          changeLabel={T.deleteGo}
          busy={busy}
          onKeep={() => setAsk(null)}
          onChange={() => void confirmDelete()}
        />
      )}
    </>
  );
}

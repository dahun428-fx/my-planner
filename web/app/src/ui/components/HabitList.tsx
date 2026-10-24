import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../../api/client";
import type { Habit, HabitsList } from "../../api/types.gen";
import { useToast } from "../../components/Toast";
import { copy, habitMeta } from "../../lib/copy";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { CheckRow, Part } from "./Part";
import styles from "./parts.module.css";

const isHabit = (v: unknown): v is Habit =>
  typeof v === "object" && v !== null && typeof (v as Habit).id === "number" && typeof (v as Habit).checked === "boolean" && typeof (v as Habit).week_count === "number";

/**
 * The habit rows (SP7 6.1, 9장), the same on Today, in a check-in card and in chat. A press checks
 * or unchecks that day at once (no confirm: the toast carries "되돌리기"); a checked row only fills
 * its circle, the title stays as it is. `readOnly`: offline, a restored chat card, a snapshot.
 *
 * After "되돌리기" (which may be this list's write, another one, or something else entirely: the
 * toast does not say which) the rows must show the truth, never the props they started from. A
 * caller that reads again on undo itself (Today) leaves `readsOnUndo` off; a card (chat, check-in)
 * turns it on and reads `GET /habits` for its date. If that read fails, the rows stay as they are.
 */
export function HabitList({
  habits,
  date,
  readOnly,
  onChanged,
  readsOnUndo = false,
}: {
  habits: Habit[];
  date: string;
  readOnly: boolean;
  onChanged: () => void;
  readsOnUndo?: boolean;
}) {
  const act = usePartAction();
  // The BE's answer ({habit, date, already}) until the rows are read again.
  const [answered, setAnswered] = useState<ReadonlyMap<number, Habit>>(new Map());
  // The rows read after an undo (cards only), until the caller hands new ones.
  const [reread, setReread] = useState<Habit[] | null>(null);
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());
  const inFlight = useRef(new Set<number>());
  useEffect(() => {
    setAnswered(new Map());
    setReread(null);
  }, [habits]);

  const toast = useToast();
  const dateRef = useRef(date);
  dateRef.current = date;
  useEffect(() => {
    if (!readsOnUndo) return;
    let alive = true;
    const off = toast.onUndone(() => {
      const q = new URLSearchParams({ date: dateRef.current, status: "active" });
      void apiGet<HabitsList>(`/habits?${q.toString()}`, "HabitsList").then((r) => {
        if (!alive || r.kind !== "ok") return; // offline or refused: keep what is shown
        setReread(r.data.items);
        setAnswered(new Map());
      });
    });
    return () => {
      alive = false;
      off();
    };
  }, [toast, readsOnUndo]);

  const rows = reread ?? habits;
  if (rows.length === 0) {
    return (
      <Link href="/habits/" className={styles.habitAdd}>
        {copy.habits.addRow}
      </Link>
    );
  }

  const press = async (h: Habit) => {
    if (inFlight.current.has(h.id)) return; // the answer to the first press has not come yet
    inFlight.current.add(h.id);
    setBusy(new Set(inFlight.current));
    try {
      const out = await act(h.checked ? "uncheck_habit" : "check_habit", { id: h.id, date });
      if (out?.kind !== "applied") return;
      const r = out.result as { habit?: unknown } | null;
      const next = isHabit(r?.habit) && r.habit.id === h.id ? r.habit : { ...h, checked: !h.checked };
      setAnswered((m) => new Map(m).set(h.id, next));
      onChanged();
    } finally {
      inFlight.current.delete(h.id);
      setBusy(new Set(inFlight.current));
    }
  };

  return (
    <ul className={`${styles.rows} ${styles.habitRows} ${readOnly ? styles.readOnly : ""}`}>
      {rows.map((given) => {
        const h = answered.get(given.id) ?? given;
        return (
          <CheckRow
            key={h.id}
            title={h.title}
            checked={h.checked}
            meta={habitMeta(h)}
            disabled={readOnly || busy.has(h.id)}
            onToggle={() => void press(h)}
          />
        );
      })}
    </ul>
  );
}

/** `ui_habit_check {date}` (SP7 9장). Without `data.habits` it is one line to the habits screen. */
export function HabitCheck({ props, data, ctx }: PartProps<{ date: string }>) {
  const habits = data?.habits;
  if (!habits) {
    return (
      <Part>
        <Link href="/habits/" className={styles.habitAdd}>
          {copy.habits.todayLine}
        </Link>
      </Part>
    );
  }
  // A restored card shows rows as they were: they may have changed since, so it writes nothing.
  const readOnly = ctx.readOnly || ctx.restored === true;
  return (
    <Part title={copy.habits.heading} readOnly={ctx.readOnly}>
      <HabitList habits={habits} date={props.date} readOnly={readOnly} onChanged={ctx.onAfterAction} readsOnUndo />
    </Part>
  );
}

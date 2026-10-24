import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { Habit } from "../../api/types.gen";
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
 */
export function HabitList({ habits, date, readOnly, onChanged }: { habits: Habit[]; date: string; readOnly: boolean; onChanged: () => void }) {
  const act = usePartAction();
  // The BE's answer ({habit, date, already}) until the caller reads again (a chat card never does).
  const [answered, setAnswered] = useState<ReadonlyMap<number, Habit>>(new Map());
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());
  const inFlight = useRef(new Set<number>());
  useEffect(() => setAnswered(new Map()), [habits]);
  // "되돌리기" on the toast: drop the answers kept here (a chat card falls back to the rows it was
  // given) and let the caller read again (a check-in does not listen to the toast itself).
  const toast = useToast();
  const changed = useRef(onChanged);
  changed.current = onChanged;
  useEffect(
    () =>
      toast.onUndone(() => {
        setAnswered(new Map());
        changed.current();
      }),
    [toast],
  );

  if (habits.length === 0) {
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
      {habits.map((given) => {
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
      <HabitList habits={habits} date={props.date} readOnly={readOnly} onChanged={ctx.onAfterAction} />
    </Part>
  );
}

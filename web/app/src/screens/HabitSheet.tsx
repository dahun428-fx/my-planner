import { useId, useRef, useState } from "react";
import { useAction } from "../api/actions";
import type { Habit } from "../api/types.gen";
import { Segmented } from "../components/Segmented";
import { Sheet } from "../components/Sheet";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
// The same fields, pills and buttons as the to-do add sheet.
import styles from "./AddTodoSheet.module.css";

type Area = Habit["area"];
type Kind = Habit["kind"];
const AREAS = Object.keys(copy.areas) as Area[];
const TARGETS = [1, 2, 3, 4, 5, 6] as const;
/** The BE's limit (SP7 H1), in code points as it counts them: an emoji is one character. */
const TITLE_MAX = 40;

const capTitle = (v: string) => {
  const chars = [...v];
  return chars.length > TITLE_MAX ? chars.slice(0, TITLE_MAX).join("") : v;
};

export interface HabitSheetProps {
  open: boolean;
  onClose(): void;
  /** The habit to change ("저장" = update_habit); none adds one ("추가" = add_habit). */
  habit?: Habit | null;
  /** Called after the BE applied it, so the screen can read again. */
  onSaved?(): void;
}

// SP7 6.2 add and edit sheet: title (needed, 40 characters), one of the six areas, "매일" · "주 N회",
// and for 주 N회 a number from 1 to 6.
export function HabitSheet({ open, onClose, habit = null, onSaved }: HabitSheetProps) {
  return (
    <Sheet open={open} onClose={onClose} title={habit ? copy.habits.editTitle : copy.habits.add}>
      <HabitForm key={habit?.id ?? "new"} habit={habit} onClose={onClose} onSaved={onSaved} />
    </Sheet>
  );
}

function HabitForm({ habit, onClose, onSaved }: { habit: Habit | null; onClose(): void; onSaved?(): void }) {
  const { run } = useAction();
  const toast = useToast();
  const titleId = useId();
  const [title, setTitle] = useState(habit?.title ?? "");
  const [area, setArea] = useState<Area | null>(habit?.area ?? null);
  const [kind, setKind] = useState<Kind>(habit?.kind ?? "daily");
  const [target, setTarget] = useState<number | null>(habit?.target_per_week ?? null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  const trimmed = title.trim();
  const valid = trimmed !== "" && area !== null && (kind === "daily" || target !== null);

  // Only what changed goes to update_habit: the BE keeps the rest (and clears the target for 매일).
  const changes = (): Record<string, unknown> => {
    if (!habit) return {};
    const out: Record<string, unknown> = {};
    if (trimmed !== habit.title) out.title = trimmed;
    if (area !== habit.area) out.area = area;
    if (kind !== habit.kind || (kind === "weekly" && target !== habit.target_per_week)) {
      out.kind = kind;
      if (kind === "weekly") out.target_per_week = target;
    }
    return out;
  };
  const changed = habit === null || Object.keys(changes()).length > 0;

  const submit = async () => {
    if (!valid || !changed || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const out = habit
        ? await run("update_habit", { id: habit.id, ...changes() })
        : await run("add_habit", { title: trimmed, area, kind, ...(kind === "weekly" ? { target_per_week: target } : {}) });
      if (out === null) return;
      if (out.kind === "applied") {
        onSaved?.();
        onClose();
      } else if (out.kind === "conflict" || out.kind === "needs_confirm") {
        toast.show({ text: copy.actions.failed });
      }
      // rejected and failed: useAction said why; the sheet stays so it can be fixed.
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className={styles.field}>
        <label className={styles.label} htmlFor={titleId}>
          {copy.habits.titleLabel}
        </label>
        <input id={titleId} className={styles.input} type="text" value={title} onChange={(e) => setTitle(capTitle(e.target.value))} autoComplete="off" />
      </div>
      <div className={styles.field}>
        <span className={styles.label}>{copy.habits.areaLabel}</span>
        <div className={styles.pills} role="group" aria-label={copy.habits.areaLabel}>
          {AREAS.map((a) => (
            <button key={a} type="button" className={`${styles.pill} ${area === a ? styles.picked : ""}`} aria-pressed={area === a} onClick={() => setArea(a)}>
              {copy.areas[a]}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.field}>
        <span className={styles.label}>{copy.habits.cadenceLabel}</span>
        <Segmented<Kind>
          ariaLabel={copy.habits.cadenceLabel}
          value={kind}
          onChange={setKind}
          options={[
            { value: "daily", label: copy.habits.daily },
            { value: "weekly", label: copy.habits.weekly },
          ]}
        />
        {kind === "weekly" && (
          <div className={styles.pills} role="group" aria-label={copy.habits.targetLabel}>
            {TARGETS.map((n) => (
              <button key={n} type="button" className={`${styles.pill} ${target === n ? styles.picked : ""}`} aria-pressed={target === n} onClick={() => setTarget(n)}>
                {n}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className={styles.buttons}>
        <button type="button" className={styles.cancel} onClick={onClose}>
          {copy.habits.close}
        </button>
        <button type="submit" className={styles.submit} disabled={!valid || !changed || busy}>
          {habit ? copy.habits.save : copy.habits.addSubmit}
        </button>
      </div>
    </form>
  );
}

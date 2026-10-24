import { useState } from "react";
import { copy } from "../../lib/copy";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { Part } from "./Part";
import styles from "./parts.module.css";

const SCORES = [1, 2, 3, 4, 5];

// ui_condition_picker: 1-5 pills and an optional note. The note is sent when the field is left,
// as the same action again with the same score.
export function ConditionPicker({ props, ctx }: PartProps<{ date: string }>) {
  const act = usePartAction();
  const [score, setScore] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [sentNote, setSentNote] = useState("");

  const record = async (n: number, withNote: string) => {
    const args: Record<string, unknown> = { date: props.date, score: n };
    if (withNote) args.note = withNote;
    const out = await act("record_condition", args);
    if (out?.kind === "applied") {
      setScore(n);
      if (withNote) setSentNote(withNote);
      ctx.onAfterAction();
    }
  };
  const leaveNote = () => {
    const text = note.trim();
    if (score === null || text === "" || text === sentNote) return;
    void record(score, text);
  };

  return (
    <Part readOnly={ctx.readOnly}>
      <div className={styles.pills}>
        {SCORES.map((n) => (
          <button
            key={n}
            type="button"
            className={styles.pill}
            aria-label={copy.today.conditionScore(n)}
            aria-pressed={score === n}
            disabled={ctx.readOnly}
            onClick={() => void record(n, note.trim())}
          >
            {n}
          </button>
        ))}
      </div>
      <div className={styles.ends}>
        <span>{copy.parts.scoreLow}</span>
        <span>{copy.parts.scoreHigh}</span>
      </div>
      <input
        type="text"
        className={styles.note}
        aria-label={copy.parts.noteLabel}
        placeholder={copy.parts.notePlaceholder}
        value={note}
        disabled={ctx.readOnly}
        onChange={(e) => setNote(e.target.value)}
        onBlur={leaveNote}
      />
    </Part>
  );
}

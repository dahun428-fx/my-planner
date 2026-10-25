import { useState } from "react";
import { copy } from "../../lib/copy";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { Part } from "./Part";
import styles from "./parts.module.css";

const FIRST_ROW = [0, 1, 2, 3, 4, 5];
const SECOND_ROW = [6, 7, 8, 9, 10];

// ui_ladder_picker: 0-10 in two rows (6 + 5) for "지금" or "5년 뒤".
export function LadderPicker({ props, ctx }: PartProps<{ period: string; field: "now" | "future" }>) {
  const act = usePartAction();
  const [score, setScore] = useState<number | null>(null);
  const record = async (n: number) => {
    const out = await act("record_ladder_score", { period: props.period, [props.field]: n });
    if (out?.kind === "applied") {
      setScore(n);
      ctx.onAfterAction();
    }
  };
  const row = (nums: number[]) => (
    <div className={styles.pills}>
      {nums.map((n) => (
        <button key={n} type="button" className={`${styles.pill} pressable`} aria-label={copy.parts.ladderScore(n)} aria-pressed={score === n} disabled={ctx.readOnly} onClick={() => void record(n)}>
          {n}
        </button>
      ))}
    </div>
  );
  return (
    <Part readOnly={ctx.readOnly}>
      <p className={styles.text}>{copy.parts.ladderPrompt(props.field)}</p>
      {row(FIRST_ROW)}
      {row(SECOND_ROW)}
      <div className={styles.ends}>
        <span>{props.field === "now" ? copy.parts.ladderNow : copy.parts.ladderFuture}</span>
      </div>
    </Part>
  );
}

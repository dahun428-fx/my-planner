import type { AgentNote } from "../lib/agentNotes";
import { copy } from "../lib/copy";
import styles from "./AgentNoteLines.module.css";
import { Pictogram } from "./pictograms.gen";

export interface AgentNoteLine extends AgentNote {
  /** A meta line after the text (the more screen's "M/D"). */
  meta?: string;
}

// SP14 10장: a partner's observation, its pictogram (운동메이트 = dumbbell, 라이프 매니저 = compass) beside
// its name. The name is there in letters, so the pictogram is aria-hidden (DESIGN.md Pictograms 3).
export function AgentNoteLines({ notes }: { notes: AgentNoteLine[] }) {
  if (notes.length === 0) return null;
  return (
    <ul className={styles.notes}>
      {notes.map((n, i) => (
        <li key={i} className={styles.note}>
          <span className={styles.mark}>
            <Pictogram name={n.agent === "mate" ? "dumbbell" : "compass"} size={20} />
          </span>
          <span className={styles.body}>
            <span className={styles.name}>{copy.agentNames[n.agent]}</span>
            <span className={styles.text}>{n.text}</span>
            {n.meta !== undefined && <span className={`${styles.meta} tnum`}>{n.meta}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

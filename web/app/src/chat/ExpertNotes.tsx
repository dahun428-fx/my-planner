import { Markdown } from "../components/Markdown";
import { type ExpertKey, copyPanel } from "../lib/copyPanel";
import type { ExpertNote } from "./parts";
import styles from "./ExpertNotes.module.css";

const nameOf = (key: string): string | null =>
  key in copyPanel.experts ? copyPanel.experts[key as ExpertKey] : null;

// SP15 1장 2, 11장: under a life manager answer, one folded line "전문가 소견 n개"; open, each
// expert's name (bold) and its note as Markdown, in the order they were asked. The stream's
// data-expert-notes and the history's expert_notes draw the same. No notes: nothing.
export function ExpertNotes({ notes }: { notes: ExpertNote[] }) {
  if (notes.length === 0) return null;
  return (
    <details className={styles.fold}>
      <summary>{copyPanel.expertNotes(notes.length)}</summary>
      <ul>
        {notes.map((n, i) => {
          const name = nameOf(n.expert);
          return (
            <li key={i}>
              {name && <strong>{name}</strong>}
              <Markdown text={n.text} />
            </li>
          );
        })}
      </ul>
    </details>
  );
}

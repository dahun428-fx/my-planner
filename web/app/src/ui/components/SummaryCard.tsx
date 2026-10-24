import type { PartProps } from "../types";
import { Part } from "./Part";
import styles from "./parts.module.css";

const MAX_LINES = 8;

// ui_summary_card: a title and up to 8 lines. No buttons.
export function SummaryCard({ props }: PartProps<{ title: string; lines: string[] }>) {
  return (
    <Part title={props.title}>
      <ul className={styles.lines}>
        {props.lines.slice(0, MAX_LINES).map((l, i) => (
          <li key={i}>{l}</li>
        ))}
      </ul>
    </Part>
  );
}

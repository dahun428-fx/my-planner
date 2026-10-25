import { copy } from "../../lib/copy";
import styles from "./primitives.module.css";

/**
 * One check row (SP6 spec 5.3.5): ui_todo_list, ui_todo_draft, todo_rows, ui_period_list and the
 * habit rows all draw this. It knows nothing about to-dos; what a press does is the card's to say.
 * `mark` (gap 1): "circle" is the 44px checkbox, "dot" a row that cannot be checked here, "none"
 * a row with no mark at all (a dropped to-do). `struck` greys the title and strikes it through.
 * The row is an <li>: put it in a <ul>.
 */
export function CheckRow({
  title,
  meta,
  checked,
  disabled,
  struck = false,
  highlight = false,
  mark = "circle",
  onToggle,
}: {
  title: string;
  meta?: string | null;
  checked: boolean;
  disabled: boolean;
  struck?: boolean;
  highlight?: boolean;
  mark?: "circle" | "dot" | "none";
  onToggle(): void;
}) {
  return (
    <li className={`${styles.checkRow} ${highlight ? styles.highlight : ""}`}>
      {mark === "circle" ? (
        <button type="button" role="checkbox" aria-checked={checked} aria-label={copy.parts.checkLabel(title)} className={`${styles.check} pressable`} disabled={disabled} onClick={onToggle}>
          <span className={styles.circle} />
        </button>
      ) : (
        <span className={styles.mark} aria-hidden="true">
          {mark === "dot" && <span className={styles.dot} />}
        </span>
      )}
      <span className={`${styles.rowTitle} ${struck ? styles.struck : ""}`}>{title}</span>
      {meta != null && <span className={styles.rowMeta}>{meta}</span>}
      {highlight && <span className={styles.srOnly}>{copy.parts.changedBySecretary}</span>}
    </li>
  );
}

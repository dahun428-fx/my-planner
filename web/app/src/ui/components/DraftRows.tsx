import { useState } from "react";
import type { ActionName } from "../../api/actions";
import { copy } from "../../lib/copy";
import type { PartContext } from "../types";
import { usePartAction } from "../usePartAction";
import { Part } from "./Part";
import styles from "./parts.module.css";

export type DraftRow = { id: number; title: string; when: string };

// The body shared by ui_milestone_draft and ui_chapter_draft: a bordered group with one line per
// draft and "빼기" · "확정" on each line. A line that was handled leaves the list. A group restored
// after a reload shows its lines only (they may have been handled since).
export function DraftRows({
  heading,
  fallback,
  rows,
  confirmAction,
  dropAction,
  ctx,
}: {
  heading: string;
  fallback: string;
  rows: DraftRow[] | null;
  confirmAction: ActionName;
  dropAction: ActionName;
  ctx: PartContext;
}) {
  const act = usePartAction();
  const [handled, setHandled] = useState<ReadonlySet<number>>(new Set());

  if (!rows) {
    return (
      <Part title={heading} variant="outlined">
        <p className={styles.text}>{fallback}</p>
      </Part>
    );
  }
  const send = async (row: DraftRow, action: ActionName, args: object) => {
    const out = await act(action, args);
    if (out?.kind === "applied") {
      setHandled((h) => new Set(h).add(row.id));
      ctx.onAfterAction();
    }
  };
  return (
    <Part title={heading} variant="outlined" readOnly={ctx.readOnly}>
      <ul className={styles.rows}>
        {rows
          .filter((r) => !handled.has(r.id))
          .map((r) => (
            <li key={r.id} className={styles.draftRow}>
              <p className={styles.draftTitle}>{r.title}</p>
              <p className={styles.draftWhen}>{r.when}</p>
              {!ctx.restored && (
                <div className={styles.buttons}>
                  <button type="button" className={styles.button} disabled={ctx.readOnly} onClick={() => void send(r, dropAction, { id: r.id })}>
                    {copy.parts.drop}
                  </button>
                  <button type="button" className={`${styles.button} ${styles.primary}`} disabled={ctx.readOnly} onClick={() => void send(r, confirmAction, { ids: [r.id] })}>
                    {copy.parts.confirmOne}
                  </button>
                </div>
              )}
            </li>
          ))}
      </ul>
    </Part>
  );
}

/** "2024-03" or "2024-03-15" -> "2024년 3월" */
export function monthText(value: string): string {
  const [y, m] = value.split("-").map(Number);
  return Number.isFinite(y) && Number.isFinite(m) ? copy.parts.yearMonth(y, m) : value;
}

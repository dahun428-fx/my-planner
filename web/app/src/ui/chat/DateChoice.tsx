import { useRef, useState } from "react";
import { ConfirmSheet } from "../../components/ConfirmSheet";
import { useToast } from "../../components/Toast";
import { copy } from "../../lib/copy";
import { Part } from "../components/Part";
import { candidateLabel } from "../primitives/dates";
import { MiniText } from "../primitives/MiniText";
import primitives from "../primitives/primitives.module.css";
import type { PartProps } from "../types";
import { type NeedsConfirm, usePartAction } from "../usePartAction";
import styles from "./cards.module.css";

type Props = { task_id: number; question: string; candidates: { date: string; note?: string | null }[] };
type Asking = { date: string; token: string; summary: string };

/**
 * ui_date_choice (SP6 6.2): the question, the to-do's title, one wide button per candidate date and
 * "다른 날로 할게요". A candidate is `move_task {id: data.todo.id, planned_for}` (8 `confirm`): every
 * button is off while it is in flight; applied leaves only the chosen one dark. A to-do that got a
 * time meanwhile comes back `needs_confirm`: the same sheet as on the to-do screen asks first.
 * Rejected or failed: useAction's toast says why and the buttons are on again.
 */
export function DateChoice({ props, data, ctx }: PartProps<Props>) {
  const act = usePartAction();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [asking, setAsking] = useState<Asking | null>(null);
  const [sent, setSent] = useState(false);
  const lock = useRef(false);

  if (data === undefined) {
    return (
      <Part>
        <MiniText md={props.question} />
        <p className={styles.sub}>{copy.parts.todoCount(1)}</p>
      </Part>
    );
  }
  const todo = data.todo;
  if (!todo || todo.status !== "open") {
    return (
      <Part>
        <MiniText md={props.question} />
        <p className={styles.sub}>{copy.parts.alreadySettled}</p>
      </Part>
    );
  }

  const off = ctx.readOnly || ctx.restored === true || busy || chosen !== null || sent || asking !== null;

  // A 409 to "바꾸기" is the question's token gone stale (10 minutes), not a failure.
  const expired = () => toast.show({ text: copy.todos.confirmExpired });

  const move = async (date: string, confirmToken?: string) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const onNeedsConfirm = (o: NeedsConfirm) => setAsking({ date, token: o.confirmToken, summary: o.summary });
      const out = await act("move_task", { id: todo.id, planned_for: date }, { confirmToken, onNeedsConfirm, onConflict: confirmToken === undefined ? undefined : expired });
      if (out?.kind !== "needs_confirm") setAsking(null);
      // A refusal with no sentence of its own is not said by useAction.
      if (out?.kind === "rejected" && out.message === "") toast.show({ text: copy.actions.failed });
      if (out?.kind === "applied") {
        setChosen(date);
        ctx.onAfterAction();
      }
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  const otherDay = () => {
    if (off || !ctx.onChoose) return;
    setSent(true);
    ctx.onChoose(copy.parts.otherDay);
  };

  return (
    <Part readOnly={ctx.readOnly}>
      <MiniText md={props.question} />
      <p className={styles.todoTitle}>{todo.title}</p>
      <div className={styles.candidates}>
        {props.candidates.map((c) => (
          <button
            key={c.date}
            type="button"
            className={styles.candidate}
            aria-pressed={chosen === c.date}
            disabled={off}
            onClick={() => void move(c.date)}
          >
            <span className={styles.candidateDay}>{candidateLabel(c.date, data.today)}</span>
            {c.note && (
              <>
                {" "}
                <span className={styles.candidateNote}>{c.note}</span>
              </>
            )}
          </button>
        ))}
        <button type="button" className={primitives.pill} disabled={off || !ctx.onChoose} onClick={otherDay}>
          {copy.parts.otherDay}
        </button>
      </div>
      {asking && (
        <ConfirmSheet summary={asking.summary} busy={busy} onKeep={() => setAsking(null)} onChange={() => void move(asking.date, asking.token)} />
      )}
    </Part>
  );
}

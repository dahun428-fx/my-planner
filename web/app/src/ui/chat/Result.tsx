import { Fragment, useState } from "react";
import { type UndoBlockReason, useUndo } from "../../api/actions";
import { copy } from "../../lib/copy";
import { formatKst } from "../../lib/time";
import { Part } from "../components/Part";
import { dayLabel } from "../primitives/dates";
import { Divider } from "../primitives/Divider";
import primitives from "../primitives/primitives.module.css";
import type { PartProps, ResultItem, TodoSnap } from "../types";
import styles from "./cards.module.css";

type UndoState = { kind: "idle" } | { kind: "done" } | { kind: "blocked"; reason: UndoBlockReason };

const time = (iso: string) => formatKst(iso, "HH:mm");
/** A day as on the card: "10월 27일 (화)", with its time when it has one; "날짜 없음" without a day. */
const day = (s: Pick<TodoSnap, "planned_for" | "scheduled_at">) =>
  s.planned_for ? (s.scheduled_at ? `${dayLabel(s.planned_for)} ${time(s.scheduled_at)}` : dayLabel(s.planned_for)) : copy.parts.noDate;

/** "{before} → {after}": read as "이전 …, 지금 …" so the arrow is not read out (6.3). */
function Change({ from, to }: { from: string; to: string }) {
  return (
    <p className={styles.change} role="img" aria-label={copy.parts.changeAria(from, to)}>
      <span className={styles.before}>{from}</span>
      {copy.parts.arrow}
      {to}
    </p>
  );
}

/** The second line of an item (6.3 table, gap 4). */
function secondLine(it: ResultItem) {
  const { before, after } = it;
  switch (it.change) {
    case "added":
      return <p className={styles.change}>{day(after)}</p>;
    case "moved":
      return <Change from={day(before ?? after)} to={day(after)} />;
    case "updated":
      if (before?.title != null && before.title !== after.title) return <p className={styles.change}>{copy.parts.prevTitle(before.title)}</p>;
      if (before?.scheduled_at != null && after.scheduled_at != null && before.scheduled_at !== after.scheduled_at) {
        return <Change from={time(before.scheduled_at)} to={time(after.scheduled_at)} />;
      }
      if (before?.planned_for != null && before.planned_for !== after.planned_for) return <Change from={day(before)} to={day(after)} />;
      return <p className={styles.change}>{copy.parts.editedOnly}</p>;
    case "confirmed":
      return <p className={styles.change}>{copy.parts.confirmedDraft}</p>;
    default:
      return null; // completed, reopened, dropped
  }
}

function Item({ it, readOnly, restored, onUndone }: { it: ResultItem; readOnly: boolean; restored: boolean; onUndone(): void }) {
  const { undo, busy } = useUndo();
  const [state, setState] = useState<UndoState>({ kind: "idle" });
  const struck = it.change === "completed" || it.change === "dropped";

  const run = async (id: number) => {
    if (readOnly) return;
    const out = await undo(id);
    if (out?.kind === "undone" || out?.kind === "already_undone") {
      setState({ kind: "done" });
      onUndone();
    } else if (out?.kind === "blocked") setState({ kind: "blocked", reason: out.reason });
  };

  let trailing: React.ReactNode = null;
  if (state.kind === "done") trailing = <span className={styles.undoNote}>{copy.chat.undone}</span>;
  else if (state.kind === "blocked") trailing = <span className={styles.undoNote}>{copy.activity.undoBlocked[state.reason]}</span>;
  else if (it.undo_id !== null && !restored) {
    const id = it.undo_id;
    trailing = (
      <button type="button" className={styles.undo} disabled={readOnly || busy.has(id)} onClick={() => void run(id)}>
        {copy.chat.undo}
      </button>
    );
  }

  return (
    <div className={styles.item}>
      <div className={styles.itemBody}>
        <p className={styles.itemHead}>
          <span className={styles.changeChip}>{copy.parts.changeChip[it.change]}</span>
          <span className={struck ? `${styles.itemTitle} ${primitives.struck}` : styles.itemTitle}>{it.todo.title}</span>
        </p>
        {secondLine(it)}
      </div>
      {trailing}
    </div>
  );
}

/**
 * ui_result (SP6 6.3): what the secretary changed in this answer, one block per to-do, divided.
 * "되돌리기" only where the BE gave an `undo_id` (one activity on that one to-do); a restored card has
 * none. The confirmation of an undo is the toast's (useUndo).
 */
export function Result({ props, data, ctx }: PartProps<{ task_ids: number[] }>) {
  const items = data?.items;
  if (!items) {
    return (
      <Part>
        <p className={primitives.text}>{copy.parts.resultCount(props.task_ids.length)}</p>
      </Part>
    );
  }
  return (
    <Part readOnly={ctx.readOnly} restored={ctx.restored}>
      {items.map((it, i) => (
        <Fragment key={it.todo.id}>
          {i > 0 && <Divider />}
          <Item it={it} readOnly={ctx.readOnly} restored={ctx.restored === true} onUndone={ctx.onAfterAction} />
        </Fragment>
      ))}
    </Part>
  );
}

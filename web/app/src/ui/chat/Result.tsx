import { Fragment } from "react";
import { copy } from "../../lib/copy";
import { formatKst } from "../../lib/time";
import { Part } from "../components/Part";
import { dayLabel } from "../primitives/dates";
import { Divider } from "../primitives/Divider";
import primitives from "../primitives/primitives.module.css";
import type { PartProps, ResultItem, TodoSnap } from "../types";
import styles from "./cards.module.css";

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

function Item({ it }: { it: ResultItem }) {
  const struck = it.change === "completed" || it.change === "dropped";
  return (
    <div className={styles.item}>
      <div className={styles.itemBody}>
        <p className={styles.itemHead}>
          <span className={styles.changeChip}>{copy.parts.changeChip[it.change]}</span>{" "}
          <span className={struck ? `${styles.itemTitle} ${primitives.struck}` : styles.itemTitle}>{it.todo.title}</span>
        </p>
        {secondLine(it)}
      </div>
    </div>
  );
}

/**
 * ui_result (SP6 6.3): what the secretary changed in this answer, one block per to-do, divided.
 * The card shows results only (SP9 9.6): the undo is the chat toast's, then the activity screen's.
 * So it has nothing to press, and no offline reason either.
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
    <Part restored={ctx.restored}>
      {items.map((it, i) => (
        <Fragment key={it.todo.id}>
          {i > 0 && <Divider />}
          <Item it={it} />
        </Fragment>
      ))}
    </Part>
  );
}

import { useState } from "react";
import { copy } from "../../lib/copy";
import { Part } from "../components/Part";
import partStyles from "../components/parts.module.css";
import { CheckRow } from "../primitives/CheckRow";
import { Buttons } from "../primitives/Buttons";
import { dayLabel, dayTitle, isoWeekOf, rowMeta, weekTitle } from "../primitives/dates";
import primitives from "../primitives/primitives.module.css";
import type { ButtonItem } from "../primitives/types";
import type { OutsideItem, PartContext, PartProps, PartTodo } from "../types";
import { usePartAction } from "../usePartAction";
import styles from "./cards.module.css";

type Props = { day?: string; week?: string; highlight_task_ids?: number[] };

const FOLD_AT = 8;
const OUTSIDE_ORDER = ["moved", "dropped", "no_date"] as const;
const OUTSIDE_HEAD: Record<OutsideItem["reason"], string> = {
  moved: copy.parts.outsideHead.moved,
  dropped: copy.parts.outsideHead.dropped,
  no_date: copy.parts.outsideHead.noDate,
};

/** One day's rows, folded after eight. Only an open row of `data.days` completes (8장). */
function DayRows({
  todos,
  today,
  highlight,
  completed,
  off,
  onComplete,
}: {
  todos: PartTodo[];
  today: string | undefined;
  highlight: ReadonlySet<number>;
  completed: ReadonlySet<number>;
  off: boolean;
  onComplete(id: number): void;
}) {
  const [open, setOpen] = useState(false);
  const shown = todos.length > FOLD_AT && !open ? todos.slice(0, FOLD_AT) : todos;
  return (
    <>
      <ul className={primitives.checkRows}>
        {shown.map((t) => {
          const done = t.status === "done" || completed.has(t.id);
          return (
            <CheckRow
              key={t.id}
              title={t.title}
              meta={rowMeta(t, today)}
              checked={done}
              struck={done}
              disabled={off || done}
              highlight={highlight.has(t.id)}
              onToggle={() => onComplete(t.id)}
            />
          );
        })}
      </ul>
      {todos.length > FOLD_AT && (
        <button type="button" className={partStyles.more} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? copy.parts.less : copy.parts.more(todos.length - FOLD_AT)}
        </button>
      )}
    </>
  );
}

/** The rows the period does not hold (6.4): by reason, no check, no empty group. */
function Outside({ outside, highlight }: { outside: OutsideItem[]; highlight: ReadonlySet<number> }) {
  return (
    <>
      {OUTSIDE_ORDER.map((reason) => {
        const rows = outside.filter((o) => o.reason === reason);
        if (rows.length === 0) return null;
        return (
          <div key={reason} className={styles.dayGroup}>
            <p className={styles.dayHead}>{OUTSIDE_HEAD[reason]}</p>
            <ul className={primitives.checkRows}>
              {rows.map(({ todo }) => (
                <CheckRow
                  key={todo.id}
                  title={todo.title}
                  meta={reason === "moved" && todo.planned_for ? dayLabel(todo.planned_for) : null}
                  checked={false}
                  disabled
                  struck={reason === "dropped"}
                  mark={reason === "dropped" ? "none" : "dot"}
                  highlight={highlight.has(todo.id)}
                  onToggle={() => {}}
                />
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}

function openButtons(props: Props, today: string | undefined, ctx: PartContext): ButtonItem[] {
  if (!ctx.onOpen) return [];
  const items: ButtonItem[] = [];
  if (today !== undefined && props.day === today) items.push({ label: copy.parts.openTodos, do: { kind: "open", screen: "todos_day" } });
  if (today !== undefined && props.week !== undefined && props.week === isoWeekOf(today)) {
    items.push({ label: copy.parts.openTodos, do: { kind: "open", screen: "todos_week" } });
  }
  if ((props.highlight_task_ids ?? []).length > 0) items.push({ label: copy.parts.openActivity, do: { kind: "open", screen: "activity" } });
  return items;
}

/** An `open` button: the chat sheet moves to that screen (8장). */
function open(item: ButtonItem, ctx: PartContext): boolean {
  if (item.do.kind !== "open" || !ctx.onOpen) return false;
  ctx.onOpen(item.do.screen);
  return true;
}

/**
 * ui_period_list (SP6 6.4): one day or one week of to-dos as the BE read them, titled from
 * `data.today` (never the device calendar). Rows the secretary changed carry CheckRow's --hue bar.
 * A check completes (8장); there is no undo here (SP9 9.6): the chat toast and the activity
 * screen have it. Opening a screen works read-only and restored too (6.5).
 */
export function PeriodList({ props, data, ctx }: PartProps<Props>) {
  const act = usePartAction();
  const [completed, setCompleted] = useState<ReadonlySet<number>>(new Set());
  const today = data?.today;
  const title = props.day !== undefined ? dayTitle(props.day, today) : weekTitle(props.week ?? "", today);

  if (!data?.days) {
    return (
      <Part title={title}>
        <p className={primitives.text}>{copy.parts.periodFailed}</p>
      </Part>
    );
  }

  const highlight = new Set(props.highlight_task_ids ?? []);
  const off = ctx.readOnly || ctx.restored === true;
  const complete = async (id: number) => {
    if (off) return;
    const out = await act("complete_task", { id });
    if (out?.kind === "applied") {
      setCompleted((s) => new Set(s).add(id));
      ctx.onAfterAction();
    }
  };
  const rows = (todos: PartTodo[]) => <DayRows todos={todos} today={today} highlight={highlight} completed={completed} off={off} onComplete={(id) => void complete(id)} />;
  const buttons = openButtons(props, today, ctx);
  const isWeek = props.day === undefined;

  return (
    <Part title={title} readOnly={ctx.readOnly} restored={ctx.restored}>
      <div className={styles.period}>
        {isWeek
          ? data.days.map((d) =>
              d.todos.length === 0 ? (
                <p key={d.date} className={styles.dayHead}>
                  {copy.todos.emptyDay(d.weekday)}
                </p>
              ) : (
                <div key={d.date} className={styles.dayGroup}>
                  <p className={styles.dayHead}>{copy.parts.dayHead(Number(d.date.slice(8, 10)), d.weekday) + (d.is_today ? copy.parts.dayHeadToday : "")}</p>
                  {rows(d.todos)}
                </div>
              ),
            )
          : data.days.map((d) => (d.todos.length === 0 ? <p key={d.date} className={primitives.text}>{copy.parts.noTodos}</p> : <div key={d.date}>{rows(d.todos)}</div>))}
        <Outside outside={data.outside ?? []} highlight={highlight} />
        {buttons.length > 0 && <Buttons items={buttons} isDisabled={() => false} onPress={(item) => open(item, ctx)} />}
      </div>
    </Part>
  );
}

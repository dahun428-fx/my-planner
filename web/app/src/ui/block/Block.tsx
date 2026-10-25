import { Fragment, useState } from "react";
import { Part } from "../components/Part";
import { UnknownPart } from "../components/UnknownPart";
import styles from "../chat/cards.module.css";
import type { BlockElement, ButtonItem } from "../primitives/types";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { checkBlock } from "./checkBlock";
import { renderElement } from "./renderElement";

export type BlockProps = { title: string; children: BlockElement[] };

/**
 * ui_block (SP6 7): up to twelve parts stacked 12px apart in the usual card frame. checkBlock runs
 * here, not in UiPart, so it stays out of the first screen's bundle (gap 13): a card that fails
 * it is an UnknownPart with its title, never drawn in part.
 */
export function Block({ props, data, ctx }: PartProps<BlockProps>) {
  const act = usePartAction();
  const [completed, setCompleted] = useState<ReadonlySet<number>>(new Set());
  if (!checkBlock(props)) return <UnknownPart props={props} />;

  const complete = async (id: number): Promise<boolean> => {
    if (ctx.readOnly || ctx.restored) return false;
    const out = await act("complete_task", { id });
    if (out?.kind !== "applied") return false;
    setCompleted((s) => new Set(s).add(id));
    ctx.onAfterAction();
    return true;
  };
  const press = async (item: ButtonItem): Promise<boolean> => {
    const d = item.do;
    if (d.kind === "open") {
      ctx.onOpen?.(d.screen);
      return true;
    }
    if (ctx.readOnly || ctx.restored) return false;
    if (d.kind === "send") {
      if (!ctx.onChoose) return false;
      ctx.onChoose(item.label);
      return true;
    }
    return complete(d.task_id);
  };

  return (
    <Part title={props.title} readOnly={ctx.readOnly} restored={ctx.restored}>
      <div className={styles.block}>
        {props.children.map((el, i) => (
          <Fragment key={i}>{renderElement(el, { todos: data?.todos, today: data?.today, ctx, first: i === 0, completed, complete, press })}</Fragment>
        ))}
      </div>
    </Part>
  );
}

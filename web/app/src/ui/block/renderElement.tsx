import { Fragment, type ReactNode } from "react";
import { Bullets } from "../primitives/Bullets";
import { Buttons } from "../primitives/Buttons";
import { Divider } from "../primitives/Divider";
import { Group } from "../primitives/Group";
import { Heading } from "../primitives/Heading";
import { MiniText } from "../primitives/MiniText";
import { Progress } from "../primitives/Progress";
import { Stat } from "../primitives/Stat";
import { Tags } from "../primitives/Tags";
import { TodoRows } from "../primitives/TodoRows";
import type { BlockElement, ButtonItem } from "../primitives/types";
import type { PartContext, PartTodo } from "../types";

export type BlockEnv = {
  todos: PartTodo[] | undefined;
  today: string | undefined;
  ctx: PartContext;
  /** The first element of its list (a heading there has no top margin). */
  first: boolean;
  /** The ids completed from this card since it was drawn. */
  completed: ReadonlySet<number>;
  complete(id: number): Promise<boolean>;
  press(item: ButtonItem): Promise<boolean>;
};

/**
 * SP6 7 / 6.5: which buttons a block shows. `open` needs a screen to open (`ctx.onOpen`); a
 * restored card has no `complete` or `send` (its question is over), only `open`.
 */
function shownButtons(items: ButtonItem[], ctx: PartContext): ButtonItem[] {
  return items.filter((b) => (b.do.kind === "open" ? ctx.onOpen !== undefined : ctx.restored !== true));
}

/** A button that writes is off read-only, `send` without a chat, `complete` unless its row is open in `data.todos` (8장). */
function buttonOff(item: ButtonItem, env: BlockEnv): boolean {
  const d = item.do;
  if (d.kind === "open") return false;
  if (env.ctx.readOnly) return true;
  if (d.kind === "send") return !env.ctx.onChoose;
  const row = env.todos?.find((t) => t.id === d.task_id);
  return row?.status !== "open" || env.completed.has(d.task_id);
}

/** One part of a ui_block (5.3), drawn from props and the rows the BE attached. */
export function renderElement(el: BlockElement, env: BlockEnv): ReactNode {
  switch (el.type) {
    case "heading":
      return <Heading text={el.text} first={env.first} />;
    case "text":
      return <MiniText md={el.md} />;
    case "stat":
      return <Stat label={el.label} value={el.value} delta={el.delta} />;
    case "progress":
      return <Progress label={el.label} value={el.value} max={el.max} />;
    case "todo_rows":
      return (
        <TodoRows
          ids={el.task_ids}
          todos={env.todos}
          today={env.today}
          checkable={el.checkable !== false}
          completed={env.completed}
          ctx={env.ctx}
          onComplete={(id) => void env.complete(id)}
        />
      );
    case "tags":
      return <Tags items={el.items} />;
    case "bullets":
      return <Bullets items={el.items} />;
    case "divider":
      return <Divider />;
    case "group":
      return (
        <Group layout={el.layout}>
          {el.children.map((c, i) => (
            <Fragment key={i}>{renderElement(c, { ...env, first: i === 0 })}</Fragment>
          ))}
        </Group>
      );
    case "buttons": {
      const items = shownButtons(el.items, env.ctx);
      if (items.length === 0) return null;
      return <Buttons items={items} isDisabled={(item) => buttonOff(item, env)} onPress={env.press} />;
    }
  }
}


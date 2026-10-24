import { Buttons } from "../primitives/Buttons";
import type { ButtonItem } from "../primitives/types";
import primitives from "../primitives/primitives.module.css";
import type { PartProps } from "../types";
import { Part } from "./Part";
import styles from "./parts.module.css";

// ui_choice: a question and 2-4 pills (SP6 6.1: the `buttons` part, each one a `send`). The chosen
// label goes on as the next user message; after that only the chosen pill stays dark and
// everything is off (the state is the buttons' own). Where there is no chat to send it to (a card
// pinned to Today), or the card was restored after a reload (the question is over: its answer
// would land in the current conversation), the pills are off. The question has the `text` part's
// look but is not markdown: `**` shows as typed, as before (gap 12).
export function Choice({ props, ctx }: PartProps<{ question: string; options: { id: string; label: string }[] }>) {
  const send = ctx.restored ? undefined : ctx.onChoose;
  const items: ButtonItem[] = props.options.map((o) => ({ label: o.label, do: { kind: "send" } }));
  const press = (item: ButtonItem) => {
    if (!send) return false;
    send(item.label);
    return true;
  };
  return (
    <Part readOnly={ctx.readOnly}>
      <p className={primitives.text}>{props.question}</p>
      <div className={styles.choiceButtons}>
        <Buttons items={items} isDisabled={() => ctx.readOnly || !send} onPress={press} />
      </div>
    </Part>
  );
}

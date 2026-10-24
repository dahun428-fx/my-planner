import { useRef, useState } from "react";
import { useToast } from "../../components/Toast";
import { type ActionName, useAction } from "../../api/actions";
import { copy } from "../../lib/copy";
import type { PartProps } from "../types";
import { Part } from "./Part";
import styles from "./parts.module.css";

type ConfirmProps = { summary: string; confirm_token: string; action: string; args: object; };

// ui_confirm: the secretary asked before changing something. "바꾸기" sends the original action with
// the token (a new client_msg_id); "그대로 두기" declines. A 409 means the question is already over.
export function Confirm({ props, ctx }: PartProps<ConfirmProps>) {
  const { run } = useAction();
  const [gone, setGone] = useState(false);
  const [finished, setFinished] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const toast = useToast();

  const send = async (action: ActionName, args: object, token?: string) => {
    if (inFlight.current) return; // one request at a time, whichever button it came from
    inFlight.current = true;
    setBusy(true);
    try {
      const out = await run(action, args, token ? { confirmToken: token } : undefined);
      if (out?.kind === "applied") {
        setFinished(true);
        ctx.onAfterAction();
      } else if (out?.kind === "conflict") {
        setGone(true);
      } else if (out?.kind === "needs_confirm") {
        toast.show({ text: copy.actions.failed }); // asked again: the card stays so the person can try or keep
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  if (gone) {
    return (
      <Part variant="confirm">
        <p className={styles.gone}>{copy.parts.confirmGone}</p>
      </Part>
    );
  }
  const off = ctx.readOnly || finished || busy;
  return (
    <Part variant="confirm" readOnly={ctx.readOnly}>
      <p className={styles.text}>{props.summary}</p>
      <div className={styles.buttons}>
        <button type="button" className={styles.button} disabled={off} onClick={() => void send("decline_confirm", { confirm_token: props.confirm_token })}>
          {copy.todos.keep}
        </button>
        <button type="button" className={`${styles.button} ${styles.primary}`} disabled={off} onClick={() => void send(props.action as ActionName, props.args, props.confirm_token)}>
          {copy.todos.change}
        </button>
      </div>
    </Part>
  );
}

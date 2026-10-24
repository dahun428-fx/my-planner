import type { UIMessage } from "ai";
import { useRef, useState } from "react";
import { failureText, type UndoBlockReason, undoActivity } from "../api/actions";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { UiPart } from "../ui/registry";
import type { ViewPart } from "./parts";
import styles from "./ChatSheet.module.css";

type UndoState = { kind: "idle" } | { kind: "busy" } | { kind: "done" } | { kind: "blocked"; reason: UndoBlockReason };

// The grey box of a data-activity part (12장 R4b) and its undo. Before R4b there is no
// confirmation: then only the undo button shows.
function ActivityBox({ confirmation, undoId }: { confirmation: string | null; undoId: number | null }) {
  const toast = useToast();
  const [undo, setUndo] = useState<UndoState>({ kind: "idle" });
  const lock = useRef(false);

  const run = async (id: number) => {
    if (lock.current) return; // the answer to the first press has not come yet
    lock.current = true;
    setUndo({ kind: "busy" });
    try {
      const out = await undoActivity(id);
      if (out.kind === "undone") {
        toast.show({ text: out.confirmation });
        setUndo({ kind: "done" });
      } else if (out.kind === "already_undone") {
        setUndo({ kind: "done" });
      } else if (out.kind === "blocked") {
        setUndo({ kind: "blocked", reason: out.reason });
      } else {
        const k = out.result.kind;
        const known = k === "offline" || k === "unauthorized" || k === "rate_limited" || k === "safe_mode";
        toast.show({ text: known ? failureText(out.result) : copy.actions.undoFailed });
        setUndo({ kind: "idle" });
      }
    } finally {
      lock.current = false;
    }
  };

  let trailing: React.ReactNode = null;
  if (undo.kind === "done") trailing = <span className={styles.note}>{copy.chat.undone}</span>;
  else if (undo.kind === "blocked") trailing = <span className={styles.note}>{copy.activity.undoBlocked[undo.reason]}</span>;
  else if (undoId !== null) {
    trailing = (
      <button type="button" className={styles.undo} disabled={undo.kind === "busy"} onClick={() => void run(undoId)}>
        {copy.chat.undo}
      </button>
    );
  }
  if (confirmation === null && trailing === null) return null;
  return (
    <div className={confirmation !== null ? styles.activity : styles.activityBare} data-activity="">
      {confirmation !== null && <span className={styles.activityText}>{confirmation}</span>}
      {trailing}
    </div>
  );
}

const userText = (m: UIMessage) =>
  m.parts
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("");

// Spec 5.5.2: my text on the right in a dark bubble, the secretary's as plain body text, parts in place.
export function MessageView({
  message,
  parts,
  readOnly = false,
  onChoose,
}: {
  message: UIMessage;
  parts: ViewPart[];
  readOnly?: boolean;
  onChoose?(label: string): void;
}) {
  if (message.role === "user") {
    return (
      <div className={styles.mine} data-message={message.id}>
        <p className={styles.bubble}>{userText(message)}</p>
      </div>
    );
  }
  return (
    <div className={styles.theirs} data-message={message.id}>
      {parts.map((p, i) => {
        if (p.kind === "text") {
          return (
            <p key={i} className={styles.text}>
              {p.text}
            </p>
          );
        }
        if (p.kind === "ui") {
          return (
            <div key={p.toolCallId} className={styles.part}>
              <UiPart name={p.name} props={p.props} data={p.data} ctx={{ where: "chat", readOnly, restored: p.restored, onAfterAction: () => {}, onChoose }} />
            </div>
          );
        }
        return <ActivityBox key={i} confirmation={p.confirmation} undoId={p.undoIds[0] ?? null} />;
      })}
    </div>
  );
}

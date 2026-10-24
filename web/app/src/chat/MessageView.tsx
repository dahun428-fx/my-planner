import { registerChatParts } from "../ui/chat/registerChatParts";
import type { UIMessage } from "ai";
import { useState } from "react";
import { type UndoBlockReason, useUndo } from "../api/actions";
import { Markdown } from "../components/Markdown";
import { copy } from "../lib/copy";
import type { OpenScreen } from "../ui/primitives/types";
import { useCatalog } from "../ui/CatalogProvider";
import { registryNames, UiPart } from "../ui/registry";
import { hideCoveredActivity } from "./hideCoveredActivity";
import type { ViewPart } from "./parts";
import styles from "./ChatSheet.module.css";

// SP6 11.2: the chat cards join the registry with the chat sheet's bundle, before anything draws.
registerChatParts();

type UndoState = { kind: "idle" } | { kind: "done" } | { kind: "blocked"; reason: UndoBlockReason };

// The grey box of a data-activity part (12장 R4b) and its undo. Before R4b there is no
// confirmation: then only the undo button shows. Read-only (offline, an answer coming) turns the
// undo off like every other write.
function ActivityBox({ confirmation, undoId, readOnly }: { confirmation: string | null; undoId: number | null; readOnly: boolean }) {
  const { undo: send, busy } = useUndo();
  const [undo, setUndo] = useState<UndoState>({ kind: "idle" });

  const run = async (id: number) => {
    if (readOnly) return;
    const out = await send(id);
    if (out?.kind === "undone" || out?.kind === "already_undone") setUndo({ kind: "done" });
    else if (out?.kind === "blocked") setUndo({ kind: "blocked", reason: out.reason });
  };

  let trailing: React.ReactNode = null;
  if (undo.kind === "done") trailing = <span className={styles.note}>{copy.chat.undone}</span>;
  else if (undo.kind === "blocked") trailing = <span className={styles.note}>{copy.activity.undoBlocked[undo.reason]}</span>;
  else if (undoId !== null) {
    trailing = (
      <button type="button" className={styles.undo} disabled={readOnly || busy.has(undoId)} onClick={() => void run(undoId)}>
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

// Spec 5.5.2: my text on the right in a dark bubble (plain, as typed), the secretary's as body text
// in Markdown, parts in place.
export function MessageView({
  message,
  parts,
  readOnly = false,
  onChoose,
  onOpen,
}: {
  message: UIMessage;
  parts: ViewPart[];
  readOnly?: boolean;
  onChoose?(label: string): void;
  /** SP6 8: an `open` button on a part (the sheet moves there and closes). */
  onOpen?(screen: OpenScreen): void;
}) {
  const { check, settled } = useCatalog();
  if (message.role === "user") {
    return (
      <div className={styles.mine} data-message={message.id}>
        <p className={styles.bubble}>{userText(message)}</p>
      </div>
    );
  }
  // 11.4: a box that ui_result already shows is left out, but never in a restored message.
  // A ui_result hides the box only when it really draws (UiPart's own test: known name, props the catalog takes).
  const restored = parts.some((p) => p.kind === "ui" && p.restored === true);
  const shown = restored ? parts : hideCoveredActivity(parts, (p) => settled && registryNames().includes(p.name) && check(p.name, p.props));
  return (
    <div className={styles.theirs} data-message={message.id}>
      {shown.map((p, i) => {
        if (p.kind === "text") {
          return <Markdown key={i} text={p.text} className={styles.text} />;
        }
        if (p.kind === "ui") {
          return (
            <div key={p.toolCallId} className={styles.part}>
              <UiPart name={p.name} props={p.props} data={p.data} ctx={{ where: "chat", readOnly, restored: p.restored, onAfterAction: () => {}, onChoose, onOpen }} />
            </div>
          );
        }
        return <ActivityBox key={i} confirmation={p.confirmation} undoId={p.undoIds[0] ?? null} readOnly={readOnly} />;
      })}
    </div>
  );
}

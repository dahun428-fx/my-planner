import { registerChatParts } from "../ui/chat/registerChatParts";
import type { UIMessage } from "ai";
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

// SP9 9.6: a data-activity part (12장 R4b) is one line, "✓ …" in the secondary text colour, with
// no button (a confirmation that does not already start with a mark ✓ → ✗ ↩, e.g. "컨디션 7 기록했어요.", gets one): the undo is the toast's for 6 s, then the activity screen's. Before R4b no
// confirmation comes, only undo ids: then a fixed line says something changed. Nothing came at all
// (no confirmation, nothing to undo): no line.
export function ActivityLine({ confirmation, undoable = false }: { confirmation: string | null; undoable?: boolean }) {
  if (confirmation === null && !undoable) return null;
  return (
    <p className={styles.activity} data-activity="">
      {confirmation === null ? copy.chat.changed : /^[✓→✗↩]/.test(confirmation) ? confirmation : `✓ ${confirmation}`}
    </p>
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
  // 11.4 (SP9 9.6): a line that ui_result already shows is left out, but never in a restored message.
  // A ui_result hides the line only when it really draws (UiPart's own test: known name, props the catalog takes).
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
        return <ActivityLine key={i} confirmation={p.confirmation} undoable={p.undoIds.length > 0} />;
      })}
    </div>
  );
}

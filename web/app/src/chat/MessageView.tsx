import { registerChatParts } from "../ui/chat/registerChatParts";
import type { UIMessage } from "ai";
import { Markdown } from "../components/Markdown";
import { PhotoImage } from "../components/PhotoImage";
import { copy } from "../lib/copy";
import type { OpenScreen } from "../ui/primitives/types";
import type { PartContext } from "../ui/types";
import { useCatalog } from "../ui/CatalogProvider";
import { registryNames, UiPart } from "../ui/registry";
import { hideCoveredActivity } from "./hideCoveredActivity";
import type { ViewPart } from "./parts";
import { CopyHold } from "./CopyHold";
import { ExpertNotes } from "./ExpertNotes";
import { isWriteKey } from "./quickChips";
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

/** SP10 5.5: the photos of my message (its data-photo parts: those sent, or the history's `photos`), in order. */
export function messagePhotoIds(m: UIMessage): number[] {
  const ids: number[] = [];
  for (const p of m.parts) {
    if (p.type !== "data-photo") continue;
    const id = (p as { data?: { photo_id?: unknown } }).data?.photo_id;
    if (typeof id === "number" && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

// SP9c 3: a line written from an add chip on this device has a small grey label above the bubble.
function chipLabel(m: UIMessage): string | null {
  const chip = (m.metadata as { chip?: unknown } | undefined)?.chip;
  return typeof chip === "string" && isWriteKey(chip) ? copy.chat.chipLabel[chip] : null;
}

// Spec 5.5.2: my text on the right in a dark bubble (plain, as typed), the secretary's as body text
// in Markdown, parts in place.
export function MessageView({
  message,
  parts,
  readOnly = false,
  onChoose,
  onOpen,
  onOpenPath,
  onOpenPhoto,
  speakerName,
  switchAgent,
}: {
  message: UIMessage;
  parts: ViewPart[];
  readOnly?: boolean;
  onChoose?(label: string): void;
  /** SP6 8: an `open` button on a part (the sheet moves there and closes). */
  onOpen?(screen: OpenScreen): void;
  /** SP9 9.8: a `ui_events` row opens the schedule tab on its day (the sheet moves there and closes). */
  onOpenPath?(path: string): void;
  /** SP10 7.5: a photo of my bubble pressed: shown big, with the others of the message. */
  onOpenPhoto?(ids: number[], index: number): void;
  /** SP12 11.1: the head line over the partner's answer ("운동메이트"). The secretary has none. */
  speakerName?: string;
  /** SP15 10장: the chat sheet's partner switch (ui_full_diagnosis_chip). Left out off the sheet. */
  switchAgent?: PartContext["switchAgent"];
}) {
  const { check, settled } = useCatalog();
  if (message.role === "user") {
    const label = chipLabel(message);
    const text = userText(message);
    const photos = messagePhotoIds(message);
    return (
      <CopyHold side="mine" className={styles.mine} data-message={message.id}>
        {label && <p className={styles.chipLabel}>{label}</p>}
        {photos.length > 0 && (
          // SP10 7.5: small photos above the text, a grid of at most 4.
          <ul className={styles.photoGrid} aria-label={copy.photos.strip} data-count={Math.min(photos.length, 4)}>
            {photos.map((id, i) => (
              <li key={id} className={styles.photoCell}>
                <button type="button" className={styles.photoButton} aria-label={copy.photos.photo(i + 1, photos.length)} onClick={() => onOpenPhoto?.(photos, i)}>
                  <PhotoImage id={id} size="thumb" className={styles.photoThumb} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {(text !== "" || photos.length === 0) && (
          <p className={styles.bubble} data-copy="">
            {text}
          </p>
        )}
      </CopyHold>
    );
  }
  // 11.4 (SP9 9.6): a line that ui_result already shows is left out, but never in a restored message.
  // A ui_result hides the line only when it really draws (UiPart's own test: known name, props the catalog takes).
  const restored = parts.some((p) => p.kind === "ui" && p.restored === true);
  const drawn = restored ? parts : hideCoveredActivity(parts, (p) => settled && registryNames().includes(p.name) && check(p.name, p.props));
  // SP15: the expert notes are one folded line under the whole answer, wherever their part came.
  const notes = drawn.flatMap((p) => (p.kind === "notes" ? p.notes : []));
  const shown = drawn.filter((p) => p.kind !== "notes");
  return (
    <CopyHold side="theirs" className={styles.theirs} data-message={message.id}>
      {speakerName && <p className={styles.speaker}>{speakerName}</p>}
      {shown.map((p, i) => {
        if (p.kind === "text") {
          return (
            <div key={i} data-copy="">
              <Markdown text={p.text} className={styles.text} />
            </div>
          );
        }
        if (p.kind === "ui") {
          return (
            <div key={p.toolCallId} className={styles.part}>
              <UiPart name={p.name} props={p.props} data={p.data} ctx={{ where: "chat", readOnly, restored: p.restored, onAfterAction: () => {}, onChoose, onOpen, onOpenPath, switchAgent }} />
            </div>
          );
        }
        if (p.kind === "activity") return <ActivityLine key={i} confirmation={p.confirmation} undoable={p.undoIds.length > 0} />;
        return null;
      })}
      <ExpertNotes notes={notes} />
    </CopyHold>
  );
}

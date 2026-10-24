import type { ReactNode } from "react";
import type { AppCard } from "../api/types.gen";
import { SwipeRow } from "../components/SwipeRow";
import { copy } from "../lib/copy";
import styles from "./Today.module.css";

// A card the secretary pinned to Today (spec 5.5.1 block 7): the part, a blue mark at the head,
// and "내리기" · "위로" · "아래로" on a long press (or the "…" button, or a swipe).
export function PinnedCard({
  card,
  readOnly,
  canMoveUp,
  canMoveDown,
  onUnpin,
  onMove,
  children,
}: {
  card: AppCard;
  readOnly: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onUnpin(): void;
  onMove(by: -1 | 1): void;
  children: ReactNode;
}) {
  const title = typeof card.props.title === "string" && card.props.title !== "" ? card.props.title : copy.today.pinnedFallbackTitle;
  const actions = [
    { label: copy.today.unpin, tone: "neutral" as const, onPress: onUnpin },
    ...(canMoveUp ? [{ label: copy.today.moveUp, tone: "neutral" as const, onPress: () => onMove(-1) }] : []),
    ...(canMoveDown ? [{ label: copy.today.moveDown, tone: "neutral" as const, onPress: () => onMove(1) }] : []),
  ];
  return (
    <section className={styles.pinned}>
      <p className={styles.pinnedMark}>{copy.today.pinnedBySecretary}</p>
      <div className={styles.pinnedBody}>
        <SwipeRow actions={actions} disabled={readOnly} menuTitle={copy.today.pinnedMenu} moreLabel={copy.today.pinnedMore(title)}>
          {children}
        </SwipeRow>
      </div>
    </section>
  );
}

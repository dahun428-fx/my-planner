import { copy } from "../../lib/copy";
import type { Delta } from "./types";
import styles from "./primitives.module.css";

const ARROW = { up: "↑", down: "↓", same: "→" } as const;

function trendAria(d: Delta): string {
  return d.trend === "same" ? copy.parts.trendAria.same : copy.parts.trendAria[d.trend](d.text);
}

/** `stat` (5.3.3): a name, a value as written (the app does no arithmetic) and an optional change, always --text-2. */
export function Stat({ label, value, delta }: { label: string; value: string; delta?: Delta | null }) {
  const name = delta ? `${label} ${value}, ${trendAria(delta)}` : `${label} ${value}`;
  return (
    <div role="group" aria-label={name} className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>{value}</span>
      {delta && <span className={styles.delta}>{`${ARROW[delta.trend]} ${delta.text}`}</span>}
    </div>
  );
}

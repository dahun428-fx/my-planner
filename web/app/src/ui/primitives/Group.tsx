import type { ReactNode } from "react";
import styles from "./primitives.module.css";

/** `group` (5.3.10): `row` is equal columns (one per line under 340px), `stack` an inner bundle. */
export function Group({ layout, children }: { layout: "row" | "stack"; children: ReactNode[] }) {
  return <div className={layout === "row" ? styles.row : styles.stack}>{children}</div>;
}

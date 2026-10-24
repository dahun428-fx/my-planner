import styles from "./primitives.module.css";

/** `bullets` (5.3.7): a dotted list. No markdown. */
export function Bullets({ items }: { items: string[] }) {
  return (
    <ul className={styles.bullets}>
      {items.map((t, i) => (
        <li key={i}>{t}</li>
      ))}
    </ul>
  );
}

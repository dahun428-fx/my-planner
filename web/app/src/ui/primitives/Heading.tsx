import styles from "./primitives.module.css";

/** `heading` (5.3.1): one level under the card title (<h3>). `first` drops the top margin. */
export function Heading({ text, first = false }: { text: string; first?: boolean }) {
  return <h4 className={`${styles.heading} ${first ? styles.first : ""}`}>{text}</h4>;
}

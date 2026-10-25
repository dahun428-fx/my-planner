import { Fragment } from "react";
import { parseMiniMd } from "./parseMiniMd";
import styles from "./primitives.module.css";

/** `text` (5.3.2): `**strong**` and line breaks only, all as React text nodes. */
export function MiniText({ md }: { md: string }) {
  return (
    <p className={styles.text}>
      {parseMiniMd(md).map((line, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          {line.map((seg, j) => (seg.strong ? <strong key={j}>{seg.text}</strong> : <Fragment key={j}>{seg.text}</Fragment>))}
        </Fragment>
      ))}
    </p>
  );
}

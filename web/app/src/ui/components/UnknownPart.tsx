import { copy } from "../../lib/copy";
import styles from "./parts.module.css";

// A part this app cannot draw (not in the registry, or props the catalog schema refuses):
// a grey box with the part's own title / question / summary if it has one.
export function UnknownPart({ props }: { props: unknown }) {
  const bag = (props && typeof props === "object" ? props : {}) as Record<string, unknown>;
  const text = (["title", "question", "summary"] as const).map((k) => bag[k]).find((v): v is string => typeof v === "string" && v !== "");
  return (
    <section className={styles.unknown}>
      <p className={styles.gone}>{copy.parts.unknown}</p>
      {text && <p className={styles.unknownText}>{text}</p>}
    </section>
  );
}

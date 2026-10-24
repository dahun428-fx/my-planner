import { useState } from "react";
import type { PartProps } from "../types";
import { Part } from "./Part";
import styles from "./parts.module.css";

// ui_choice: a question and 2-4 pills. The chosen label goes on as the next user message; after
// that only the chosen pill stays dark and everything is off (the state is this part's own).
export function Choice({ props, ctx }: PartProps<{ question: string; options: { id: string; label: string }[] }>) {
  const [chosen, setChosen] = useState<string | null>(null);
  const pick = (id: string, label: string) => {
    if (chosen !== null) return;
    setChosen(id);
    ctx.onChoose?.(label);
  };
  return (
    <Part readOnly={ctx.readOnly}>
      <p className={styles.text}>{props.question}</p>
      <div className={styles.pills}>
        {props.options.map((o) => (
          <button
            key={o.id}
            type="button"
            className={styles.pill}
            aria-pressed={chosen === o.id}
            disabled={ctx.readOnly || chosen !== null}
            onClick={() => pick(o.id, o.label)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </Part>
  );
}

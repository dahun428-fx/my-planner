import { useState } from "react";
import { copy } from "../../lib/copy";
import { Segmented } from "../../components/Segmented";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { Part } from "./Part";
import styles from "./parts.module.css";

type Area = keyof typeof copy.areas;
const AREAS = Object.keys(copy.areas) as Area[];
const SCORES = Array.from({ length: 10 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }));

// ui_area_scores: six areas, 1-10 each (last score in grey). "저장" sends only the areas that were chosen.
export function AreaScores({ props, ctx }: PartProps<{ period: string; previous: Partial<Record<Area, number>> }>) {
  const act = usePartAction();
  const [scores, setScores] = useState<Partial<Record<Area, number>>>({});
  const [finished, setFinished] = useState(false);
  const chosen = AREAS.filter((a) => scores[a] !== undefined);
  const off = ctx.readOnly || finished;

  const save = async () => {
    const body: Partial<Record<Area, number>> = {};
    for (const a of chosen) body[a] = scores[a];
    const out = await act("record_area_scores", { period: props.period, scores: body });
    if (out?.kind === "applied") {
      setFinished(true);
      ctx.onAfterAction();
    }
  };

  return (
    <Part readOnly={ctx.readOnly}>
      {AREAS.map((a) => {
        const prev = props.previous?.[a];
        return (
          <div key={a} className={styles.areaRow}>
            <div className={styles.areaHead}>
              <span>{copy.areas[a]}</span>
              {prev !== undefined && <span className={styles.previous}>{copy.parts.previous(prev)}</span>}
            </div>
            <Segmented
              ariaLabel={copy.parts.areaLabel(copy.areas[a])}
              disabled={off}
              options={SCORES}
              value={scores[a] === undefined ? "" : String(scores[a])}
              onChange={(v) => !off && setScores((s) => ({ ...s, [a]: Number(v) }))}
            />
          </div>
        );
      })}
      <div className={styles.buttons}>
        <button type="button" className={`${styles.button} ${styles.primary}`} disabled={off || chosen.length === 0} onClick={() => void save()}>
          {copy.parts.save}
        </button>
      </div>
    </Part>
  );
}

import { useEffect, useState } from "react";
import { getPanelBudget } from "../../api/panel";
import { Pictogram } from "../../components/pictograms.gen";
import { useConnection } from "../../lib/ConnectionProvider";
import { copyPanel } from "../../lib/copyPanel";
import type { PartProps } from "../types";
import styles from "./PanelSuggestion.module.css";

export type FullDiagnosisChipProps = { period: string };

// ui_full_diagnosis_chip (SP15 10장, D3): after a quarterly review the secretary offers the full
// diagnosis. A press turns the chat sheet to the life manager and sends its "전체 진단" chip
// (ctx.switchAgent, which only ChatSheet gives); nothing runs by itself. Text only where there is no
// sheet to turn (the check-in screen), on a BE without the life manager, and on a restored card.
// Already done today (GET /panel/budget `full_diagnosis_ok` false): "오늘은 이미 했어요", off.
export function FullDiagnosisChip({ ctx }: PartProps<FullDiagnosisChipProps>) {
  const { state } = useConnection();
  const hasManager =
    state?.kind === "online" &&
    (state.health.features?.includes("manager") ?? false);
  const live = !!ctx.switchAgent && hasManager && ctx.restored !== true;
  const [fullOk, setFullOk] = useState<boolean | null>(null);
  const [pressed, setPressed] = useState(false);

  useEffect(() => {
    if (!live) return;
    let on = true;
    void getPanelBudget().then((r) => {
      if (on && r.kind === "ok") setFullOk(r.data.full_diagnosis_ok);
    });
    return () => {
      on = false;
    };
  }, [live]);

  if (!live) return <p className={styles.ask}>{copyPanel.chips.fullAsk}</p>;
  const done = fullOk === false;
  const press = () => {
    if (pressed || done || ctx.readOnly) return;
    if (ctx.switchAgent?.("manager", "manager_full")) setPressed(true);
  };
  return (
    <button
      type="button"
      className={`${styles.ask} pressable`}
      disabled={done || pressed || ctx.readOnly}
      onClick={press}
    >
      <Pictogram name="compass" size={20} />
      {done ? copyPanel.chips.fullDone : copyPanel.chips.fullAsk}
    </button>
  );
}

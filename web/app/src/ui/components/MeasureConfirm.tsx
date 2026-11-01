import { useRef, useState } from "react";
import { copy } from "../../lib/copy";
import { standingCopy as S } from "../../lib/copyStanding";
import type { PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { Part } from "./Part";
import styles from "./parts.module.css";

export type MeasureRow = { metric: string; label: string; value: number | string; unit: string | null; measured_on: string };
export type MeasureConfirmProps = { rows: MeasureRow[]; source_kind: "photo" | "pdf" | "manual"; source_ref: string | null };

type Draft = { key: number; metric: string; label: string; unit: string | null; num: boolean; value: string; measured_on: string };

const DATE = /^\d{4}-\d{2}-\d{2}$/;
/** A choice metric draws a picker; `cert` is free text (toeic:<n>, other:<x>), spec 6.2. */
const choices = (metric: string): Record<string, string> | null => (metric === "cert" ? null : (S.values[metric] ?? null));
const isKrw = (metric: string) => metric.endsWith("_krw");

const toDraft = (r: MeasureRow, key: number): Draft => ({
  key,
  metric: r.metric,
  label: r.label,
  unit: r.unit,
  num: typeof r.value === "number",
  value: String(r.value),
  measured_on: r.measured_on,
});
const numberOf = (d: Draft) => (d.value.trim() === "" ? Number.NaN : Number(d.value));
const valid = (d: Draft) => DATE.test(d.measured_on) && (d.num ? Number.isFinite(numberOf(d)) : d.value.trim() !== "");

// ui_measure_confirm (SP13 6.5): the rows a photo, a PDF or a sentence gave. Each value can be fixed
// and each row left out; "저장" sends what is left as save_measures. Once saved, the card shows the
// confirmation and is read-only, as ui_confirm is once done. A card restored after a reload (4.6) shows
// its rows only, without "빼기" or "저장": they may have been saved since.
export function MeasureConfirm({ props, ctx }: PartProps<MeasureConfirmProps>) {
  const act = usePartAction();
  const [rows, setRows] = useState<Draft[]>(() => props.rows.map(toDraft));
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // one save at a time, even before `busy` has re-rendered the button
  const [done, setDone] = useState<string | null>(null);
  const restored = ctx.restored === true;
  const off = ctx.readOnly || restored || busy || done !== null;
  const face = props.rows.some((r) => r.metric === "face_rating");

  const patch = (key: number, p: Partial<Draft>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...p } : r)));
  const drop = (key: number) => setRows((rs) => rs.filter((r) => r.key !== key));

  const save = async () => {
    if (off || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      const out = await act("save_measures", {
        rows: rows.map((r) => ({ metric: r.metric, value: r.num ? numberOf(r) : r.value.trim(), measured_on: r.measured_on })),
        source_kind: props.source_kind,
        source_ref: props.source_ref,
      });
      if (out?.kind === "applied") {
        setDone(out.confirmation);
        ctx.onAfterAction();
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <Part title={S.card.title} variant="confirm" readOnly={ctx.readOnly} restored={ctx.restored}>
      <ul className={styles.rows}>
        {rows.map((r) => {
          const pick = r.num ? null : choices(r.metric);
          const n = numberOf(r);
          return (
            <li key={r.key} className={styles.measureRow}>
              <div className={styles.measureHead}>
                <span>{r.label}</span>
                {!restored && (
                  <button type="button" className={styles.more} disabled={off} aria-label={S.card.dropLabel(r.label)} onClick={() => drop(r.key)}>
                    {S.card.drop}
                  </button>
                )}
              </div>
              <div className={styles.measureFields}>
                {pick ? (
                  <select className={styles.field} aria-label={S.card.value(r.label)} disabled={off} value={r.value} onChange={(e) => patch(r.key, { value: e.target.value })}>
                    {!(r.value in pick) && <option value={r.value}>{r.value}</option>}
                    {Object.entries(pick).map(([v, label]) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={styles.field}
                    type={r.num ? "number" : "text"}
                    inputMode={r.num ? "decimal" : undefined}
                    step={r.num ? "any" : undefined}
                    aria-label={S.card.value(r.label)}
                    disabled={off}
                    value={r.value}
                    onChange={(e) => patch(r.key, { value: e.target.value })}
                  />
                )}
                {r.unit && <span className={styles.unit}>{r.unit}</span>}
                <input
                  className={`${styles.field} ${styles.dateField}`}
                  type="date"
                  aria-label={S.card.date(r.label)}
                  disabled={off}
                  value={r.measured_on}
                  onChange={(e) => patch(r.key, { measured_on: e.target.value })}
                />
              </div>
              {r.num && isKrw(r.metric) && Number.isFinite(n) && <p className={styles.hint}>{S.krw(n)}</p>}
            </li>
          );
        })}
      </ul>
      {done !== null && <p className={styles.text}>{done}</p>}
      {!restored && (
        <div className={styles.buttons}>
          <button type="button" className={`${styles.button} ${styles.primary}`} disabled={off || rows.length === 0 || !rows.every(valid)} onClick={() => void save()}>
            {copy.parts.save}
          </button>
        </div>
      )}
      {face && <p className={styles.reason}>{S.card.faceNote}</p>}
    </Part>
  );
}

import { useCallback, useEffect, useId, useState } from "react";
import { useAction } from "../api/actions";
import type { ApiResult } from "../api/client";
import { getOwnerStatements } from "../api/panel";
import type { OwnerStatementOut, OwnerStatements as OwnerStatementsData } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { copyPanel } from "../lib/copyPanel";
import { formatKst } from "../lib/time";
import styles from "./OwnerStatements.module.css";

const T = copyPanel.statements;

// "2026-10-30T03:00:00Z" -> "10/30" (the day in Seoul).
const monthDay = (iso: string) => {
  const [, m, d] = formatKst(iso, "date").split("-");
  return `${Number(m)}/${Number(d)}`;
};

const metaOf = (s: OwnerStatementOut) => [T.kinds[s.kind], s.area ? copy.areas[s.area] : null, monthDay(s.created_at)].filter(Boolean).join(" · ");

function Line({ s, busy, onRetire }: { s: OwnerStatementOut; busy: boolean; onRetire(): void }) {
  const textId = useId();
  return (
    <li className={styles.line} data-kind={s.kind}>
      <span className={styles.body}>
        <span id={textId} className={styles.text}>
          {s.text}
        </span>
        <span className={`${styles.meta} tnum`}>{metaOf(s)}</span>
      </span>
      <button type="button" className={styles.retire} aria-describedby={textId} disabled={busy} onClick={onRetire}>
        {T.retire}
      </button>
    </li>
  );
}

// SP15 5.4: what I said that the panel may lean on (GET /owner-statements), each with "지우기"
// (retire_statement, with the undo toast). The more screen opens it in place under "내가 한 말"; it is
// its own chunk there, so its stylesheet comes with that chunk (a <link>, CSP), not with _app.
export function OwnerStatements() {
  const toast = useToast();
  const { run, isPending } = useAction();
  const [result, setResult] = useState<ApiResult<OwnerStatementsData> | null>(null);
  const read = useCallback(() => {
    void getOwnerStatements().then(setResult);
  }, []);
  useEffect(read, [read]);
  useEffect(() => toast.onUndone(read), [toast, read]);

  const retire = async (s: OwnerStatementOut) => {
    const out = await run("retire_statement", { id: s.id });
    if (out?.kind !== "applied") return;
    // The line goes at once; the read after it is the BE's word.
    setResult((r) => (r?.kind === "ok" ? { ...r, data: { items: r.data.items.filter((x) => x.id !== s.id) } } : r));
    read();
  };

  if (result === null) return <Skeleton size="row" />;
  if (result.kind !== "ok") {
    return (
      <BlockError
        code={result.kind === "error" ? result.code : result.kind}
        onRetry={() => {
          setResult(null);
          read();
        }}
      />
    );
  }
  if (result.data.items.length === 0) return <p className={styles.empty}>{T.empty}</p>;
  return (
    <ul className={styles.list}>
      {result.data.items.map((s) => (
        <Line key={s.id} s={s} busy={isPending("retire_statement", { id: s.id })} onRetire={() => void retire(s)} />
      ))}
    </ul>
  );
}

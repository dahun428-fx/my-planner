import { useState } from "react";
import type { Health } from "../api/types.gen";
import type { ApiResult } from "../lib/api";
import { useConnection } from "../lib/ConnectionProvider";
import type { LastHealthOk } from "../lib/connection";
import { BAND_TEXT } from "../lib/labels";
import { formatKst } from "../lib/time";

export type BandState = "on" | "off" | "checking" | "none";

export function bandOf(health: ApiResult<Health> | null, hasConn: boolean): BandState {
  if (!hasConn) return "none";
  if (health === null) return "checking";
  return health.kind === "offline" ? "off" : "on"; // any HTTP answer means the BE is up
}

export function bandText(health: ApiResult<Health> | null, hasConn: boolean, lastOk: LastHealthOk | null): string {
  switch (bandOf(health, hasConn)) {
    case "none":
      return "BE 연결 전";
    case "checking":
      return BAND_TEXT.checking;
    case "off":
      return BAND_TEXT.off(lastOk ? formatKst(lastOk.at, "M/D HH:mm") : null);
    case "on":
      return health?.kind === "ok" ? BAND_TEXT.on(formatKst(health.data.now, "HH:mm:ss")) : BAND_TEXT.onNoTime;
  }
}

/** Top of every screen (spec 13.1, 13.2): BE on with its answer time, or off with this browser's last answer. */
export function ConnectionBand() {
  const { ready, conn, health, lastOk, check } = useConnection();
  const [busy, setBusy] = useState(false);
  if (!ready) return <div className="band" data-state="checking" aria-hidden="true" />;
  const state = bandOf(health, conn !== null);
  const onCheck = async () => {
    setBusy(true);
    try {
      await check();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="band" data-state={state} role="status" aria-live="polite">
      <span className="band-text">
        <span className="dot" data-tone={state === "on" ? "positive" : "neutral"} aria-hidden="true" />
        {bandText(health, conn !== null, lastOk)}
      </span>
      {conn && (
        <button type="button" className="text-button" onClick={onCheck} disabled={busy}>
          {busy ? BAND_TEXT.checking : BAND_TEXT.check}
        </button>
      )}
    </div>
  );
}

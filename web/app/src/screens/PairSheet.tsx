import { useCallback, useEffect, useRef, useState } from "react";
import { createPairCode, getPairStatus } from "../api/client";
import type { PairCreated } from "../api/types.gen";
import { Qr } from "../components/Qr";
import { Segmented } from "../components/Segmented";
import { Sheet } from "../components/Sheet";
import { copy } from "../lib/copy";
import styles from "./Devices.module.css";

const POLL_MS = 2_000;

type Phase =
  | { kind: "making" }
  | { kind: "waiting"; pair: PairCreated }
  | { kind: "used"; label: string }
  | { kind: "expired" }
  | { kind: "failed"; code: string };

// "482913" -> "482 913" (spec 3.1).
const spaced = (code: string) => `${code.slice(0, 3)} ${code.slice(3)}`;

function mss(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// The optional dashboard address (spec 5.2), without a trailing slash; "" hides its row and QR switch.
function dashboardUrl(value: string | undefined = process.env.NEXT_PUBLIC_DASHBOARD_URL): string {
  return (value ?? "").trim().replace(/\/+$/, "");
}

export interface PairSheetProps {
  open: boolean;
  onClose(): void;
  /** The BE address the QR hands over (`#be=`). */
  beUrl: string;
  /** A device connected with this sheet's code: the list reads again. */
  onUsed(): void;
  pollMs?: number;
}

// Device pairing spec 5.2: a new code each time the sheet opens, its countdown, where to open it, and
// a QR of `<app>/connect/#be=…&code=…` (or the dashboard's /settings/). GET /devices/pair every 2s
// while open; closing stops asking (the code lives on at the BE until it runs out).
export function PairSheet({ open, onClose, beUrl, onUsed, pollMs = POLL_MS }: PairSheetProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "making" });
  const [now, setNow] = useState(() => Date.now());
  const [qrFor, setQrFor] = useState<"app" | "dashboard">("app");
  const onUsedRef = useRef(onUsed);
  onUsedRef.current = onUsed;
  const seq = useRef(0);
  const dashboard = dashboardUrl();

  const make = useCallback(async () => {
    const mine = ++seq.current;
    setPhase({ kind: "making" });
    const r = await createPairCode();
    if (mine !== seq.current) return; // closed, or a newer code was asked for
    setNow(Date.now());
    if (r.kind === "ok") setPhase({ kind: "waiting", pair: r.data });
    else setPhase({ kind: "failed", code: r.kind === "error" ? r.code : r.kind });
  }, []);

  useEffect(() => {
    if (!open) return;
    void make();
    return () => {
      seq.current++; // an answer still coming for this opening is dropped
      setPhase({ kind: "making" });
      setQrFor("app");
    };
  }, [open, make]);

  const waiting = phase.kind === "waiting" ? phase.pair : null;

  // The countdown, and the poll for what became of the code.
  useEffect(() => {
    if (!open || !waiting) return;
    const mine = seq.current;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    const ac = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      const r = await getPairStatus(ac.signal);
      if (ac.signal.aborted || mine !== seq.current) return;
      if (r.kind === "ok") {
        if (r.data.state === "used") {
          setPhase({ kind: "used", label: r.data.device?.label ?? "" });
          onUsedRef.current();
          return;
        }
        // `none`: the BE no longer holds it (a restart), which is the same as run out for this sheet.
        if (r.data.state === "expired" || r.data.state === "none") {
          setPhase({ kind: "expired" });
          return;
        }
      } else if (r.kind === "unauthorized" || r.kind === "rate_limited" || r.kind === "safe_mode") {
        // No more asking: each 401 counts in the BE's AuthLimiter, and these do not pass on their own.
        setPhase({ kind: "failed", code: r.kind });
        return;
      }
      timer = setTimeout(() => void poll(), pollMs);
    };
    timer = setTimeout(() => void poll(), pollMs);
    return () => {
      clearInterval(tick);
      clearTimeout(timer);
      ac.abort();
    };
  }, [open, waiting, pollMs]);

  const left = waiting ? Date.parse(waiting.expires_at) - now : 0;
  const ranOut = waiting !== null && left <= 0;
  const appUrl = typeof window === "undefined" ? "" : window.location.origin;
  const hash = (code: string) => `#be=${encodeURIComponent(beUrl)}&code=${code}`;
  const qrText = (code: string) =>
    qrFor === "dashboard" && dashboard ? `${dashboard}/settings/${hash(code)}` : `${appUrl}/connect/${hash(code)}`;

  let body;
  if (phase.kind === "used") {
    body = (
      <p className={styles.result} role="status">
        {copy.devices.used(phase.label)}
      </p>
    );
  } else if (phase.kind === "expired" || ranOut) {
    body = (
      <p className={styles.result} role="status">
        {copy.devices.expired}
        <span aria-hidden="true"> · </span>
        <button type="button" className={styles.inline} onClick={() => void make()}>
          {copy.devices.makeAgain}
        </button>
      </p>
    );
  } else if (phase.kind === "failed") {
    body = (
      <p className={styles.result} role="status">
        {copy.devices.createFailed(phase.code)}
        <span aria-hidden="true"> · </span>
        <button type="button" className={styles.inline} onClick={() => void make()}>
          {copy.errors.retry}
        </button>
      </p>
    );
  } else if (waiting) {
    body = (
      <>
        <p className={styles.code} aria-label={copy.connect.codeLabel}>
          {spaced(waiting.code)}
        </p>
        <p className={styles.remaining}>{copy.devices.remaining(mss(left))}</p>
        <dl className={styles.where}>
          <div>
            <dt>{copy.devices.appAddress}</dt>
            <dd>{appUrl.replace(/^https?:\/\//, "")}</dd>
          </div>
          {dashboard && (
            <div>
              <dt>{copy.devices.dashboardAddress}</dt>
              <dd>{dashboard.replace(/^https?:\/\//, "")}</dd>
            </div>
          )}
        </dl>
        {dashboard && (
          <div className={styles.qrSwitch}>
            <Segmented<"app" | "dashboard">
              ariaLabel={copy.devices.qrFor}
              options={[
                { value: "app", label: copy.devices.qrApp },
                { value: "dashboard", label: copy.devices.qrDashboard },
              ]}
              value={qrFor}
              onChange={setQrFor}
            />
          </div>
        )}
        <Qr text={qrText(waiting.code)} label={copy.devices.qrLabel} />
        <button type="button" className={styles.remake} onClick={() => void make()}>
          {copy.devices.remake}
        </button>
      </>
    );
  } else {
    body = <p className={styles.remaining}>{copy.connect.checking}</p>;
  }

  return (
    <Sheet open={open} onClose={onClose} title={copy.devices.sheetTitle}>
      <div className={styles.sheet}>{body}</div>
    </Sheet>
  );
}

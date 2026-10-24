import Link from "next/link";
import { useConnection } from "../lib/ConnectionProvider";
import { OFFLINE_TEXT as T, STATE_TEXT } from "../lib/labels";
import { formatKst, timeAgo } from "../lib/time";

/** The wait a screen's own poll keeps while `/health` itself still answers (spec 13.1 "새로 고침"). */
const SCREEN_INTERVAL_MS = 60_000;

/**
 * DU-02: in place of a screen while the BE does not answer. Three things to check, this browser's last good
 * answer (M/D HH:MM and how long ago), and that it keeps checking by itself. A browser with no good answer on
 * record reads as one that never connected, and is pointed at its address and token too.
 * Only the first line is a live region: the rest would be read out again at every check.
 */
export function OfflineCard({ settingsLink = true }: { settingsLink?: boolean }) {
  const { lastOk, retryMs } = useConnection();
  const seen = lastOk ? "before" : "never";
  const ago = lastOk ? timeAgo(lastOk.at) : null;
  return (
    <div className="notice offline-card" data-kind="offline" data-seen={seen}>
      <p className="offline-title" role="status">
        {T.title[seen]}
      </p>
      <p className="meta num">{lastOk ? T.lastSeen(formatKst(lastOk.at, "M/D HH:mm"), ago ?? "") : T.lastNone}</p>
      <p className="offline-lead">
        {T.lead[seen]}
      </p>
      <ol className="offline-checks" aria-label={T.checksLabel}>
        {T.checks.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
      {seen === "never" && <p>{T.neverHint}</p>}
      {seen === "never" && settingsLink && (
        <p>
          <Link href="/settings/">{STATE_TEXT.openSettings}</Link>
        </p>
      )}
      <p className="meta">{T.retry(T.every(retryMs ?? SCREEN_INTERVAL_MS))}</p>
      <p>{STATE_TEXT.offline}</p>
    </div>
  );
}

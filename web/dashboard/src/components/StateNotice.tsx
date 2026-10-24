import Link from "next/link";
import type { ApiResult } from "../lib/api";
import { STATE_TEXT } from "../lib/labels";
import { OfflineCard } from "./OfflineCard";

/** What a screen shows in place of its content when its GET did not give data (spec 13.1 table, DU-02). */
export function StateNotice({ result, settingsLink = true }: { result: ApiResult<unknown>; settingsLink?: boolean }) {
  if (result.kind === "ok") return null;
  if (result.kind === "offline") return <OfflineCard settingsLink={settingsLink} />;
  const text = result.kind === "broken" ? STATE_TEXT.broken(result.code) : STATE_TEXT[result.kind];
  return (
    <div className="notice" data-kind={result.kind} role="status">
      <p>{text}</p>
      {result.kind === "unauthorized" && settingsLink && (
        <p>
          <Link href="/settings/">{STATE_TEXT.openSettings}</Link>
        </p>
      )}
    </div>
  );
}

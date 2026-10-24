import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import type { CheckinDetail } from "../api/types.gen";

export interface ConfirmCard {
  key: string;
  props: unknown;
}

/**
 * The ui_confirm cards of every pending check-in (Today block 3, Activity top block).
 * `pendingKey` is the pending check-in ids joined by "," ("" when none). It reads again only when
 * that set changes or after `reread()` (a write on a part), not on every poll.
 */
export function useConfirms(pendingKey: string): { confirms: ConfirmCard[]; reread(): void } {
  const [byCheckin, setByCheckin] = useState<Readonly<Record<number, ConfirmCard[]>>>({});
  const [again, setAgain] = useState(0);
  const pendingIds = pendingKey === "" ? [] : pendingKey.split(",").map(Number);

  useEffect(() => {
    if (pendingKey === "") return;
    const ids = pendingKey.split(",").map(Number);
    let alive = true;
    void Promise.all(ids.map((id) => apiGet<CheckinDetail>(`/checkins/${id}`, "CheckinDetail"))).then((results) => {
      if (!alive) return;
      setByCheckin((prev) => {
        const next = { ...prev };
        results.forEach((r, i) => {
          const id = ids[i];
          if (r.kind === "ok") {
            next[id] = r.data.cards.filter((c) => c.component === "ui_confirm").map((c) => ({ key: `${id}:${c.toolCallId}`, props: c.props }));
          } else if (r.kind === "error" && r.status === 404) {
            delete next[id]; // gone
          } // any other failure keeps what that check-in showed before
        });
        return next;
      });
    });
    return () => {
      alive = false;
    };
  }, [pendingKey, again]);

  const reread = useCallback(() => setAgain((n) => n + 1), []);
  return { confirms: pendingIds.flatMap((id) => byCheckin[id] ?? []), reread };
}

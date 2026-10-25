import { useEffect, useRef, useState } from "react";
import { failureText } from "../api/actions";
import { apiFetch, apiGet } from "../api/client";
import type { CalendarSettings } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { Row } from "../components/Row";
import { Sheet } from "../components/Sheet";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import styles from "./Settings.module.css";

// Settings → 아이폰 캘린더에 구독 (SP9 9.7, 5.7). Make the address once, show it with a copy button;
// making it again cuts the old address off, so that asks first. The address holds a secret key: it is
// only on screen and never kept on this device.
export function CalendarSubscribe({ online }: { online: boolean }) {
  const toast = useToast();
  const poll = usePolling<CalendarSettings>(() => apiGet<CalendarSettings>("/settings/calendar", "CalendarSettings"));
  const [url, setUrl] = useState<string | null | undefined>(undefined); // undefined = not read yet
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  useEffect(() => {
    if (poll.result?.kind === "ok") setUrl(poll.result.data.url);
  }, [poll.result]);

  const make = async (rotate: boolean) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const r = await apiFetch<CalendarSettings>("POST", "/settings/calendar", { body: { rotate }, model: "CalendarSettings" });
      if (r.kind === "ok") {
        setUrl(r.data.url);
        setConfirmOpen(false);
      } else toast.show({ text: failureText(r) });
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(url ?? "");
      toast.show({ text: copy.calendar.copied });
    } catch {
      toast.show({ text: copy.calendar.copyFailed });
    }
  };

  // An older BE without the route: the section is left out (SP5 관대한 읽기).
  if (poll.result?.kind === "error" && poll.result.status === 404) return null;

  let body;
  if (url) {
    body = (
      <>
        <Row
          title={<span className={styles.url}>{url}</span>}
          trailing={
            <button type="button" className={styles.pill} onClick={() => void copyUrl()}>
              {copy.calendar.copy}
            </button>
          }
        />
        <button type="button" className={styles.action} onClick={() => setConfirmOpen(true)} disabled={busy || !online}>
          {copy.calendar.recreate}
        </button>
      </>
    );
  } else if (url === null) {
    body = (
      <button type="button" className={styles.action} onClick={() => void make(false)} disabled={busy || !online}>
        {copy.calendar.create}
      </button>
    );
  } else if (poll.result && poll.result.kind !== "ok" && poll.result.kind !== "offline") {
    body = (
      <div className={styles.control}>
        <BlockError code={poll.result.kind === "error" ? poll.result.code : poll.result.kind} onRetry={() => void poll.refresh()} />
      </div>
    );
  } else if (poll.result?.kind === "offline") {
    body = <Row title={<span className={styles.note}>{copy.offline.later}</span>} />;
  } else {
    body = (
      <div className={styles.control}>
        <Skeleton size="row" />
      </div>
    );
  }

  return (
    <>
      <Group heading={copy.calendar.heading} footer={copy.calendar.help}>
        {body}
      </Group>
      <Sheet open={confirmOpen} onClose={() => !busy && setConfirmOpen(false)} ariaLabel={copy.calendar.recreateSummary}>
        <p className={styles.summary}>{copy.calendar.recreateSummary}</p>
        <div className={styles.buttons}>
          <button type="button" className={styles.keep} onClick={() => setConfirmOpen(false)} disabled={busy}>
            {copy.settings.cancel}
          </button>
          <button type="button" className={styles.confirmDanger} onClick={() => void make(true)} disabled={busy}>
            {copy.calendar.recreate}
          </button>
        </div>
      </Sheet>
    </>
  );
}

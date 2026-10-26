import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { failureText } from "../api/actions";
import { apiFetch, apiGet } from "../api/client";
import type { DigestSettings as DigestSettingsBody, DigestSettingsUpdated, DigestSlot } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import styles from "./Settings.module.css";

type Kind = "morning" | "night";
const KINDS: Kind[] = ["morning", "night"];

// Spec 1장: morning 04:00–11:50, night 18:00–23:50, every 10 minutes (local time, not the 04:00 day boundary).
const RANGE: Record<Kind, [number, number]> = { morning: [4 * 60, 11 * 60 + 50], night: [18 * 60, 23 * 60 + 50] };
const STEP_MIN = 10;

const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

export function digestOptions(kind: Kind): string[] {
  const [lo, hi] = RANGE[kind];
  const out: string[] = [];
  for (let m = lo; m <= hi; m += STEP_MIN) out.push(hhmm(m));
  return out;
}

type Slots = Record<Kind, DigestSlot>;

// Settings → 일정 정리 알림 (SP9b 5장), under 체크인 시간 and shaped like it: a change saves right away,
// the toast says from when and can undo it, and one line says when the wake timer was not re-registered.
// Each row has an on/off switch and a time; an off row's time is dimmed. A BE without the route (the
// app is deployed first, 2.2) draws nothing.
export function DigestSettings({ online }: { online: boolean }) {
  const toast = useToast();
  const poll = usePolling<DigestSettingsBody>(() => apiGet<DigestSettingsBody>("/settings/digests", "DigestSettings"));
  const [slots, setSlots] = useState<Slots | null>(null);
  const [wakeStale, setWakeStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  useEffect(() => {
    if (poll.result?.kind !== "ok") return;
    setSlots({ morning: poll.result.data.morning, night: poll.result.data.night });
    setWakeStale(!poll.result.data.wake_updated);
  }, [poll.result]);
  useEffect(() => toast.onUndone(() => void poll.refresh()), [toast, poll.refresh]);

  const change = async (kind: Kind, slot: DigestSlot) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const r = await apiFetch<DigestSettingsUpdated>("PUT", "/settings/digests", {
        body: { kind, on: slot.on, time: slot.time },
        model: "DigestSettingsUpdated",
      });
      if (r.kind === "ok") {
        setSlots({ morning: r.data.morning, night: r.data.night });
        setWakeStale(!r.data.wake_updated);
        // The same value as before: nothing was written, so nothing to say or undo.
        if (r.data.applies !== null)
          toast.show({ text: r.data.applies === "today" ? copy.digests.fromToday : copy.digests.fromTomorrow, undoId: r.data.undo_id });
      } else toast.show({ text: failureText(r) });
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  if (poll.result?.kind === "error" && poll.result.status === 404) return null;

  let body;
  if (slots) {
    body = KINDS.map((kind) => {
      const slot = slots[kind];
      const name = copy.digests[kind];
      return (
        <Row
          key={kind}
          title={name}
          trailing={
            <span className={styles.slot}>
              <select
                className={slot.on ? styles.timeSelect : `${styles.timeSelect} ${styles.off}`}
                aria-label={name}
                value={slot.time}
                disabled={busy || !online || !slot.on}
                onChange={(e: ChangeEvent<HTMLSelectElement>) => void change(kind, { on: slot.on, time: e.target.value })}
              >
                {digestOptions(kind).map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <input
                className={styles.switch}
                type="checkbox"
                role="switch"
                aria-label={name}
                checked={slot.on}
                disabled={busy || !online}
                onChange={(e) => void change(kind, { on: e.target.checked, time: slot.time })}
              />
            </span>
          }
        />
      );
    });
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
    <Group heading={copy.digests.heading} footer={copy.digests.note}>
      {body}
      {wakeStale && <Row title={<span className={styles.note}>{copy.digests.wakeStale}</span>} />}
    </Group>
  );
}

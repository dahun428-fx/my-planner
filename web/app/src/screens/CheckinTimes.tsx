import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { failureText } from "../api/actions";
import { apiFetch, apiGet } from "../api/client";
import type { CheckinTimeItem, CheckinTimes as CheckinTimesBody, CheckinTimesUpdated } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import styles from "./Settings.module.css";

type Loop = CheckinTimeItem["loop"];
type DayType = CheckinTimeItem["day_type"];

/** SP1 default check-in times: shown read-only when the BE has no /settings/checkin-times yet (SP9 14장). */
export const SP1_SCHEDULE = { weekdays: ["09:00", "17:30"], weekend: ["10:00", "18:00"] } as const;

// Spec 8장: morning 05:00–11:30, evening 15:00–23:30, every 10 minutes.
const RANGE: Record<Loop, [number, number]> = { morning_brief: [5 * 60, 11 * 60 + 30], evening_checkin: [15 * 60, 23 * 60 + 30] };
const STEP_MIN = 10;

const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

export function checkinOptions(loop: Loop): string[] {
  const [lo, hi] = RANGE[loop];
  const out: string[] = [];
  for (let m = lo; m <= hi; m += STEP_MIN) out.push(hhmm(m));
  return out;
}

function label(loop: Loop, dayType: DayType): string {
  const c = copy.checkinTimes;
  if (dayType === "weekday") return loop === "morning_brief" ? c.weekdayMorning : c.weekdayEvening;
  return loop === "morning_brief" ? c.weekendMorning : c.weekendEvening;
}

// Spec 9.7 order: 평일 아침, 평일 저녁, 주말 아침, 주말 저녁.
const ORDER: [Loop, DayType][] = [
  ["morning_brief", "weekday"],
  ["evening_checkin", "weekday"],
  ["morning_brief", "weekend"],
  ["evening_checkin", "weekend"],
];

// Settings → 체크인 시간 (SP9 9.7). Picking a time saves it right away; the toast says from when
// and can undo it. When the BE could not re-register the laptop's wake timer, one line says so.
export function CheckinTimes({ online }: { online: boolean }) {
  const toast = useToast();
  const poll = usePolling<CheckinTimesBody>(() => apiGet<CheckinTimesBody>("/settings/checkin-times", "CheckinTimes"));
  const [items, setItems] = useState<CheckinTimeItem[] | null>(null);
  const [wakeStale, setWakeStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  useEffect(() => {
    if (poll.result?.kind !== "ok") return;
    setItems(poll.result.data.items);
    setWakeStale(!poll.result.data.wake_updated); // the same line whether the last change came from here, a card or undo
  }, [poll.result]);
  useEffect(() => toast.onUndone(() => void poll.refresh()), [toast, poll.refresh]);

  const change = async (loop: Loop, dayType: DayType, time: string) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const r = await apiFetch<CheckinTimesUpdated>("PUT", "/settings/checkin-times", {
        body: { loop, day_type: dayType, time },
        model: "CheckinTimesUpdated",
      });
      if (r.kind === "ok") {
        setItems(r.data.items);
        setWakeStale(!r.data.wake_updated);
        toast.show({
          text: r.data.applies === "today" ? copy.checkinTimes.fromToday : copy.checkinTimes.fromTomorrow,
          undoId: r.data.undo_id,
        });
      } else toast.show({ text: failureText(r) });
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  // An older BE without the route: the SP1 times, read-only (SP5 관대한 읽기).
  if (poll.result?.kind === "error" && poll.result.status === 404) {
    return (
      <Group heading={copy.settings.schedule} footer={copy.settings.scheduleNote}>
        <Row title={copy.settings.weekdays} trailing={<span className={styles.value}>{SP1_SCHEDULE.weekdays.join(" · ")}</span>} />
        <Row title={copy.settings.weekend} trailing={<span className={styles.value}>{SP1_SCHEDULE.weekend.join(" · ")}</span>} />
      </Group>
    );
  }

  let body;
  if (items) {
    body = ORDER.map(([loop, dayType]) => {
      const item = items.find((i) => i.loop === loop && i.day_type === dayType);
      if (!item) return null;
      const name = label(loop, dayType);
      return (
        <Row
          key={`${loop}:${dayType}`}
          title={name}
          trailing={
            <select
              className={styles.timeSelect}
              aria-label={name}
              value={item.time}
              disabled={busy || !online}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => void change(loop, dayType, e.target.value)}
            >
              {checkinOptions(loop).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
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
    <Group heading={copy.checkinTimes.heading} footer={copy.checkinTimes.reviewNote}>
      {body}
      {wakeStale && <Row title={<span className={styles.note}>{copy.checkinTimes.wakeStale}</span>} />}
    </Group>
  );
}

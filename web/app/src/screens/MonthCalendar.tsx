import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import type { EventList } from "../api/types.gen";
import { Icon } from "../components/icons";
import { copy } from "../lib/copy";
import { addMonths, dayName, monthGrid } from "../lib/schedule";
import styles from "./MonthCalendar.module.css";

// SP9 9.2: 큰 제목을 누르면 그 아래 펼쳐지는 한 달 달력(월요일부터). 고른 날의 달로 열리고, 앞뒤 달로 넘길 수
// 있다. 날을 누르면 그 날을 고르고(그 주로 간다) 화면이 달력을 접는다. 펼칠 때와 달을 넘길 때마다 보이는 칸
// (최대 6주) 전체의 일정을 한 번 읽어, 일정 있는 날에 한 주 띠와 같은 점을 찍는다. 못 읽으면 점 없이 보인다.
export function MonthCalendar({ selected, today, onPick }: { selected: string; today: string; onPick(date: string): void }) {
  const [month, setMonth] = useState(selected.slice(0, 7));
  const [y, m] = month.split("-").map(Number);
  const days = monthGrid(month).flat();
  const first = days[0];
  const last = days[days.length - 1];
  const [marked, setMarked] = useState<{ month: string; dates: Set<string> } | null>(null);
  useEffect(() => {
    let live = true;
    void apiGet<EventList>(`/events?start=${first}&end=${last}`, "EventList").then((r) => {
      if (live && r.kind === "ok") setMarked({ month, dates: new Set(r.data.items.map((e) => e.date)) });
    });
    return () => {
      live = false;
    };
  }, [month, first, last]);
  const has = (d: string) => marked?.month === month && marked.dates.has(d);
  return (
    <div role="group" aria-label={copy.schedule.monthOf(y, m)} className={styles.calendar}>
      <div className={styles.head}>
        <button type="button" className={styles.step} aria-label={copy.schedule.prevMonth} onClick={() => setMonth(addMonths(month, -1))}>
          <span className={styles.back}>
            <Icon name="chevron" />
          </span>
        </button>
        <span className={styles.name} aria-hidden="true">
          {copy.schedule.monthOf(y, m)}
        </span>
        <button type="button" className={styles.step} aria-label={copy.schedule.nextMonth} onClick={() => setMonth(addMonths(month, 1))}>
          <Icon name="chevron" />
        </button>
      </div>
      <div className={styles.grid}>
        {copy.schedule.weekdays.map((w) => (
          <span key={w} className={styles.weekday} aria-hidden="true">
            {w}
          </span>
        ))}
        {days.map((d) => (
          <button
            key={d}
            type="button"
            className={`${styles.day} ${d.startsWith(month) ? "" : styles.outside} tnum`}
            aria-label={has(d) ? copy.schedule.hasEvents(dayName(d)) : dayName(d)}
            aria-pressed={d === selected}
            aria-current={d === today ? "date" : undefined}
            data-events={has(d) ? "true" : undefined}
            onClick={() => onPick(d)}
          >
            {Number(d.slice(8))}
            <span className={styles.dot} aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}

import type { EventItem } from "../api/types.gen";

// SP9 5.6 그날 일정 한 줄. `hhmm`이 null이면 하루 종일. `start`는 서울 벽시계를 UTC로 바꾼 것.
export const ev = (id: number, date: string, hhmm: string | null, over: Partial<EventItem> = {}): EventItem => ({
  event_id: id,
  date,
  start: hhmm ? new Date(`${date}T${hhmm}:00+09:00`).toISOString().replace(".000Z", "Z") : null,
  end: null,
  all_day: hhmm === null,
  title: `일정 ${id}`,
  area: null,
  remind_min: hhmm === null ? 0 : 10,
  repeat: "none",
  origin: "user",
  ...over,
});

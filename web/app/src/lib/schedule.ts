import type { EventDetail, EventItem } from "../api/types.gen";
import { copy } from "./copy";
import { addDays, formatKst } from "./time";

// SP9 9.2 스케줄 탭의 날짜 계산. 일정의 날짜는 현지(서울) 날짜다(논리적 날짜가 아니다, 5.1).
// 시간대는 쓰지 않는다: "YYYY-MM-DD"를 UTC 자정으로 읽어 요일과 날 수만 센다.

/** `GET /events/{id}`·동작의 요일 이름. 월요일부터(5.1 `weekdays` 비트 순서와 같다). */
export const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type WeekdayKey = (typeof WEEKDAY_KEYS)[number];

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** 진짜 있는 날짜 "YYYY-MM-DD"인가(푸시가 여는 `?date=`). "2026-02-30" 같은 날은 아니다. */
export function isDate(v: unknown): v is string {
  if (typeof v !== "string" || !ISO_DATE.test(v)) return false;
  const [y, m, d] = v.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

/** 0 = 월요일 … 6 = 일요일. */
export function weekdayIndex(d: string): number {
  const [y, m, day] = d.split("-").map(Number);
  return (new Date(Date.UTC(y, m - 1, day)).getUTCDay() + 6) % 7;
}

/** 그 날이 든 주의 월~일 일곱 날(현지 날짜). */
export function weekOf(d: string): string[] {
  const monday = addDays(d, -weekdayIndex(d));
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

/**
 * 한 달 달력(9.2): "YYYY-MM"의 1일이 든 주부터 마지막 날이 든 주까지, 주마다 월~일 일곱 날. 앞뒤 달의 날도
 * 칸을 채운다(그 달인지는 `date.startsWith(month)`로 안다).
 */
export function monthGrid(month: string): string[][] {
  const first = `${month}-01`;
  const [y, m] = month.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
  const weeks: string[][] = [];
  for (let start = weekOf(first)[0]; start <= last; start = addDays(start, 7)) weeks.push(weekOf(start));
  return weeks;
}

/** "YYYY-MM"의 앞뒤 달. */
export function addMonths(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1 + n, 1)).toISOString().slice(0, 7);
}

/** 이 기기 시계의 서울 날짜(스케줄 띠의 "오늘"). 논리적 날짜가 아니다: 01:00은 그날이다. */
export function localToday(): string {
  return formatKst(new Date().toISOString(), "date");
}

/** 그날 목록 순서(9.2): 하루 종일 먼저, 그다음 시작 시각순. 같으면 BE 순서 그대로. */
export function dayOrder(items: readonly EventItem[]): EventItem[] {
  const key = (e: EventItem) => (e.all_day || e.start === null ? "" : e.start);
  return items.map((e, i) => ({ e, i })).sort((a, b) => key(a.e).localeCompare(key(b.e)) || a.i - b.i).map(({ e }) => e);
}

const parts = (d: string) => d.split("-").map(Number);

/** 날의 읽는 이름 "10월 27일 (화)": 띠·달력 칸, 그날 목록의 이름. */
export function dayName(d: string): string {
  const [, m, day] = parts(d);
  return copy.parts.dayLabel(m, day, copy.schedule.weekdays[weekdayIndex(d)]);
}

/** 10장 "{M/D}". */
export function mdOf(d: string): string {
  const [, m, day] = parts(d);
  return copy.schedule.md(m, day);
}

/** 그날 일정 줄의 시각: "14:00", 하루 종일은 "하루 종일"(9.2). `start`는 UTC라 서울 시각으로 바꾼다. */
export function clockOf(e: Pick<EventItem, "all_day" | "start">): string {
  return e.all_day || e.start === null ? copy.schedule.allDay : formatKst(e.start, "HH:mm");
}

/** 10장 "일정 때": 한 번짜리 "10/27 14:00"·"10/27 하루 종일", 반복 "매일 14:00"·"매주 월·수 14:00"·"매달 31일 14:00". */
export function whenOf(e: Pick<EventDetail, "date" | "time" | "all_day" | "repeat" | "weekdays">): string {
  const at = e.all_day || e.time === null ? copy.schedule.allDay : e.time;
  switch (e.repeat) {
    case "daily":
      return copy.schedule.everyDay(at);
    case "weekly":
      return copy.schedule.everyWeek(
        WEEKDAY_KEYS.filter((k) => e.weekdays?.includes(k))
          .map((k) => copy.schedule.weekdays[WEEKDAY_KEYS.indexOf(k)])
          .join("·"),
        at,
      );
    case "monthly":
      return copy.schedule.everyMonth(parts(e.date)[2], at);
    default:
      return `${mdOf(e.date)} ${at}`;
  }
}

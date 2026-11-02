import { describe, expect, it } from "vitest";
import type { CheckinSummary, EventItem, Today } from "../api/types.gen";
import { copy } from "../lib/copy";
import { FIXED_CHIPS, frontChip, quickChips } from "./quickChips";

// 시험 날짜(계획 작업 방식): 2026-10-27(화), 2026-11-01(일).
const today = (over: Partial<Today> = {}): Today => ({
  date: "2026-10-27",
  day_boundary: "04:00",
  weekday: "화",
  brief: null,
  condition: null,
  todos: [],
  cards: [],
  checkins: [],
  habits: [],
  events: [],
  missed_reminders: [],
  ...over,
});

const run = (over: Partial<CheckinSummary> = {}): CheckinSummary => ({
  id: 341,
  loop: "evening_checkin",
  cadence: "day",
  state: "pending",
  scheduled_for: "2026-10-27T12:00:00Z",
  sent_at: "2026-10-27T12:00:05Z", // 21:00 서울
  reply_until: "2026-10-27T19:00:00Z", // 다음 날 04:00 서울
  answered_at: null,
  answered_via: null,
  delivered_via: ["app"],
  conversation_ids: { app: null, telegram: null },
  ...over,
});

const event = (start: string, over: Partial<EventItem> = {}): EventItem => ({
  event_id: 9,
  title: "치과",
  date: "2026-10-27",
  start,
  end: null,
  all_day: false,
  area: null,
  origin: "user",
  remind_min: 10,
  repeat: "none",
  ...over,
});

const at = (iso: string) => new Date(iso);

describe("FIXED_CHIPS", () => {
  it("four chips in 9.5 order with their sentences", () => {
    expect(FIXED_CHIPS.map((c) => [c.label, c.text])).toEqual([
      ["할 일 추가", "할 일 추가할래요"],
      ["일정 추가", "일정 하나 추가할래요"],
      ["메모하기", "메모 하나 남길래요"],
      ["오늘 정리해줘", "오늘 정리해줘"],
    ]);
    expect(FIXED_CHIPS.every((c) => c.checkinId === undefined)).toBe(true);
  });

  // SP9c 3: the add chips open a one-line write; 오늘 정리해줘 sends its sentence with `chip`.
  it("the add chips write, the others send; only today and next carry a chip on the wire", () => {
    expect(FIXED_CHIPS.map((c) => [c.key, c.mode, c.wire])).toEqual([
      ["todo", "write", "todo"],
      ["event", "write", "event"],
      ["memo", "write", "memo"],
      ["today", "send", "today"],
    ]);
    const checkin = frontChip(today({ checkins: [run()] }), at("2026-10-27T13:00:00Z"));
    expect(checkin).toMatchObject({ key: "checkin", mode: "send" });
    expect(checkin).not.toHaveProperty("wire");
    expect(frontChip(today({ events: [event("2026-10-27T05:00:00Z")] }), at("2026-10-27T03:00:00Z"))).toMatchObject({ key: "next", mode: "send", wire: "next" });
  });
});

describe("frontChip", () => {
  it("an unanswered check-in inside its reply window: 체크인 하기 with that run's id", () => {
    const chip = frontChip(today({ checkins: [run()] }), at("2026-10-27T13:00:00Z"));
    expect(chip).toMatchObject({ key: "checkin", label: "체크인 하기", text: "체크인 할게요", checkinId: 341 });
  });

  it("a /today from a BE before the schedule (no events) gives no next-event chip (spec 14)", () => {
    const old: Partial<Today> = today();
    delete old.events;
    expect(frontChip(old as Today, new Date("2026-10-27T05:00:00Z"))).toBeNull();
  });

  it("no check-in chip once answered, after the window, or before it is sent", () => {
    const now = at("2026-10-27T13:00:00Z");
    expect(frontChip(today({ checkins: [run({ state: "answered", answered_at: "2026-10-27T12:30:00Z" })] }), now)).toBeNull();
    expect(frontChip(today({ checkins: [run({ state: "missed" })] }), now)).toBeNull();
    expect(frontChip(today({ checkins: [run()] }), at("2026-10-27T19:00:01Z"))).toBeNull();
    expect(frontChip(today({ checkins: [run({ sent_at: null })] }), now)).toBeNull();
  });

  it("Sunday with this week's review open: 이번 주 돌아보기", () => {
    const review = run({ id: 400, loop: "review", cadence: "week", sent_at: "2026-11-01T11:00:00Z", reply_until: "2026-11-01T19:00:00Z" });
    const t = today({ date: "2026-11-01", weekday: "일", checkins: [review] });
    expect(frontChip(t, at("2026-11-01T12:00:00Z"))).toMatchObject({ key: "review", label: "이번 주 돌아보기", text: "이번 주 돌아볼래요", checkinId: 400 });
    // 01:00 on Monday is still the logical Sunday (the day starts at 04:00).
    expect(frontChip(t, at("2026-11-01T16:00:00Z"))?.key).toBe("review");
  });

  it("the check-in comes before the review, the review before the next event", () => {
    const review = run({ id: 400, loop: "review", cadence: "week", sent_at: "2026-11-01T11:00:00Z", reply_until: "2026-11-01T19:00:00Z" });
    const evening = run({ id: 401, sent_at: "2026-11-01T11:30:00Z", reply_until: "2026-11-01T19:00:00Z" });
    const soon = event("2026-11-01T13:00:00Z", { date: "2026-11-01" });
    const now = at("2026-11-01T12:00:00Z");
    expect(frontChip(today({ date: "2026-11-01", checkins: [review, evening], events: [soon] }), now)?.key).toBe("checkin");
    expect(frontChip(today({ date: "2026-11-01", checkins: [review], events: [soon] }), now)?.key).toBe("review");
  });

  it("an event starting within 3 hours: 다음 일정 보기 (2:59 ahead yes, 3:01 ahead no)", () => {
    const now = at("2026-10-27T02:00:00Z"); // 11:00 서울
    const chip = frontChip(today({ events: [event("2026-10-27T04:59:00Z")] }), now);
    expect(chip).toMatchObject({ key: "next", label: "다음 일정 보기", text: "다음 일정 알려줘" });
    expect(chip?.checkinId).toBeUndefined();
    expect(frontChip(today({ events: [event("2026-10-27T05:01:00Z")] }), now)).toBeNull();
  });

  it("no next-event chip for an all-day event or one that has started", () => {
    const now = at("2026-10-27T02:00:00Z");
    expect(frontChip(today({ events: [event("2026-10-27T00:00:00Z", { all_day: true })] }), now)).toBeNull();
    expect(frontChip(today({ events: [event(null as never, { all_day: true, start: null })] }), now)).toBeNull();
    expect(frontChip(today({ events: [event("2026-10-27T01:59:00Z")] }), now)).toBeNull();
  });

  it("nothing fits: no front chip", () => {
    expect(frontChip(today(), at("2026-10-27T02:00:00Z"))).toBeNull();
  });

  it("a weekly review on Sunday is not a check-in chip, and not offered on another day as 돌아보기", () => {
    const review = run({ id: 400, loop: "review", cadence: "week", sent_at: "2026-10-27T11:00:00Z", reply_until: "2026-10-27T19:00:00Z" });
    // Tuesday: an open weekly review is still an unanswered run in its window (rule 1).
    expect(frontChip(today({ checkins: [review] }), at("2026-10-27T12:00:00Z"))?.key).toBe("checkin");
  });
});

describe("quickChips", () => {
  it("the front chip goes before the fixed four; none without /today", () => {
    const chips = quickChips(today({ checkins: [run()] }), at("2026-10-27T13:00:00Z"));
    expect(chips.map((c) => c.label)).toEqual([copy.chat.chips.checkin.label, ...FIXED_CHIPS.map((c) => c.label)]);
    expect(quickChips(null, at("2026-10-27T13:00:00Z"))).toEqual(FIXED_CHIPS);
  });
});

describe("mate chips (SP12 5.7)", () => {
  it("are the three of Appendix A, whatever /today says", () => {
    const soon = today({ events: [event("2026-10-27T01:00:00Z")] });
    for (const t of [null, soon]) {
      const chips = quickChips(t, new Date("2026-10-27T00:00:00Z"), "mate");
      expect(chips.map((c) => c.label)).toEqual(["오늘 뭐 할까?", "운동 기록하기", "플랜 고치기"]);
      expect(chips.map((c) => c.wire)).toEqual(["mate_today", "mate_log", "mate_plan"]);
      expect(chips.every((c) => c.mode === "send")).toBe(true);
    }
  });
});

describe("life manager chips (SP15 11장)", () => {
  it("are the three of the spec; the upload chip opens the attach menu and is never sent", () => {
    const chips = quickChips(null, new Date("2026-10-27T00:00:00Z"), "manager");
    expect(chips.map((c) => c.key)).toEqual(["manager_full", "manager_week", "manager_upload"]);
    expect(chips.map((c) => c.label)).toEqual(["전체 진단", "이번 주 뭐부터?", "자료 올리기"]);
    expect(chips.map((c) => c.mode)).toEqual(["send", "send", "attach"]);
    expect(chips.map((c) => c.wire)).toEqual(["manager_full", "manager_week", undefined]);
    expect(chips.map((c) => c.pictogram ?? c.icon)).toEqual(["status", "today", "memo"]); // status: the status tab's pictogram
    expect(chips.some((c) => c.disabled)).toBe(false);
  });

  it("the full diagnosis chip is off once today's is done", () => {
    const chips = quickChips(null, new Date("2026-10-27T00:00:00Z"), "manager", { fullDiagnosisOk: false });
    expect(chips[0]).toMatchObject({ key: "manager_full", label: "오늘은 이미 했어요", disabled: true });
    expect(chips.slice(1).some((c) => c.disabled)).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import type { CurveHistory, HistoryEvent } from "../api/types.gen";
import { applySensitive, UNASSIGNED_ID, collapsedOnPhone, eventDateText, filterEvents, ladderText, orderChapters, yearsText } from "./history";

const ev = (id: number, kind: HistoryEvent["kind"]): HistoryEvent => ({
  id,
  date: "2025-09",
  precision: "month",
  kind,
  kind_certainty: "fact",
  title: `꾸민 사건 ${id}`,
  note: null,
  area: null,
  origin: "seed",
  certainty: "fact",
  sensitive: false,
});

const chapter = (id: number, start: string): CurveHistory["chapters"][number] => ({
  id,
  title: `꾸민 챕터 ${id}`,
  theme: null,
  start,
  end: null,
  sketch: null,
  certainty: "fact",
  ladder: null,
  events: [],
  hidden_sensitive: { count: 0, years: [] },
});

const hidden = { count: 0, years: [] };
const history = (ids: number[], unassigned: HistoryEvent[] = []): CurveHistory => ({
  since_year: 2019,
  chapters: ids.map((id) => chapter(id, `20${30 - id}-01`)), // newest first, as the BE sends
  unassigned: { events: unassigned, hidden_sensitive: hidden },
  summary: { chapters: ids.length, events: 0, highest: null, turning_points: { count: 0, years: [] }, longest: null, records_since: null },
});

const ids = (list: Array<{ id: number } | "unassigned">) => list.map((c) => (c === "unassigned" ? c : c.id));

describe("history lib", () => {
  it("filter_by_kind", () => {
    const events = [ev(1, "high"), ev(2, "low"), ev(3, "turning_point"), ev(4, "high")];
    expect(filterEvents(events, "all").map((e) => e.id)).toEqual([1, 2, 3, 4]);
    expect(filterEvents(events, "high").map((e) => e.id)).toEqual([1, 4]);
    expect(filterEvents(events, "low").map((e) => e.id)).toEqual([2]);
    expect(filterEvents(events, "turning_point").map((e) => e.id)).toEqual([3]);
  });

  it("unassigned_last_when_recent_first_and_first_when_oldest", () => {
    const h = history([3, 2, 1], [ev(9, "high")]);
    expect(ids(orderChapters(h, "recent"))).toEqual([3, 2, 1, "unassigned"]);
    expect(ids(orderChapters(h, "oldest"))).toEqual(["unassigned", 1, 2, 3]);
    expect(ids(orderChapters(history([2, 1]), "oldest"))).toEqual([1, 2]);
  });

  it("phone_expands_recent_4", () => {
    const h = history([6, 5, 4, 3, 2, 1]);
    expect([...collapsedOnPhone(h.chapters, new Set())]).toEqual([2, 1]);
    expect([...collapsedOnPhone(h.chapters, new Set([2]))]).toEqual([1]);
    expect(collapsedOnPhone(history([2, 1]).chapters, new Set()).size).toBe(0);
  });

  it("years_text_open_end", () => {
    expect(yearsText("2019-03", "2022-12")).toBe("2019 – 2022");
    expect(yearsText("2026-10", null)).toBe("2026 –");
  });

  it("event_date_text_month_and_year", () => {
    expect(eventDateText("2019-03", "month")).toBe("2019.03");
    expect(eventDateText("2018", "year")).toBe("2018");
    expect(eventDateText("2026-02-14", "day")).toBe("2026.02.14");
  });

  it("ladder_text_drops_trailing_zero", () => {
    expect(ladderText(6.0)).toBe("6");
    expect(ladderText(6.3)).toBe("6.3");
    expect(ladderText(5.14)).toBe("5.1");
  });

  it("hidden_sensitive_alone_keeps_the_unassigned_group", () => {
    const h = history([1]);
    h.unassigned.hidden_sensitive = { count: 1, years: [2020] };
    expect(ids(orderChapters(h, "recent"))).toEqual([1, "unassigned"]);
  });

  it("apply_sensitive_hides_unopened_groups_and_recounts", () => {
    const secret = { ...ev(7, "turning_point"), sensitive: true, date: "2021-04" };
    const h = history([2, 1], [{ ...secret, id: 8, date: "2018-01" }]);
    h.chapters[0].events = [ev(1, "high"), secret];
    h.summary = { ...h.summary, events: 3, turning_points: { count: 2, years: [2018, 2021] } };
    const hid = applySensitive(h, new Set(), false);
    expect(hid.chapters[0].events.map((e) => e.id)).toEqual([1]);
    expect(hid.chapters[0].hidden_sensitive).toEqual({ count: 1, years: [2021] });
    expect(hid.unassigned.hidden_sensitive).toEqual({ count: 1, years: [2018] });
    expect(hid.summary.events).toBe(1);
    expect(hid.summary.turning_points).toEqual({ count: 0, years: [] });
    const one = applySensitive(h, new Set([2]), false);
    expect(one.chapters[0].events.map((e) => e.id)).toEqual([1, 7]);
    expect(one.unassigned.events).toEqual([]);
    expect(one.summary.events).toBe(2);
    expect(one.summary.turning_points).toEqual({ count: 1, years: [2021] });
    expect(applySensitive(h, new Set([2, UNASSIGNED_ID]), false)).toBe(h);
    expect(applySensitive(h, new Set(), true)).toBe(h);
  });
});

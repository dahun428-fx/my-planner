import { describe, expect, it } from "vitest";
import type { ResultItem } from "../ui/types";
import { hideCoveredActivity } from "./hideCoveredActivity";
import type { ViewPart } from "./parts";

// SP6 11.4 as SP9 9.6 changed it: the change is one line and the toast undoes, so a drawn ui_result
// item covers every activity it lists, with or without an undo_id. Review Focus 4.
const activity = (...ids: number[]): ViewPart => ({ kind: "activity", confirmation: "옮겼어요", undoIds: ids.slice(0, 1), activityIds: ids });
function item(id: number, undo_id: number | null, activity_ids: number[]): ResultItem {
  return {
    todo: { id, title: `할 일 ${id}`, status: "open", planned_for: "2026-10-27", scheduled_at: null },
    change: "moved",
    before: { status: null, planned_for: "2026-10-25", scheduled_at: null, title: null },
    after: { status: "open", planned_for: "2026-10-27", scheduled_at: null, title: null },
    activity_ids,
    undo_id,
  };
}
const result = (toolCallId: string, ...items: ResultItem[]): ViewPart => ({ kind: "ui", toolCallId, name: "ui_result", props: { task_ids: items.map((i) => i.todo.id) }, data: { today: "2026-10-24", items } });
const all = () => true;
const hide = (parts: ViewPart[], drawn: (p: Extract<ViewPart, { kind: "ui" }>) => boolean = all) => hideCoveredActivity(parts, drawn);
const text: ViewPart = { kind: "text", text: "옮겼어요." };

describe("hideCoveredActivity", () => {
  it("all covered hides", () => {
    const parts = [text, result("c1", item(53, 931, [931])), activity(931)];
    expect(hide(parts)).toEqual([text, parts[1]]);
  });

  it("partly covered keeps", () => {
    const parts = [result("c1", item(53, 931, [931])), activity(931, 932)];
    expect(hide(parts)).toEqual(parts);
  });

  it("an item without undo_id still covers its activities (the card shows them; undo is the toast's)", () => {
    const parts = [result("c1", item(53, null, [931, 932])), activity(931, 932)];
    expect(hide(parts)).toEqual([parts[0]]);
    const one = [result("c1", item(53, null, [931])), activity(931)];
    expect(hide(one)).toEqual([one[0]]);
  });

  it("an activity no item lists keeps the line", () => {
    const parts = [result("c1", item(53, null, [931])), activity(931, 940)];
    expect(hide(parts)).toEqual(parts);
  });

  it("period list only keeps", () => {
    const period: ViewPart = { kind: "ui", toolCallId: "c1", name: "ui_period_list", props: { day: "2026-10-24", highlight_task_ids: [53] }, data: { today: "2026-10-24", days: [], outside: [] } };
    const parts = [period, activity(931)];
    expect(hide(parts)).toEqual(parts);
  });

  it("two results covering same id hide once", () => {
    const parts = [result("c1", item(53, 931, [931])), result("c2", item(53, 931, [931])), activity(931)];
    expect(hide(parts)).toEqual([parts[0], parts[1]]);
  });

  it("two results covering two activities hide the box", () => {
    const parts = [result("c1", item(53, 931, [931])), result("c2", item(54, 932, [932])), activity(931, 932)];
    expect(hide(parts)).toEqual([parts[0], parts[1]]);
  });

  it("a result period list pair still hides by the result alone", () => {
    const period: ViewPart = { kind: "ui", toolCallId: "c2", name: "ui_period_list", props: { day: "2026-10-24" } };
    const parts = [result("c1", item(53, 931, [931])), period, activity(931)];
    expect(hide(parts)).toEqual([parts[0], period]);
  });

  it("empty activityIds keeps", () => {
    const parts = [result("c1", item(53, 931, [931])), activity()];
    expect(hide(parts)).toEqual(parts);
  });

  it("a result without data covers nothing", () => {
    const parts: ViewPart[] = [{ kind: "ui", toolCallId: "c1", name: "ui_result", props: { task_ids: [53] } }, activity(931)];
    expect(hide(parts)).toEqual(parts);
  });

  it("a result that will not draw keeps the box", () => {
    // No catalog yet, or props the catalog refuses: an UnknownPart shows no undo, so the box stays.
    const parts = [result("c1", item(53, 931, [931])), activity(931)];
    expect(hide(parts, () => false)).toEqual(parts);
    const two = [result("c1", item(53, 931, [931])), result("c2", item(54, 932, [932])), activity(931, 932)];
    expect(hide(two, (p) => p.toolCallId === "c1")).toEqual(two);
  });
});

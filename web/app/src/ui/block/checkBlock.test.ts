import { describe, expect, it } from "vitest";
import type { BlockElement, InnerElement } from "../primitives/types";
import { checkBlock } from "./checkBlock";

// SP6 spec 7.2: one smallest case per rule the schema cannot say.
const text = (md = "글"): InnerElement => ({ type: "text", md });
const stat = (label = "완료"): InnerElement => ({ type: "stat", label, value: "1개" });
const rows = (...task_ids: number[]): InnerElement => ({ type: "todo_rows", task_ids });
const divider: InnerElement = { type: "divider" };
const send: BlockElement = { type: "buttons", items: [{ label: "더 알려 줘", do: { kind: "send" } }] };
const block = (...children: BlockElement[]) => ({ title: "카드", children });

describe("checkBlock", () => {
  it("counts group children toward 12", () => {
    const eleven = Array.from({ length: 11 }, () => text());
    expect(checkBlock(block(...eleven))).toBe(true);
    expect(checkBlock(block(...eleven.slice(0, 9), { type: "group", layout: "row", children: [{ type: "stat", label: "a", value: "1" }, { type: "stat", label: "b", value: "2" }] }))).toBe(true);
    // 11 at the top + a group of 1 + 2 = 14 > 12.
    expect(checkBlock(block(...eleven, { type: "group", layout: "row", children: [{ type: "stat", label: "a", value: "1" }, { type: "stat", label: "b", value: "2" }] }))).toBe(false);
    expect(checkBlock(block(...eleven, text()))).toBe(true);
    expect(checkBlock(block(...eleven, text(), text()))).toBe(false);
  });

  it("buttons must be last and single", () => {
    expect(checkBlock(block(text(), send))).toBe(true);
    expect(checkBlock(block(send, text()))).toBe(false);
    expect(checkBlock(block(text(), send, send))).toBe(false);
  });

  it("two todo_rows ok three not", () => {
    expect(checkBlock(block(rows(1), rows(2)))).toBe(true);
    expect(checkBlock(block(rows(1), rows(2), rows(3)))).toBe(false);
    expect(checkBlock(block(rows(1), rows(2), { type: "group", layout: "stack", children: [text(), rows(3)] }))).toBe(false);
  });

  it("divider not first last or adjacent including inside stack", () => {
    expect(checkBlock(block(text(), divider, text()))).toBe(true);
    expect(checkBlock(block(divider, text()))).toBe(false);
    expect(checkBlock(block(text(), divider))).toBe(false);
    expect(checkBlock(block(text(), divider, divider, text()))).toBe(false);
    expect(checkBlock(block(text(), { type: "group", layout: "stack", children: [text(), divider] }))).toBe(false);
    expect(checkBlock(block(text(), { type: "group", layout: "stack", children: [divider, text()] }))).toBe(false);
    expect(checkBlock(block(text(), { type: "group", layout: "stack", children: [text(), divider, text()] }))).toBe(true);
  });

  it("needs a content element", () => {
    expect(checkBlock(block({ type: "heading", text: "제목" }))).toBe(false);
    expect(checkBlock(block({ type: "heading", text: "제목" }, send))).toBe(false);
    expect(checkBlock(block({ type: "heading", text: "제목" }, stat()))).toBe(true);
  });

  it("complete must target a row id", () => {
    const done = (task_id: number): BlockElement => ({ type: "buttons", items: [{ label: "끝났어", do: { kind: "complete", task_id } }] });
    expect(checkBlock(block(rows(61), done(61)))).toBe(true);
    expect(checkBlock(block(rows(61), done(62)))).toBe(false);
    expect(checkBlock(block(text(), done(61)))).toBe(false);
    expect(checkBlock(block({ type: "group", layout: "stack", children: [text(), rows(61)] }, done(61)))).toBe(true);
  });

  it("anything without a children list is refused", () => {
    expect(checkBlock(null)).toBe(false);
    expect(checkBlock({ title: "카드" })).toBe(false);
  });
});

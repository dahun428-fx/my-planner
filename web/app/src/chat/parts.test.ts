import type { UIMessage } from "ai";
import { describe, expect, it } from "vitest";
import { conversationIdOf, toViewParts } from "./parts";

const msg = (parts: UIMessage["parts"], metadata?: unknown): UIMessage => ({ id: "m-1-1", role: "assistant", parts, metadata });
const todo = { id: 7, title: "장보기", status: "draft", planned_for: "2026-10-25", scheduled_at: null, parent_id: null, areas: [], note: "", priority: null, completed_at: null };

describe("toViewParts", () => {
  it("text parts", () => {
    expect(toViewParts(msg([{ type: "step-start" }, { type: "text", text: "네, 추가할게요." }]))).toEqual([{ kind: "text", text: "네, 추가할게요." }]);
  });

  it("ui tool part with data", () => {
    const parts = toViewParts(
      msg([
        {
          type: "tool-ui_todo_draft",
          toolCallId: "tc_1",
          state: "output-available",
          input: { task_ids: [7] },
          output: { ok: true, data: { todos: [todo] } },
        },
      ] as UIMessage["parts"]),
    );
    expect(parts).toEqual([{ kind: "ui", toolCallId: "tc_1", name: "ui_todo_draft", props: { task_ids: [7] }, data: { todos: [todo] } }]);
  });

  it("ui tool part without ok output has no data", () => {
    const parts = toViewParts(
      msg([{ type: "tool-ui_choice", toolCallId: "tc_2", state: "input-available", input: { question: "q" } }] as UIMessage["parts"]),
    );
    expect(parts).toEqual([{ kind: "ui", toolCallId: "tc_2", name: "ui_choice", props: { question: "q" } }]);
  });

  it("dynamic-tool ui part", () => {
    const parts = toViewParts(
      msg([
        { type: "dynamic-tool", toolName: "ui_summary_card", toolCallId: "h_3", state: "output-available", input: { title: "t" }, output: { ok: true, data: {} } },
        { type: "dynamic-tool", toolName: "add_task", toolCallId: "tc_4", state: "output-available", input: {}, output: {} },
      ] as UIMessage["parts"]),
    );
    expect(parts).toEqual([{ kind: "ui", toolCallId: "h_3", name: "ui_summary_card", props: { title: "t" }, data: {} }]);
  });

  it("hides non-ui tools", () => {
    const parts = toViewParts(
      msg([
        { type: "tool-add_task", toolCallId: "tc_01", state: "output-available", input: { title: "치과" }, output: { id: 1 } },
        { type: "text", text: "추가할게요." },
      ] as UIMessage["parts"]),
    );
    expect(parts).toEqual([{ kind: "text", text: "추가할게요." }]);
  });

  it("activity with confirmation", () => {
    const parts = toViewParts(msg([{ type: "data-activity", data: { activity_ids: [1], undo_ids: [1], confirmation: "✓ 추가: 치과 → 내일" } }] as UIMessage["parts"])); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(parts).toEqual([{ kind: "activity", confirmation: "✓ 추가: 치과 → 내일", undoIds: [1], activityIds: [1] }]); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
  });

  it("activity without confirmation keeps undo", () => {
    const parts = toViewParts(msg([{ type: "data-activity", data: { activity_ids: [1], undo_ids: [1] } }] as UIMessage["parts"]));
    expect(parts).toEqual([{ kind: "activity", confirmation: null, undoIds: [1], activityIds: [1] }]);
  });

  it("reads activity_ids", () => {
    const parts = toViewParts(msg([{ type: "data-activity", data: { activity_ids: [931, 932], undo_ids: [931], confirmation: "옮겼어요" } }] as UIMessage["parts"]));
    expect(parts).toEqual([{ kind: "activity", confirmation: "옮겼어요", undoIds: [931], activityIds: [931, 932] }]);
    // Before SP6 the app did not read them; a BE without them gives [].
    const none = toViewParts(msg([{ type: "data-activity", data: { undo_ids: [931], activity_ids: ["x"] } }] as UIMessage["parts"]));
    expect(none).toEqual([{ kind: "activity", confirmation: null, undoIds: [931], activityIds: [] }]);
  });

  it("input-streaming ui part is not rendered yet", () => {
    const parts = toViewParts(
      msg([{ type: "tool-ui_todo_draft", toolCallId: "tc_1", state: "input-streaming", input: { task_ids: [7] } }] as UIMessage["parts"]),
    );
    expect(parts).toEqual([]);
  });

  it("ignores status data, reasoning and files", () => {
    const parts = toViewParts(
      msg([
        { type: "data-status", data: { state: "queued" } },
        { type: "reasoning", text: "..." },
        { type: "text", text: "" },
      ] as UIMessage["parts"]),
    );
    expect(parts).toEqual([]);
  });
});

describe("conversationIdOf", () => {
  it("reads metadata.conversation_id", () => {
    expect(conversationIdOf(msg([], { conversation_id: 3, channel: "app" }))).toBe(3);
    expect(conversationIdOf(msg([], { conversation_id: null }))).toBeNull();
    expect(conversationIdOf(msg([]))).toBeNull();
    expect(conversationIdOf(msg([], { conversation_id: "3" }))).toBeNull();
  });
});

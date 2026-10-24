import "fake-indexeddb/auto";
import { clear, keys } from "idb-keyval";
import { afterEach, describe, expect, it } from "vitest";
import { loadParts, pruneParts, saveParts } from "./localParts";
import type { ViewPart } from "./parts";

const DAY = 86_400_000;
const ui: ViewPart = { kind: "ui", toolCallId: "tc_1", name: "ui_todo_draft", props: { task_ids: [7] } };

afterEach(async () => {
  await clear();
});

describe("localParts", () => {
  it("saves only ui parts", async () => {
    await saveParts("m-1-1", [{ kind: "text", text: "안녕" }, ui, { kind: "activity", confirmation: "\u2713 추가: 치과", undoIds: [1] }]);
    expect(await loadParts("m-1-1")).toEqual([ui]);
    expect(await keys()).toEqual(["parts:m-1-1"]);
  });

  it("does not store a message without ui parts", async () => {
    await saveParts("m-1-2", [{ kind: "text", text: "안녕" }]);
    expect(await loadParts("m-1-2")).toBeNull();
    expect(await keys()).toEqual([]);
  });

  it("prunes to 200 and 7 days", async () => {
    const now = Date.parse("2026-10-24T12:00:00Z");
    await saveParts("old", [ui], now - 8 * DAY);
    for (let i = 0; i < 205; i++) await saveParts(`m-${i}`, [ui], now - DAY + i * 1000);
    await pruneParts(now);
    const left = (await keys()) as string[];
    expect(left).toHaveLength(200);
    expect(left).not.toContain("parts:old");
    for (let i = 0; i < 5; i++) expect(left).not.toContain(`parts:m-${i}`);
    expect(left).toContain("parts:m-204");
    expect(await loadParts("m-5", now)).toEqual([ui]);
  });

  it("does not return expired parts", async () => {
    const now = Date.parse("2026-10-24T12:00:00Z");
    await saveParts("m-1", [ui], now - 8 * DAY);
    expect(await loadParts("m-1", now)).toBeNull();
  });
});

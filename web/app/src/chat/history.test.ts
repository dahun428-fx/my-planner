import "fake-indexeddb/auto";
import { clear } from "idb-keyval";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { saveConn } from "../lib/connection";
import { serveHistory } from "../test/chat";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { loadHistory } from "./history";
import { toViewParts } from "./parts";

beforeEach(() => saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN }));
afterEach(async () => {
  await clear();
});

// SP15 11장: the life manager's conversations are a list of their own (`?agent=manager`), its lines
// say `manager`, and an answer's expert notes come back from the history as the stream gave them.
describe("loadHistory, life manager", () => {
  const notes = [
    { expert: "career", text: "가짜 커리어 소견" },
    { expert: "relationship", text: "가짜 관계 소견" },
  ];

  it("reads the manager's conversation with its expert notes and no elsewhere lines", async () => {
    const seen = serveHistory({
      conversations: [{ id: 5, last_message_at: "2026-10-24T01:00:00Z" }],
      messages: {
        5: [
          {
            id: "m-5-1",
            at: "2026-10-24T01:00:00Z",
            speaker: "secretary",
            text: "비서 대화",
          },
        ],
      },
      manager: {
        conversations: [{ id: 12, last_message_at: "2026-10-24T02:01:00Z" }],
        messages: {
          12: [
            {
              id: "u-12-1",
              at: "2026-10-24T02:00:00Z",
              speaker: "user",
              text: "연봉이 오르면?",
            },
            {
              id: "m-12-2",
              at: "2026-10-24T02:01:00Z",
              speaker: "manager",
              text: "가짜 답",
              expert_notes: notes,
            },
          ],
        },
      },
      activity: [
        {
          id: 1,
          at: "2026-10-24T03:00:00Z",
          channel: "telegram",
          summary: "텔레그램에서 바뀜",
        },
      ],
    });
    const r = await loadHistory(undefined, { agent: "manager" });
    expect(seen.agents).toEqual(["manager"]);
    expect(seen.messages).toEqual([12]);
    expect(r.kind).toBe("ok");
    if (r.kind !== "ok") return;
    expect(r.history.conversationId).toBe(12);
    expect(r.history.messages.map((m) => m.role)).toEqual([
      "user",
      "assistant",
    ]);
    expect(toViewParts(r.history.messages[1])).toEqual([
      { kind: "text", text: "가짜 답" },
      { kind: "notes", notes },
    ]);
    expect(
      toViewParts(r.history.messages[0]).some((p) => p.kind === "notes"),
    ).toBe(false);
    expect(seen.activitySince).toEqual([]); // readElsewhere is the secretary's only
    expect(r.history.elsewhere).toEqual([]);
  });

  it("the secretary still reads elsewhere lines and asks without an agent", async () => {
    const seen = serveHistory({
      conversations: [{ id: 5, last_message_at: "2026-10-24T01:00:00Z" }],
      messages: {
        5: [
          {
            id: "m-5-1",
            at: "2026-10-24T01:00:00Z",
            speaker: "secretary",
            text: "비서 대화",
          },
        ],
      },
      activity: [
        {
          id: 1,
          at: "2026-10-24T03:00:00Z",
          channel: "telegram",
          summary: "텔레그램에서 바뀜",
        },
      ],
    });
    const r = await loadHistory(undefined, { agent: "secretary" });
    expect(seen.agents).toEqual([null]);
    expect(r.kind === "ok" && r.history.elsewhere).toEqual([
      "텔레그램에서 바뀜",
    ]);
  });
});

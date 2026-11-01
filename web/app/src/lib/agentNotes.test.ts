import { describe, expect, it } from "vitest";
import { splitAgentNotes } from "./agentNotes";

// SP14 10장: the brief's observation lines ("{이름}: {관찰}") come out of the Markdown body.
describe("splitAgentNotes", () => {
  it("takes a trailing mate line out of the body", () => {
    expect(splitAgentNotes("좋은 아침이에요.\n\n운동메이트: 토요일만 비어요.")).toEqual({
      body: "좋은 아침이에요.",
      notes: [{ agent: "mate", text: "토요일만 비어요." }],
    });
  });

  it("knows the manager", () => {
    expect(splitAgentNotes("라이프 매니저: 가짜 관찰이에요.")).toEqual({
      body: "",
      notes: [{ agent: "manager", text: "가짜 관찰이에요." }],
    });
  });

  it("takes a line from the middle too, in order", () => {
    expect(splitAgentNotes("첫 줄\n운동메이트: 하나\n가운데 줄\n라이프 매니저: 둘\n끝 줄")).toEqual({
      body: "첫 줄\n가운데 줄\n끝 줄",
      notes: [
        { agent: "mate", text: "하나" },
        { agent: "manager", text: "둘" },
      ],
    });
  });

  it("leaves other lines as they are", () => {
    const text = "메이트: 아니에요\n운동메이트:붙여씀\n- 목록 줄";
    expect(splitAgentNotes(text)).toEqual({ body: text, notes: [] });
  });
});

import { describe, expect, it } from "vitest";
import { parseMiniMd } from "./parseMiniMd";

describe("parseMiniMd", () => {
  it("bold and newline", () => {
    expect(parseMiniMd("이번 주는 **화요일**이\n비어요")).toEqual([
      [
        { text: "이번 주는 ", strong: false },
        { text: "화요일", strong: true },
        { text: "이", strong: false },
      ],
      [{ text: "비어요", strong: false }],
    ]);
  });

  it("unpaired stars stay literal", () => {
    expect(parseMiniMd("**굵게")).toEqual([[{ text: "**굵게", strong: false }]]);
  });

  it("html and links stay literal", () => {
    const md = "<b>x</b> [a](b) `c` # h _i_";
    expect(parseMiniMd(md)).toEqual([[{ text: md, strong: false }]]);
  });

  it("an empty line stays a line", () => {
    expect(parseMiniMd("a\n\nb")).toEqual([[{ text: "a", strong: false }], [], [{ text: "b", strong: false }]]);
  });
});

import { describe, expect, it } from "vitest";
import { codePoints, placeRead, shiftAnchor } from "./shiftAnchor";

// SP10 7.4 test_shift_anchor_cases: the changed span is what is left between the common start and
// the common end of the two texts.
describe("shiftAnchor (spec 7.4)", () => {
  it.each([
    // [what, prev, next, anchor, expected]
    ["no change", "abcdef", "abcdef", 3, 3],
    ["typing wholly before the anchor moves it by the added length", "abcdef", "abXYcdef", 3, 5],
    ["deleting wholly before the anchor moves it back", "abcdef", "acdef", 3, 2],
    ["replacing a span wholly before the anchor moves it by the difference", "abcdef", "aZZZdef", 3, 4],
    ["typing wholly after the anchor leaves it", "abcdef", "abcdeXf", 3, 3],
    ["deleting wholly after the anchor leaves it", "abcdef", "abcd", 3, 3],
    ["typing right at the anchor counts as before it", "abcdef", "abcXYdef", 3, 5],
    ["a change that covers the anchor puts it at the change's new end", "abcdef", "aQf", 3, 2],
    ["deleting a span over the anchor puts it where the span was", "abcdef", "af", 3, 1],
    ["clearing everything puts it at 0", "abcdef", "", 4, 0],
    ["writing into an empty text with the anchor at 0", "", "hello", 0, 5],
    ["a change ending right at the anchor is before it", "abcdef", "aXYZdef", 3, 4],
    ["a change starting right at the anchor is after it", "abcdef", "abcXef", 3, 3],
    ["Korean typing before the anchor", "첫 줄\n둘째", "첫 줄 더\n둘째", 4, 6],
  ])("%s", (_what, prev, next, anchor, expected) => {
    expect(shiftAnchor(prev, next, anchor)).toBe(expected);
  });

  it("follows a run of edits step by step", () => {
    let text = "제목\n본문";
    let anchor = 3; // start of 본문
    const steps = ["제목 하나\n본문", "제목 하나\n본문 끝", "목 하나\n본문 끝"];
    for (const next of steps) {
      anchor = shiftAnchor(text, next, anchor);
      text = next;
    }
    expect(text.slice(anchor)).toBe("본문 끝");
  });
});

describe("placeRead (spec 7.4)", () => {
  it("in an empty body it goes in as it is", () => {
    expect(placeRead("", 0, "읽은 글")).toEqual({ body: "읽은 글", cut: false });
  });

  it("in the middle of a line it gets a line break before and after", () => {
    expect(placeRead("앞뒤", 1, "글")).toEqual({ body: "앞\n글\n뒤", cut: false });
  });

  it("no extra break where there already is one, nor at the start or the end", () => {
    expect(placeRead("앞\n뒤", 2, "글").body).toBe("앞\n글\n뒤");
    expect(placeRead("앞\n", 2, "글").body).toBe("앞\n글");
    expect(placeRead("뒤", 0, "글").body).toBe("글\n뒤");
    expect(placeRead("앞", 1, "글").body).toBe("앞\n글");
  });

  it("the read text's own leading and trailing line breaks are dropped", () => {
    expect(placeRead("앞", 1, "\n글\n\n").body).toBe("앞\n글");
  });

  it("an anchor past the end goes at the end", () => {
    expect(placeRead("앞", 9, "글").body).toBe("앞\n글");
  });

  it("over 20,000 code points the rest is left out (code points, as the BE counts)", () => {
    const body = "가".repeat(19_990);
    const out = placeRead(body, body.length, "😀".repeat(20));
    expect(out.cut).toBe(true);
    // 19,990 + 1 line break + 9 emoji = 20,000 code points (but more UTF-16 units)
    expect(codePoints(out.body)).toBe(20_000);
    expect(out.body.endsWith(`\n${"😀".repeat(9)}`)).toBe(true);
  });

  it("a body already at the limit takes nothing", () => {
    const body = "가".repeat(20_000);
    expect(placeRead(body, 3, "글")).toEqual({ body, cut: true });
  });

  it("exactly at the limit is not cut", () => {
    const body = "가".repeat(19_998);
    const out = placeRead(body, body.length, "나");
    expect(out).toEqual({ body: `${body}\n나`, cut: false });
  });
});

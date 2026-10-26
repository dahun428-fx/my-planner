import { describe, expect, it } from "vitest";
import { swipeStep } from "./PhotoViewer";

// SP10 7.1: left and right through the photos. A swipe left (negative dx) goes to the next one.
describe("swipeStep", () => {
  it.each([
    // [dx, at, n, to]
    [-40, 0, 3, 1],
    [-200, 1, 3, 2],
    [-40, 2, 3, null], // the last one: nowhere further
    [40, 2, 3, 1],
    [120, 1, 3, 0],
    [40, 0, 3, null], // the first one: nowhere before
    [-39, 0, 3, null], // too short to count
    [39, 1, 3, null],
    [0, 1, 3, null],
    [-100, 0, 1, null], // a single photo
  ])("dx %i from %i of %i → %s", (dx, at, n, to) => {
    expect(swipeStep(dx, at, n)).toBe(to);
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import conditions from "../test/fixtures/conditions.json";
import { ConditionDots } from "./ConditionDots";

const dots = () => Array.from(document.querySelectorAll<SVGElement>(".cdots-dot"));

describe("ConditionDots", () => {
  it("gaps are not zero", () => {
    render(
      <ConditionDots
        from="2026-10-18"
        to="2026-10-24"
        items={[
          { date: "2026-10-18", score: 3, note: null },
          { date: "2026-10-20", score: 5, note: null },
          { date: "2026-10-24", score: 1, note: null },
        ]}
      />,
    );
    // one dot per logged day, at its own day and score; the four empty days have no dot and no line
    expect(dots().map((d) => [d.dataset.date, d.dataset.score])).toEqual([
      ["2026-10-18", "3"],
      ["2026-10-20", "5"],
      ["2026-10-24", "1"],
    ]);
    expect(document.querySelector("polyline, path.cdots-line")).toBeNull();
    // a score of 1 sits on the lowest grid line; nothing is drawn below it as a zero
    const [three, five, one] = dots().map((d) => Number(d.getAttribute("y1")));
    expect(five).toBeLessThan(three);
    expect(three).toBeLessThan(one);
    expect(one).toBe(Number(document.querySelector(".cdots-grid[data-score='1']")!.getAttribute("y1")));
    expect(dots().every((d) => d.getAttribute("x1") === d.getAttribute("x2"))).toBe(true);
    // x is the day's own column: 10/20 is the third of seven
    const xs = dots().map((d) => Number(d.getAttribute("x1")));
    expect(xs).toEqual([0.5, 2.5, 6.5]);
  });

  it("puts the average and the logged days in the head", () => {
    render(<ConditionDots from={conditions.from} to={conditions.to} items={conditions.items} />);
    expect(screen.getByText("평균 3.7 · 21일 기록")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "컨디션 지난 30일: 21일 기록, 평균 3.7" })).toBeInTheDocument();
    expect(dots()).toHaveLength(21);
    expect(document.querySelectorAll(".cdots-grid")).toHaveLength(5);
    expect(document.querySelector("[style]")).toBeNull();
  });

  it("labels days on one step that lands on today", () => {
    render(<ConditionDots from={conditions.from} to={conditions.to} items={conditions.items} />);
    const ticks = Array.from(document.querySelectorAll(".cdots-x span")).map((s) => s.textContent).filter(Boolean);
    expect(ticks).toEqual(["9/26", "10/3", "10/10", "10/17", "10/24"]);
  });

  it("shows one sentence when nothing is logged", () => {
    render(<ConditionDots from="2026-09-25" to="2026-10-24" items={[]} />);
    expect(screen.getByText("저녁 체크인에서 컨디션을 기록하면 여기에 그려져요.")).toBeInTheDocument();
    expect(screen.queryByText(/평균/)).toBeNull();
    expect(dots()).toHaveLength(0);
  });
});

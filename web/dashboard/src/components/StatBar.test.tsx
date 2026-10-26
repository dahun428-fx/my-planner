import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatBar } from "./StatBar";

const bonus = (c: HTMLElement) => Array.from(c.querySelectorAll("rect.stat-bonus"));

describe("StatBar bonus cells", () => {
  it("bonus_cells_are_outlined_after_base", () => {
    const { container } = render(<StatBar label="커리어" score={6} bonus={1.2} />);
    const cells = bonus(container);
    expect(cells).toHaveLength(1);
    expect(cells[0].getAttribute("x")).toBe("60"); // right after the base fill
    expect(cells[0].getAttribute("width")).toBe("20"); // ceil(1.2) = 2 cells of 10
    expect(container.querySelector(".stat-fill")!.getAttribute("width")).toBe("60");
    expect(container.querySelector("svg")!.getAttribute("aria-label")).toBe("커리어 6 / 10");
  });

  it("no_bonus_cells_without_base", () => {
    const { container } = render(<StatBar label="배움" score={null} bonus={0.4} />);
    expect(bonus(container)).toHaveLength(0);
    expect(container.querySelector(".stat-fill")).toBeNull();
  });

  it("bonus_clipped_at_10", () => {
    const { container } = render(<StatBar label="건강" score={9} bonus={1.5} />);
    const cells = bonus(container);
    expect(cells).toHaveLength(1);
    expect(cells[0].getAttribute("width")).toBe("10"); // min(10 - 9, ceil(1.5))
  });

  it("zero bonus draws none, and a full base leaves no room", () => {
    expect(bonus(render(<StatBar label="a" score={5} />).container)).toHaveLength(0);
    expect(bonus(render(<StatBar label="a" score={10} bonus={2} />).container)).toHaveLength(0);
  });
});

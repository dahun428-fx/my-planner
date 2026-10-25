import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PICTOGRAM_NAMES, Pictogram, PictogramSprite } from "./pictograms.gen";

describe("Pictogram", () => {
  it("is hidden from assistive tech without a label", () => {
    const { container } = render(<Pictogram name="career" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("role")).toBeNull();
    expect(svg.querySelector("use")!.getAttribute("href")).toBe("#p-career");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("stroke-width")).toBe("1.75");
  });

  it("is an image with a name when labelled", () => {
    const { getByRole } = render(<Pictogram name="high" label="높은 때" />);
    const img = getByRole("img", { name: "높은 때" });
    expect(img.getAttribute("aria-hidden")).toBeNull();
  });

  it("draws 16px with a 2 stroke", () => {
    const { container } = render(<Pictogram name="todo" size={16} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("stroke-width")).toBe("2");
    expect(svg.getAttribute("width")).toBe("16");
  });

  it("the sprite holds one symbol per name", () => {
    const { container } = render(<PictogramSprite />);
    expect(container.querySelector("svg.pictogram-sprite")!.getAttribute("aria-hidden")).toBe("true");
    expect([...container.querySelectorAll("symbol")].map((s) => s.id)).toEqual(PICTOGRAM_NAMES.map((n) => `p-${n}`));
  });
});

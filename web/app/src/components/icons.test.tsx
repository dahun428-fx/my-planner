import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./icons";

// SP10 7.5: the chat's two photo buttons, by the pictogram rule (24px, 1.75 stroke, round ends, no emoji).
describe("Icon camera and photo", () => {
  it.each(["camera", "photo"] as const)("%s is 24px, 1.75 stroke, round ends, drawn as paths", (name) => {
    const { container } = render(<Icon name={name} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("24");
    expect(svg.getAttribute("height")).toBe("24");
    expect(svg.getAttribute("stroke-width")).toBe("1.75");
    expect(svg.getAttribute("stroke-linecap")).toBe("round");
    expect(svg.getAttribute("stroke-linejoin")).toBe("round");
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.querySelectorAll("path").length).toBeGreaterThan(0);
    expect(svg.textContent).toBe("");
  });
});

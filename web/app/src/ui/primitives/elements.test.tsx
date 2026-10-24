import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MiniText } from "./MiniText";

describe("primitives", () => {
  it("text renders only strong and br", () => {
    const { container } = render(<MiniText md={"<b>x</b> 이번 주는 **화요일**이\n[a](b) 비어요"} />);
    const p = container.querySelector("p")!;
    expect(p.querySelectorAll("strong")).toHaveLength(1);
    expect(p.querySelector("strong")).toHaveTextContent("화요일");
    expect(p.querySelectorAll("br")).toHaveLength(1);
    expect([...p.querySelectorAll("*")].map((e) => e.tagName)).toEqual(["STRONG", "BR"]);
    expect(p.innerHTML).not.toContain("<b>");
    expect(p).toHaveTextContent("<b>x</b> 이번 주는 화요일이[a](b) 비어요");
  });
});

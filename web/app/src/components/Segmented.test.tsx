import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Segmented } from "./Segmented";

describe("Segmented hint (SP14 10장)", () => {
  it("shows a hint under the label; the radio's name stays the label, the hint describes it", () => {
    render(
      <Segmented
        ariaLabel="대화 상대"
        value="a"
        onChange={() => {}}
        options={[
          { value: "a", label: "비서" },
          { value: "b", label: "운동메이트", hint: "새로 본 것 3개" },
        ]}
      />,
    );
    expect(screen.getByText("새로 본 것 3개")).toBeInTheDocument();
    const mate = screen.getByRole("radio", { name: "운동메이트" });
    expect(mate).toHaveAccessibleDescription("새로 본 것 3개");
    expect(screen.getByRole("radio", { name: "비서" })).not.toHaveAttribute("aria-describedby");
  });
});

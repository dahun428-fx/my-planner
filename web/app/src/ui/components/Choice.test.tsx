import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { makeCtx } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { Choice } from "./Choice";

const props = { question: "무엇부터 할까요?", options: [{ id: "a", label: "운동" }, { id: "b", label: "독서" }] };

describe("Choice", () => {
  it("chooses label once", async () => {
    const onChoose = vi.fn();
    renderWithProviders(<Choice props={props} ctx={makeCtx({ onChoose })} />);
    await userEvent.click(screen.getByRole("button", { name: "독서" }));
    expect(onChoose).toHaveBeenCalledExactlyOnceWith("독서");
    expect(screen.getByRole("button", { name: "독서" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "독서" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "운동" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "운동" }));
    expect(onChoose).toHaveBeenCalledTimes(1);
  });
});

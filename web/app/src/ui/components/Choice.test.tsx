import { readFileSync } from "node:fs";
import { join } from "node:path";
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

  it("pills are off where a choice cannot be sent (a card pinned to Today)", async () => {
    renderWithProviders(<Choice props={props} ctx={makeCtx({ where: "today" })} />);
    for (const b of screen.getAllByRole("button")) expect(b).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "독서" }));
    expect(screen.getByRole("button", { name: "독서" })).toHaveAttribute("aria-pressed", "false");
  });

  it("pill is 44px", () => {
    // SP6 6.1: ui_choice's pills are the buttons part's 44px pills (were 36px).
    renderWithProviders(<Choice props={props} ctx={makeCtx({ onChoose: vi.fn() })} />);
    expect(screen.getByRole("button", { name: "운동" })).toHaveClass("pill");
    const strip = (f: string) => readFileSync(join(__dirname, f), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const css = strip("../primitives/primitives.module.css");
    const pill = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(([, sel]) => sel.trim() === ".pill")?.[2] ?? "";
    expect(pill).toMatch(/min-height:\s*var\(--control-h\)/);
    expect(strip("../../styles/tokens.css")).toMatch(/--control-h:\s*44px/);
  });
});

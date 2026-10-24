import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeCtx } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { SummaryCard } from "./SummaryCard";

describe("SummaryCard", () => {
  it("renders up to 8 lines", () => {
    const lines = Array.from({ length: 10 }, (_, i) => `줄 ${i + 1}`);
    renderWithProviders(<SummaryCard props={{ title: "이번 주 운동", lines }} ctx={makeCtx()} />);
    expect(screen.getByRole("heading", { name: "이번 주 운동" })).toBeInTheDocument();
    expect(screen.getByText("줄 8")).toBeInTheDocument();
    expect(screen.queryByText("줄 9")).toBeNull();
  });
});

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { renderWithProviders } from "../../test/render";
import { UnknownPart } from "./UnknownPart";

describe("UnknownPart", () => {
  it.each([
    [{ title: "제목", question: "질문", summary: "요약" }, "제목"],
    [{ question: "질문", summary: "요약" }, "질문"],
    [{ summary: "요약" }, "요약"],
  ])("shows the first of title / question / summary", (props, text) => {
    renderWithProviders(<UnknownPart props={props} />);
    expect(screen.getByText(copy.parts.unknown)).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("shows only the line for odd props", () => {
    renderWithProviders(<UnknownPart props={null} />);
    expect(screen.getByText(copy.parts.unknown)).toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { CheckRow } from "./CheckRow";

const inList = (el: React.ReactElement) => render(<ul>{el}</ul>);

describe("CheckRow", () => {
  it("four states", async () => {
    const onToggle = vi.fn();
    const { unmount } = inList(<CheckRow title="운동" checked={false} disabled={false} onToggle={onToggle} />);
    const box = screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동") });
    expect(box).toHaveAttribute("aria-checked", "false");
    await userEvent.click(box);
    expect(onToggle).toHaveBeenCalledTimes(1);
    unmount();

    // done: struck, filled, off
    const done = inList(<CheckRow title="장보기" checked disabled struck onToggle={onToggle} />);
    const doneBox = screen.getByRole("checkbox", { name: copy.parts.checkLabel("장보기") });
    expect(doneBox).toHaveAttribute("aria-checked", "true");
    expect(doneBox).toBeDisabled();
    expect(screen.getByText("장보기")).toHaveClass("struck");
    done.unmount();

    // dropped: struck, no checkbox, "뺌"
    const dropped = inList(<CheckRow title="청소" meta={copy.parts.dropped} checked={false} disabled struck mark="none" onToggle={onToggle} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("청소")).toHaveClass("struck");
    expect(screen.getByText("뺌")).toBeInTheDocument();
    dropped.unmount();

    // dot: not checkable here
    inList(<CheckRow title="읽기" checked={false} disabled mark="dot" onToggle={onToggle} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("읽기")).not.toHaveClass("struck");
  });

  it("highlight has hidden text", () => {
    const { container } = inList(<CheckRow title="회의" checked={false} disabled={false} highlight onToggle={() => {}} />);
    expect(container.querySelector("li")).toHaveClass("highlight");
    expect(screen.getByText(copy.parts.changedBySecretary)).toHaveClass("srOnly");
  });

  it("meta shows", () => {
    inList(<CheckRow title="회의" meta="14:00" checked={false} disabled={false} onToggle={() => {}} />);
    expect(screen.getByText("14:00")).toHaveClass("rowMeta");
    expect(screen.queryByText(copy.parts.changedBySecretary)).toBeNull();
  });
});

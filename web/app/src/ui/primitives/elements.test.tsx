import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../../lib/copy";
import { makeCtx, makeTodo } from "../../test/parts";
import { Bullets } from "./Bullets";
import { Divider } from "./Divider";
import { Group } from "./Group";
import { Heading } from "./Heading";
import { MiniText } from "./MiniText";
import { Progress } from "./Progress";
import { Stat } from "./Stat";
import { Tags } from "./Tags";
import { TodoRows } from "./TodoRows";

const css = readFileSync(join(__dirname, "primitives.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const ruleOf = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter(([, sel]) => sel.trim() === selector).map(([, , body]) => body);

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

  it("heading is h4", () => {
    render(<Heading text="이번 주 운동" first />);
    const h = screen.getByRole("heading", { level: 4, name: "이번 주 운동" });
    expect(h).toHaveClass("heading");
    expect(h).toHaveClass("first");
  });

  it("stat aria label", () => {
    render(<Stat label="컨디션 평균" value="3.6" delta={{ text: "0.4", trend: "up" }} />);
    const g = screen.getByRole("group", { name: "컨디션 평균 3.6, 지난번보다 올라감 0.4" });
    const delta = g.querySelector(".delta")!;
    expect(delta).toHaveTextContent(/^↑ 0\.4$/);
    // The change is always --text-2: no colour for up or down (P4).
    expect(delta.className).toBe("delta");
    expect(ruleOf(".delta")).toHaveLength(1);
    expect(ruleOf(".delta")[0]).toMatch(/color:\s*var\(--text-2\)/);
  });

  it("stat without a change and the other trends", () => {
    const { unmount } = render(<Stat label="완료" value="4개" delta={null} />);
    expect(screen.getByRole("group", { name: "완료 4개" })).toBeInTheDocument();
    unmount();
    render(
      <>
        <Stat label="잠" value="6시간" delta={{ text: "1시간", trend: "down" }} />
        <Stat label="걸음" value="8천" delta={{ text: "0", trend: "same" }} />
      </>,
    );
    expect(screen.getByRole("group", { name: "잠 6시간, 지난번보다 내려감 1시간" })).toHaveTextContent("↓ 1시간");
    expect(screen.getByRole("group", { name: "걸음 8천, 지난번과 같음" })).toHaveTextContent("→ 0");
  });

  it("progress element values", () => {
    const { container } = render(<Progress label="운동" value={3} max={5} />);
    const bar = container.querySelector("progress")!;
    expect(bar).toHaveAttribute("value", "3");
    expect(bar).toHaveAttribute("max", "5");
    expect(bar).toHaveAccessibleName(copy.parts.progressAria("운동", 3, 5));
    expect(screen.getByText("3/5")).toBeInTheDocument();
    expect(container.textContent).not.toContain("%");
  });

  it("todo rows fallback and empty", () => {
    const ctx = makeCtx();
    const { unmount } = render(<TodoRows ids={[1, 2]} checkable ctx={ctx} onComplete={() => {}} />);
    expect(screen.getByText("할 일 2개")).toBeInTheDocument();
    unmount();
    render(<TodoRows ids={[1, 2]} todos={[]} checkable ctx={ctx} onComplete={() => {}} />);
    expect(screen.getByText("보여 줄 할 일이 없어요")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("todo rows complete calls handler", async () => {
    const onComplete = vi.fn();
    const todos = [makeTodo(54, "장보기", "done"), makeTodo(53, "운동 30분"), { ...makeTodo(55, "청소", "dropped") }];
    render(<TodoRows ids={[53, 54, 55]} todos={todos} today="2026-10-24" checkable ctx={makeCtx()} onComplete={onComplete} />);
    // In the order of the ids, not of `todos`.
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["운동 30분", "장보기", "청소뺌"]);
    await userEvent.click(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동 30분") }));
    expect(onComplete).toHaveBeenCalledExactlyOnceWith(53);
    const done = screen.getByRole("checkbox", { name: copy.parts.checkLabel("장보기") });
    expect(done).toHaveAttribute("aria-checked", "true");
    expect(done).toBeDisabled();
    expect(screen.getByText("장보기")).toHaveClass("struck");
    expect(screen.getByText("청소")).toHaveClass("struck");
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("todo rows: a row completed here, a date, dots and read-only", () => {
    const todos = [makeTodo(53, "운동 30분"), { ...makeTodo(56, "치과"), planned_for: "2026-10-27" }];
    const { unmount } = render(<TodoRows ids={[53, 56]} todos={todos} today="2026-10-24" completed={new Set([53])} checkable ctx={makeCtx()} onComplete={() => {}} />);
    expect(screen.getByRole("checkbox", { name: copy.parts.checkLabel("운동 30분") })).toBeDisabled();
    expect(screen.getByText("10월 27일 (화)")).toBeInTheDocument();
    unmount();
    const r = render(<TodoRows ids={[53]} todos={todos} checkable={false} ctx={makeCtx()} onComplete={() => {}} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
    r.unmount();
    for (const ctx of [makeCtx({ readOnly: true }), makeCtx({ restored: true })]) {
      const x = render(<TodoRows ids={[53]} todos={todos} checkable ctx={ctx} onComplete={() => {}} />);
      expect(screen.getByRole("checkbox")).toBeDisabled();
      x.unmount();
    }
  });

  it("tags show area names", () => {
    render(<Tags items={[{ area: "health" }, { text: "오전" }]} />);
    const list = screen.getByRole("list", { name: copy.parts.tagsLabel });
    expect([...list.querySelectorAll("li")].map((li) => li.textContent)).toEqual(["건강", "오전"]);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("bullets list", () => {
    render(<Bullets items={["화요일 오후가 비어 있어요", "**목요일**은 일정이 셋이에요"]} />);
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["화요일 오후가 비어 있어요", "**목요일**은 일정이 셋이에요"]);
    expect(document.querySelector("strong")).toBeNull();
  });

  it("divider hidden from a11y", () => {
    const { container } = render(<Divider />);
    expect(container.querySelector("hr")).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("separator")).toBeNull();
  });

  it("group row and stack classes", () => {
    const { container, unmount } = render(<Group layout="row">{[<Stat key="a" label="완료" value="4개" />, <Stat key="b" label="남은 것" value="3개" />]}</Group>);
    expect(container.firstElementChild).toHaveClass("row");
    expect(container.firstElementChild!.children).toHaveLength(2);
    unmount();
    const s = render(<Group layout="stack">{[<Heading key="a" text="a" />, <MiniText key="b" md="b" />]}</Group>);
    expect(s.container.firstElementChild).toHaveClass("stack");
  });
});

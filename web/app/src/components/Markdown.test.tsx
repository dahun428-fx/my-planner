import { act, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { Markdown, markdownChunk } from "./Markdown";

// The renderer arrives in its own chunk; until then the text shows plain.
async function md(text: string) {
  await markdownChunk.load();
  const view = render(<Markdown text={text} />);
  return view.container.firstElementChild as HTMLElement;
}

describe("Markdown", () => {
  it("shows the text plain before the renderer has loaded, then rendered", async () => {
    // A fresh copy of the module: the test setup has already loaded the renderer into the shared one.
    vi.resetModules();
    const fresh = await import("./Markdown");
    const view = render(<fresh.Markdown text={"**굵게** 그리고"} />);
    expect(view.container.textContent).toBe("**굵게** 그리고");
    expect(await screen.findByText("굵게", { selector: "strong" })).toBeInTheDocument();
  });

  it("bold, italic, strikethrough and inline code", async () => {
    const root = await md("**굵게** *기울임* ~~취소~~ `코드`");
    expect(root.querySelector("strong")).toHaveTextContent("굵게");
    expect(root.querySelector("em")).toHaveTextContent("기울임");
    expect(root.querySelector("del")).toHaveTextContent("취소");
    expect(root.querySelector("code")).toHaveTextContent("코드");
  });

  it("ordered and unordered lists", async () => {
    const root = await md("- 하나\n- 둘\n\n1. 첫째\n2. 둘째");
    expect(root.querySelectorAll("ul > li")).toHaveLength(2);
    expect(root.querySelectorAll("ol > li")).toHaveLength(2);
    expect(root.querySelector("ol li")).toHaveTextContent("첫째");
  });

  it("task list items are read-only checkboxes", async () => {
    await md("- [x] 끝남\n- [ ] 남음");
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).toBeChecked();
    expect(boxes[1]).not.toBeChecked();
    for (const b of boxes) expect(b).toBeDisabled();
  });

  it("blockquote", async () => {
    const root = await md("> 인용한 말");
    expect(root.querySelector("blockquote")).toHaveTextContent("인용한 말");
  });

  it("fenced code block in a scrolling pre", async () => {
    const root = await md("```\nconst a = 1;\n```");
    const pre = root.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre!.querySelector("code")).toHaveTextContent("const a = 1;");
  });

  it("table inside a horizontally scrolling wrapper", async () => {
    const root = await md("| 이름 | 값 |\n|---|---|\n| 가 | 1 |");
    const table = root.querySelector("table");
    expect(table).not.toBeNull();
    expect(table!.parentElement).toHaveClass("tableWrap");
    expect(table!.querySelectorAll("td")).toHaveLength(2);
  });

  // Aligned columns would come as style="text-align:…", which style-src 'self' blocks: classes instead.
  it("aligned table columns use classes, never a style attribute", async () => {
    const root = await md("| 왼 | 가운데 | 오른 | 그냥 |\n|:--|:-:|--:|---|\n| 1 | 2 | 3 | 4 |");
    const [l, c, r, plain] = [...root.querySelectorAll("tbody td")];
    expect(l).toHaveClass("alignLeft");
    expect(c).toHaveClass("alignCenter");
    expect(r).toHaveClass("alignRight");
    expect(plain.className).toBe("");
    expect(root.querySelector("thead th")).toHaveClass("alignLeft");
    expect(root.querySelector("thead th")).toHaveTextContent("왼");
    expect(root.querySelectorAll("[style]")).toHaveLength(0);
  });

  // The model's text must not set DOM ids (a footnote's default is <footer><div id=…>).
  it("footnotes keep their text with no ids and no footer", async () => {
    const root = await md("# 제목\n본문[^1]\n\n[^1]: 덧붙인 말");
    expect(root.querySelector("[id]")).toBeNull();
    expect(root.querySelector("footer")).toBeNull();
    expect(root.textContent).toContain("덧붙인 말");
    expect(root.querySelector("sup")).toHaveTextContent("1");
  });

  // Pinned: a bare www. address becomes an http link, like GFM.
  it("www. autolinks to http", async () => {
    await md("보기: www.example.com");
    expect(screen.getByRole("link", { name: "www.example.com" })).toHaveAttribute("href", "http://www.example.com");
  });

  it("headings are bold body text, not h1-h6", async () => {
    const root = await md("# 큰 제목\n## 작은 제목\n본문");
    expect(root.querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
    expect(screen.getByText("큰 제목").closest("strong")).not.toBeNull();
    expect(screen.getByText("큰 제목").closest("p")).toHaveClass("heading");
  });

  it("keeps line breaks", async () => {
    const root = await md("첫 줄\n둘째 줄");
    expect(root.textContent).toContain("첫 줄\n둘째 줄");
  });

  it("http and https links open in a new tab", async () => {
    await md("[사이트](https://example.com/a) 와 http://example.org");
    const links = screen.getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/a", "http://example.org"]);
    for (const a of links) {
      expect(a).toHaveAttribute("target", "_blank");
      expect(a).toHaveAttribute("rel", "noopener noreferrer");
    }
  });

  it("javascript:, data:, mailto: and relative links are plain text", async () => {
    const root = await md("[x](javascript:alert(1)) [y](data:text/html,hi) [z](mailto:a@b.c) [w](/settings/) [v](JaVaScRiPt:alert(1))");
    expect(root.querySelector("a")).toBeNull();
    expect(root.textContent).toContain("x");
    expect(root.textContent).toContain("w");
  });

  it("images show their alt text, never an img", async () => {
    const root = await md("앞 ![그림 설명](https://example.com/a.png) 뒤");
    expect(root.querySelector("img")).toBeNull();
    expect(root.textContent).toContain("그림 설명");
  });

  it("raw HTML shows as text and makes no elements", async () => {
    const text = '<script>alert(1)</script>\n\n<img src=x onerror="alert(1)"> <b>굵게</b>\n\n<div onclick="x()">블록</div>';
    const root = await md(text);
    expect(root.querySelector("script, img, b, div, [onerror], [onclick]")).toBeNull();
    expect(root.textContent).toContain("<script>alert(1)</script>");
    expect(root.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it("mid-stream: an unclosed code fence is already a code block", async () => {
    const root = await md("앞 문장\n\n```js\nconst a = 1;");
    expect(root.querySelector("pre code")).toHaveTextContent("const a = 1;");
  });

  // Half a link is not a link to "t" yet; the bare start of its address autolinks like any URL
  // (GFM) and turns into the real link once ")" arrives.
  it("mid-stream: half a link makes no link of its text", async () => {
    const view = render(<Markdown text="[t](https://ex" />);
    expect(screen.queryByRole("link", { name: "t" })).toBeNull();
    expect(view.container.textContent).toContain("[t](");
    view.rerender(<Markdown text="[t](https://ex)" />);
    expect(screen.getByRole("link", { name: "t" })).toHaveAttribute("href", "https://ex");
  });

  it("stays plain text when the chunk cannot load", async () => {
    vi.resetModules();
    const fresh = await import("./Markdown");
    const load = vi.spyOn(fresh.markdownChunk, "load").mockRejectedValue(new Error("chunk failed"));
    const view = render(<fresh.Markdown text={"**굵게** 그대로"} />);
    await waitFor(() => expect(load).toHaveBeenCalled());
    await act(async () => {});
    expect(view.container.textContent).toBe("**굵게** 그대로");
    expect(view.container.querySelector("strong")).toBeNull();
    load.mockRestore();
  });

  it("every prefix of a streaming answer renders", async () => {
    const full = "# 제목\n**굵게** 와 *기울임*\n\n- [x] 할 일\n1. 하나\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```js\nconst a = `x`;\n```\n> 인용 [링크](https://example.com)";
    await markdownChunk.load();
    const view = render(<Markdown text="" />);
    for (let i = 1; i <= full.length; i++) {
      act(() => view.rerender(<Markdown text={full.slice(0, i)} />));
    }
    expect(view.container.querySelector("table")).not.toBeNull();
    expect(view.container.querySelector("a")).toHaveAttribute("href", "https://example.com");
  });
});

describe("Markdown styles", () => {
  const css = readFileSync(join(__dirname, "Markdown.module.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const rule = (selector: string) =>
    [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, sel]) => sel.split(",").some((s) => s.trim() === selector))
      .map(([, , body]) => body)
      .join("");

  it("code blocks and tables scroll sideways; links use the secretary hue", () => {
    expect(rule(".root pre")).toMatch(/overflow-x:\s*auto/);
    expect(rule(".root pre")).toMatch(/font-family:[^;]*monospace/);
    expect(rule(".tableWrap")).toMatch(/overflow-x:\s*auto/);
    expect(rule(".link")).toMatch(/color:\s*var\(--hue\)/);
    expect(rule(".root .alignLeft")).toMatch(/text-align:\s*left/);
    expect(rule(".root .alignCenter")).toMatch(/text-align:\s*center/);
    expect(rule(".root .alignRight")).toMatch(/text-align:\s*right/);
  });
});

import { memo, type ReactNode, useEffect, useState } from "react";
import type { RenderMarkdown } from "./markdownRender";
import styles from "./Markdown.module.css";

// The parser (markdown-to-jsx, ~26KB gzip) is its own chunk so the first screen stays inside 180KB
// (spec 9). An object so a test can wait on it. The styles stay here: they ship with _app.
export const markdownChunk = {
  load: (): Promise<RenderMarkdown> => {
    loading ??= import("./markdownRender").then((m) => {
      render = m.renderMarkdown;
      return m.renderMarkdown;
    });
    return loading;
  },
};
let render: RenderMarkdown | null = null;
const CLASSES: MarkdownClasses = { heading: styles.heading, link: styles.link, tableWrap: styles.tableWrap, task: styles.task };
let loading: Promise<RenderMarkdown> | null = null;

/** The classes the renderer puts on its elements. */
export type MarkdownClasses = Record<"heading" | "link" | "tableWrap" | "task", string>;

// The secretary's words (chat answers, the brief, a check-in) as Markdown: no raw HTML, no
// images, links only http(s). Until the parser arrives (or if it cannot) the text shows plain.
// Re-parsed whole on each change, so a reply still streaming in is fine at any cut.
export const Markdown = memo(function Markdown({ text, className }: { text: string; className?: string }) {
  const [ready, setReady] = useState<RenderMarkdown | null>(() => render);
  useEffect(() => {
    if (ready) return;
    let live = true;
    markdownChunk.load().then(
      (r) => live && setReady(() => r),
      () => {
        loading = null; // a later mount tries again
      },
    );
    return () => {
      live = false;
    };
  }, [ready]);
  let body: ReactNode;
  try {
    body = ready ? ready(text, CLASSES) : <p>{text}</p>;
  } catch {
    body = <p>{text}</p>;
  }
  return <div className={className ? `${styles.root} ${className}` : styles.root}>{body}</div>;
});

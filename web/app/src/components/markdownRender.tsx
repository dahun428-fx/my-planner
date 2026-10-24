import { compiler, type MarkdownToJSX, RuleType } from "markdown-to-jsx/react";
import { createElement, type ReactNode } from "react";
import type { MarkdownClasses } from "./Markdown";

export type RenderMarkdown = (text: string, classes: MarkdownClasses) => ReactNode;

function isWebLink(target: string | null): target is string {
  if (!target) return false;
  try {
    const { protocol } = new URL(target);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false; // relative, or not a URL at all
  }
}

/** Markdown to React elements; loaded on demand by Markdown.tsx. */
export const renderMarkdown: RenderMarkdown = (text, classes) => {
  const align = { left: classes.alignLeft, center: classes.alignCenter, right: classes.alignRight };
  const renderRule: MarkdownToJSX.Options["renderRule"] = (next, node, children, state) => {
    switch (node.type) {
      // A heading inside a bubble is bold body text, not a big title.
      case RuleType.heading:
        return (
          <p key={state.key} className={classes.heading}>
            <strong>{children(node.children, state)}</strong>
          </p>
        );
      // No images from the secretary's text: its alt words stand in.
      case RuleType.image:
        return node.alt || null;
      case RuleType.link:
        return isWebLink(node.target) ? (
          <a key={state.key} href={node.target} target="_blank" rel="noopener noreferrer" className={classes.link}>
            {children(node.children, state)}
          </a>
        ) : (
          <span key={state.key}>{children(node.children, state)}</span>
        );
      case RuleType.footnoteReference:
        return <sup key={state.key}>{node.text}</sup>;
      case RuleType.gfmTask:
        return <input key={state.key} type="checkbox" className={classes.task} checked={node.completed} disabled readOnly />;
      // Drawn here rather than by next(): its aligned cells would carry style="text-align:…",
      // which style-src 'self' blocks.
      case RuleType.table: {
        const cls = (i: number) => {
          const a = node.align[i];
          return a ? align[a] : undefined;
        };
        return (
          <div key={state.key} className={classes.tableWrap}>
            <table>
              <thead>
                <tr>
                  {node.header.map((cell, i) => (
                    <th key={i} className={cls(i)}>
                      {children(cell, state)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {node.cells.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, i) => (
                      <td key={i} className={cls(i)}>
                        {children(cell, state)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      // Raw HTML is off (disableParsingRawHTML), so these do not come; if one did, its source shows as text.
      case RuleType.htmlBlock:
      case RuleType.htmlSelfClosing:
        return node._rawOuter ?? node._rawOpen ?? null;
      case RuleType.htmlComment:
        return null;
      default:
        return next();
    }
  };
  return compiler(text, {
    // Every element the compiler makes goes through here, including the footnotes it adds outside
    // renderRule (<footer><div id=…>): the model's text never sets a DOM id or a style.
    createElement: (tag, props, ...kids) => {
      const { id: _id, style: _style, ...rest } = (props ?? {}) as Record<string, unknown>;
      if (tag === "footer") return createElement("div", { key: "footnotes", className: classes.footnotes }, ...kids);
      return createElement(tag, rest, ...kids);
    },
    disableParsingRawHTML: true,
    disableFrontmatter: true,
    forceBlock: true,
    wrapper: null,
    renderRule,
  });
};

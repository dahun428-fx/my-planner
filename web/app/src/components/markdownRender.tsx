import { compiler, type MarkdownToJSX, RuleType } from "markdown-to-jsx/react";
import type { ReactNode } from "react";
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
      case RuleType.table:
        return (
          <div key={state.key} className={classes.tableWrap}>
            {next()}
          </div>
        );
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
    disableParsingRawHTML: true,
    disableFrontmatter: true,
    forceBlock: true,
    wrapper: null,
    renderRule,
  });
};

import { copy } from "../../lib/copy";
import type { PartProps } from "../types";
import { DraftRows, monthText } from "./DraftRows";

// ui_chapter_draft: chapters waiting to be confirmed, one line each.
export function ChapterDraft({ props, data, ctx }: PartProps<{ chapter_ids: number[] }>) {
  const rows = data?.chapters?.map((c) => ({
    id: c.id,
    title: c.title,
    when: copy.parts.period(monthText(c.start_month), c.end_month ? monthText(c.end_month) : null),
  })) ?? null;
  return (
    <DraftRows
      heading={copy.parts.chapterHeading}
      fallback={copy.parts.chapterCount(props.chapter_ids.length)}
      rows={rows}
      confirmAction="confirm_chapters"
      dropAction="drop_chapter"
      ctx={ctx}
    />
  );
}

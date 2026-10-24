import type { PartProps } from "../types";
import { DraftRows, monthText } from "./DraftRows";
import { copy } from "../../lib/copy";

// ui_milestone_draft: life events waiting to be confirmed, one line each.
export function MilestoneDraft({ props, data, ctx }: PartProps<{ milestone_ids: number[] }>) {
  const rows = data?.milestones?.map((m) => ({ id: m.id, title: m.title, when: monthText(m.date) })) ?? null;
  return (
    <DraftRows
      heading={copy.parts.milestoneHeading}
      fallback={copy.parts.milestoneCount(props.milestone_ids.length)}
      rows={rows}
      confirmAction="confirm_milestones"
      dropAction="drop_milestone"
      ctx={ctx}
    />
  );
}

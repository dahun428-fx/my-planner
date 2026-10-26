import type { ResultItem } from "../ui/types";
import type { ViewPart } from "./parts";

type UiViewPart = Extract<ViewPart, { kind: "ui" }>;

/** The activities a message's drawn ui_result cards show: every id an item lists. */
function coveredIds(parts: ViewPart[], drawn: (p: UiViewPart) => boolean): Set<number> {
  const ids = new Set<number>();
  for (const p of parts) {
    if (p.kind !== "ui" || p.name !== "ui_result" || !Array.isArray(p.data?.items) || !drawn(p)) continue;
    for (const it of p.data.items as ResultItem[]) {
      if (Array.isArray(it.activity_ids)) for (const id of it.activity_ids) ids.add(id);
    }
  }
  return ids;
}

/**
 * SP6 11.4 as SP9 9.6 changed it: a change is one line ("✓ …") and its undo is the toast's, so the
 * line is left out when the message's ui_result cards show every activity it stands for (the same
 * change is not shown twice, G4). An item covers each activity it lists, with or without an
 * undo_id. One activity no item lists (two to-dos changed and one shown, only a ui_period_list)
 * keeps the line. So does a ui_result that will not draw (`drawn` false: no catalog yet, props it
 * refuses, an app that does not know the name): its UnknownPart shows nothing of the change. Only
 * for a message just received: a restored one is drawn as it is.
 */
export function hideCoveredActivity(parts: ViewPart[], drawn: (p: UiViewPart) => boolean): ViewPart[] {
  const covered = coveredIds(parts, drawn);
  if (covered.size === 0) return parts;
  return parts.filter((p) => p.kind !== "activity" || p.activityIds.length === 0 || !p.activityIds.every((id) => covered.has(id)));
}

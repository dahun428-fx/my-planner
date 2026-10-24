import type { ResultItem } from "../ui/types";
import type { ViewPart } from "./parts";

/** The activities a message's ui_result cards undo one by one: items with an undo_id and exactly that one activity. */
type UiViewPart = Extract<ViewPart, { kind: "ui" }>;

function coveredIds(parts: ViewPart[], drawn: (p: UiViewPart) => boolean): Set<number> {
  const ids = new Set<number>();
  for (const p of parts) {
    if (p.kind !== "ui" || p.name !== "ui_result" || !Array.isArray(p.data?.items) || !drawn(p)) continue;
    for (const it of p.data.items as ResultItem[]) {
      if (it.undo_id !== null && Array.isArray(it.activity_ids) && it.activity_ids.length === 1 && it.activity_ids[0] === it.undo_id) ids.add(it.undo_id);
    }
  }
  return ids;
}

/**
 * SP6 11.4: a message's grey confirmation box is left out when its ui_result cards show every
 * activity it stands for, each with its own "되돌리기" (the same change is not shown twice, G4).
 * One activity left uncovered (two to-dos changed and one shown, an item without undo_id, only a
 * ui_period_list) keeps the box: it is the one that undoes those. So does a ui_result that will
 * not draw (`drawn` false: no catalog yet, props it refuses, an app that does not know the name):
 * its UnknownPart has no undo. Only for a message just received: a restored one is drawn as it is.
 */
export function hideCoveredActivity(parts: ViewPart[], drawn: (p: UiViewPart) => boolean): ViewPart[] {
  const covered = coveredIds(parts, drawn);
  if (covered.size === 0) return parts;
  return parts.filter((p) => p.kind !== "activity" || p.activityIds.length === 0 || !p.activityIds.every((id) => covered.has(id)));
}

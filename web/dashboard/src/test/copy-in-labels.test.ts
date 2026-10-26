// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// "화면 문구는 한 곳" (B3): the screen code these files hold has no Korean of its own; every word comes from
// lib/labels.ts. Comments may stay Korean.
const FILES = [
  "components/ConnectionBand.tsx",
  "components/StateNotice.tsx",
  "components/OfflineCard.tsx",
  "components/Upcoming.tsx",
  "components/AreaRadar.tsx",
  "components/Reassurance.tsx",
  "pages/settings.tsx",
  "screens/CurveScreen.tsx",
  "screens/StatusScreen.tsx",
  "components/MomentsPanel.tsx",
  "screens/HistoryView.tsx",
  "components/HistoryChapter.tsx",
  "components/HistoryFilters.tsx",
];

const code = (rel: string) =>
  readFileSync(join(__dirname, "..", rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\s\/\/ .*$/gm, "");

describe("screen words", () => {
  it.each(FILES)("%s takes its words from labels.ts", (rel) => {
    const hangul = code(rel).match(/[가-힣]+/g) ?? [];
    expect(hangul).toEqual([]);
  });
});

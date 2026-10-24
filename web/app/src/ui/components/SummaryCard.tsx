import { Bullets } from "../primitives/Bullets";
import type { PartProps } from "../types";
import { Part } from "./Part";

const MAX_LINES = 8;

// ui_summary_card: a title and up to 8 lines in the `bullets` look (SP6 6.1). No buttons.
export function SummaryCard({ props }: PartProps<{ title: string; lines: string[] }>) {
  return (
    <Part title={props.title}>
      <Bullets items={props.lines.slice(0, MAX_LINES)} />
    </Part>
  );
}

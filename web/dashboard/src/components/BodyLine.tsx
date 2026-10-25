import type { StatusBody } from "../api/types.gen";
import { STATUS_TEXT as T } from "../lib/labels";

/** 몸 기록 under the health row (SP8 10.1): the last week's averages as a caption. No warning when the last record is old. */
export function BodyLine({ body }: { body: StatusBody | null }) {
  const line = body === null ? "" : T.bodyLine(body);
  if (line === "") return null;
  return <span className="stat-body meta">{line}</span>;
}

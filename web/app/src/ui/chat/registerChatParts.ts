import { Block } from "../block/Block";
import { registerParts } from "../registry";
import { DateChoice } from "./DateChoice";
import { PeriodList } from "./PeriodList";
import { Result } from "./Result";

/**
 * Written as a literal here (not imported) so it stays in the chat bundle after minifying:
 * scripts/size.mjs finds the chat sheet's chunk by it (SP6 11.7).
 */
export const CHAT_PARTS_MARKER = "sp6-chat-parts";

let registered = false;

/**
 * SP6 11.2: the four chat cards join the registry once, when the chat bundle loads (MessageView
 * calls this first thing). They are never pinned (2장), so the first screen's bundle has none.
 */
export function registerChatParts(): void {
  if (registered) return;
  registered = true;
  registerParts({ ui_date_choice: DateChoice, ui_result: Result, ui_period_list: PeriodList, ui_block: Block }, CHAT_PARTS_MARKER);
}

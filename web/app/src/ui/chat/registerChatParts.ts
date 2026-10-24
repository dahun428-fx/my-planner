import { UnknownPart } from "../components/UnknownPart";
import { registerParts } from "../registry";
import { DateChoice } from "./DateChoice";
import { Result } from "./Result";
import type { PartProps } from "../types";

/**
 * Written as a literal here (not imported) so it stays in the chat bundle after minifying:
 * scripts/size.mjs finds the chat sheet's chunk by it (SP6 11.7).
 */
export const CHAT_PARTS_MARKER = "sp6-chat-parts";

// Until each card lands, its name draws as an unknown part (the first-screen behaviour).
const Pending = ({ props }: PartProps<unknown>) => UnknownPart({ props });

let registered = false;

/** SP6 11.2: the four chat cards join the registry once, when the chat bundle loads. */
export function registerChatParts(): void {
  if (registered) return;
  registered = true;
  registerParts({ ui_date_choice: DateChoice, ui_result: Result, ui_period_list: Pending, ui_block: Pending }, CHAT_PARTS_MARKER);
}

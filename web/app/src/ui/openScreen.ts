import type { OpenScreen } from "./primitives/types";

// SP6 spec 8: the six screens a part may open. The app makes the address; props never carry one.
const HREF: Record<OpenScreen, string> = {
  today: "/",
  todos_day: "/todos/?tab=day",
  todos_week: "/todos/?tab=week",
  todos_month: "/todos/?tab=month",
  activity: "/activity/",
  settings: "/settings/",
};

export function screenHref(s: OpenScreen): string {
  return HREF[s];
}

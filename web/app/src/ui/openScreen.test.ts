import { describe, expect, it } from "vitest";
import { screenHref } from "./openScreen";

describe("screenHref", () => {
  it("maps the six screens of spec 8", () => {
    expect(screenHref("today")).toBe("/");
    expect(screenHref("todos_day")).toBe("/todos/?tab=day");
    expect(screenHref("todos_week")).toBe("/todos/?tab=week");
    expect(screenHref("todos_month")).toBe("/todos/?tab=month");
    expect(screenHref("activity")).toBe("/activity/");
    expect(screenHref("settings")).toBe("/settings/");
  });
});

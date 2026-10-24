import { describe, expect, it } from "vitest";
import { newClientMsgId } from "./ids";

describe("newClientMsgId", () => {
  it("is a fresh UUID v4", () => {
    const a = newClientMsgId();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newClientMsgId()).not.toBe(a);
  });
});

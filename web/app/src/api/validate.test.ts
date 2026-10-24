import { afterEach, describe, expect, it } from "vitest";
import health from "../test/fixtures/health.json";
import { validateModel } from "./validate";

const realFunction = globalThis.Function;
afterEach(() => {
  globalThis.Function = realFunction;
});

describe("validateModel", () => {
  it("accepts health fixture", () => {
    expect(validateModel("Health", health)).toBe(true);
  });

  it("rejects missing field", () => {
    const copy: Record<string, unknown> = structuredClone(health);
    delete copy.status;
    expect(validateModel("Health", copy)).toBe(false);
  });

  it("rejects unknown model shape", () => {
    expect(validateModel("SafeModeHealth", health)).toBe(false);
  });

  it("runs without eval", () => {
    const thrower = function () {
      throw new Error("Function constructor is blocked by CSP");
    } as unknown as FunctionConstructor;
    globalThis.Function = thrower;
    expect(validateModel("Health", structuredClone(health))).toBe(true);
    expect(validateModel("Week", { week: "2026-W43" })).toBe(false);
  });
});

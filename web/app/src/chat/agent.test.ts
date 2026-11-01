import { afterEach, describe, expect, it, vi } from "vitest";
import { loadAgent, saveAgent } from "./agent";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("agent", () => {
  it("is the secretary when nothing is kept", () => {
    expect(loadAgent()).toBe("secretary");
  });

  it("is the secretary when localStorage is missing or throws", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(loadAgent()).toBe("secretary");
    expect(() => saveAgent("mate")).not.toThrow();
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(loadAgent()).toBe("secretary");
    expect(() => saveAgent("mate")).not.toThrow();
  });

  it("keeps the pick", () => {
    saveAgent("mate");
    expect(loadAgent()).toBe("mate");
    saveAgent("secretary");
    expect(loadAgent()).toBe("secretary");
  });

  it("reads an unknown value as the secretary", () => {
    localStorage.setItem("chat.agent", "other");
    expect(loadAgent()).toBe("secretary");
  });
});

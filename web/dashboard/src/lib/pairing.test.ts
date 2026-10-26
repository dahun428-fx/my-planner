import { describe, expect, it } from "vitest";
import { SETTINGS_TEXT } from "./labels";
import { deviceName, readPairHash } from "./pairing";

describe("pairing", () => {
  it("names the device from its user agent (device pairing spec 6.2)", () => {
    expect(deviceName("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15")).toBe("iPhone");
    expect(deviceName("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15")).toBe("iPad");
    // iPadOS Safari asks for the desktop site: a Mac user agent with touch points
    expect(deviceName("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15", 5)).toBe("iPad");
    expect(deviceName("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15", 0)).toBe("Mac");
    expect(deviceName("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36")).toBe("Android");
    expect(deviceName("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")).toBe("Windows");
    expect(deviceName("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")).toBe("Linux");
    expect(deviceName("Lynx/2.9")).toBeNull();
    expect(SETTINGS_TEXT.deviceLabel("Windows")).toBe("Windows · 대시보드");
    expect(SETTINGS_TEXT.deviceLabel(null)).toBe("기기 · 대시보드");
  });

  it("reads #be=…&code=… (spec 3.3)", () => {
    expect(readPairHash("")).toBeNull();
    expect(readPairHash("#p-settings")).toBeNull();
    expect(readPairHash("#be=https%3A%2F%2Fdesk.example.ts.net&code=482913")).toEqual({ be: "https://desk.example.ts.net", code: "482913" });
    expect(readPairHash("#code=482913")).toEqual({ be: null, code: "482913" });
    // a code that is not six digits leaves the boxes empty
    expect(readPairHash("#be=https%3A%2F%2Fdesk.example.ts.net&code=48291")).toEqual({ be: "https://desk.example.ts.net", code: null });
    expect(readPairHash("#code=abcdef")).toEqual({ be: null, code: null });
  });
});

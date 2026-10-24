import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../../lib/copy";
import { Part } from "./Part";

// CheckRow's stylesheet reads data-read-only to draw the round mark (SP5 5.5.4).
describe("Part", () => {
  it("sets data-read-only when read-only and when restored", () => {
    const cases: [{ readOnly?: boolean; restored?: boolean }, boolean][] = [
      [{}, false],
      [{ readOnly: true }, true],
      [{ restored: true }, true],
    ];
    for (const [props, set] of cases) {
      const { container, unmount } = render(<Part {...props}>x</Part>);
      expect(container.querySelector("section")!.hasAttribute("data-read-only"), JSON.stringify(props)).toBe(set);
      // The offline reason is for read-only only, not for a restored card.
      expect(container.textContent?.includes(copy.offline.writeLater)).toBe(props.readOnly === true);
      unmount();
    }
  });
});

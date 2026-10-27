import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { markdownChunk } from "../components/Markdown";
import { server } from "./server";

// jsdom has no blob: addresses; photos (SP10 7.3) are shown through them. A counter stands in.
if (typeof URL.createObjectURL !== "function") {
  let n = 0;
  URL.createObjectURL = () => `blob:test/${++n}`;
  URL.revokeObjectURL = () => {};
}

// The Markdown parser is its own chunk; loaded up front here, so a test never sees the plain text
// swapped for the rendered one under its feet (Markdown.test.tsx covers the plain text before it).
beforeAll(async () => {
  server.listen({ onUnhandledRequest: "error" });
  await markdownChunk.load();
});
afterEach(() => {
  cleanup();
  if (typeof localStorage !== "undefined") localStorage.clear();
  server.resetHandlers();
});
afterAll(() => server.close());

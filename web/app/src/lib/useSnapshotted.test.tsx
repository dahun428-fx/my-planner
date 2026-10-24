import "fake-indexeddb/auto";
import { act, screen, waitFor } from "@testing-library/react";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import health from "../test/fixtures/health.json";
import todayJson from "../test/fixtures/today.json";
import { renderWithProviders, TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { saveConn } from "./connection";
import { loadSnap, useSnapshotted } from "./snapshot";
import type { Today } from "../api/types.gen";

const OTHER = "https://other.example.ts.net";

afterEach(() => clear());

function Probe() {
  const { view } = useSnapshotted<Today>("today", "/today", "Today");
  return <p data-testid="kind">{view.kind === "live" ? `live:${view.data.date}` : view.kind}</p>;
}

describe("useSnapshotted across connections", () => {
  it("does not save or show the previous BE's answer after the connection changes", async () => {
    server.use(http.get(`${BASE}/today`, () => HttpResponse.json(todayJson)));
    server.use(
      http.get(`${OTHER}/api/v1/health`, () => HttpResponse.json(health)),
      http.get(`${OTHER}/api/v1/today`, () => new Promise<Response>(() => {})), // never answers
    );
    renderWithProviders(<Probe />);
    await waitFor(() => expect(screen.getByTestId("kind")).toHaveTextContent("live:2026-10-24"));
    await waitFor(async () => expect(await loadSnap("today", TEST_BE_URL)).not.toBeNull());

    act(() => saveConn({ beUrl: OTHER, token: TEST_TOKEN }));
    await waitFor(() => expect(screen.getByTestId("kind")).toHaveTextContent("loading"));
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.getByTestId("kind")).toHaveTextContent("loading");
    expect(await loadSnap("today", OTHER)).toBeNull();
  });
});

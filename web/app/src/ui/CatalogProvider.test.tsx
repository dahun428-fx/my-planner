import "fake-indexeddb/auto";
import { act, screen, waitFor } from "@testing-library/react";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { saveConn } from "../lib/connection";
import catalogJson from "../test/fixtures/catalog.json";
import health from "../test/fixtures/health.json";
import { renderWithProviders, TEST_TOKEN } from "../test/render";
import { server } from "../test/server";
import { useCatalog } from "./CatalogProvider";

afterEach(async () => {
  await clear();
});

function Version() {
  const { catalog, settled } = useCatalog();
  return <p>{settled ? (catalog?.version ?? "no-catalog") : "waiting"}</p>;
}

describe("CatalogProvider", () => {
  it("drops the old BE's catalog when the address changes", async () => {
    const OTHER = "https://other.example.ts.net/api/v1";
    server.use(
      http.get(`${OTHER}/health`, () => HttpResponse.json(health)),
      http.get(`${OTHER}/ui/catalog`, () => HttpResponse.json({ error: { code: "internal", message: "x" } }, { status: 500 })),
    );
    renderWithProviders(<Version />);
    expect(await screen.findByText(catalogJson.version)).toBeInTheDocument();
    act(() => saveConn({ beUrl: "https://other.example.ts.net", token: TEST_TOKEN }));
    await waitFor(() => expect(screen.getByText("no-catalog")).toBeInTheDocument());
  });
});

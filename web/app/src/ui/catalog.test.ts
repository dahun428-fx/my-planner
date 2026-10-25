import "fake-indexeddb/auto";
import { clear, get, set } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { saveConn } from "../lib/connection";
import catalogJson from "../test/fixtures/catalog.json";
import { TEST_BE_URL, TEST_TOKEN } from "../test/render";
import { BASE, server } from "../test/server";
import { type Catalog, loadCatalog, makePropsCheck } from "./catalog";
import { registerChatParts } from "./chat/registerChatParts";
import { registryNames } from "./registry";

const catalog = catalogJson as Catalog;

afterEach(async () => {
  await clear();
});

function serve(answer: () => Response = () => HttpResponse.json(catalog)) {
  const hits = { n: 0 };
  server.use(
    http.get(`${BASE}/ui/catalog`, () => {
      hits.n += 1;
      return answer();
    }),
  );
  saveConn({ beUrl: TEST_BE_URL, token: TEST_TOKEN });
  return hits;
}

describe("catalog", () => {
  it("uses cached catalog when version matches", async () => {
    const hits = serve();
    await set("catalog", { ...catalog, beUrl: TEST_BE_URL });
    const got = await loadCatalog(catalog.version);
    expect(got?.version).toBe(catalogJson.version);
    expect(hits.n).toBe(0);
  });

  it("refetches when version changes", async () => {
    const hits = serve(() => HttpResponse.json({ ...catalog, version: "2026-10-25.1" }));
    await set("catalog", { ...catalog, beUrl: TEST_BE_URL });
    const got = await loadCatalog("2026-10-25.1");
    expect(got?.version).toBe("2026-10-25.1");
    expect(hits.n).toBe(1);
    expect(((await get("catalog")) as Catalog).version).toBe("2026-10-25.1");
  });

  it("fetches and stores when nothing is stored", async () => {
    const hits = serve();
    const got = await loadCatalog(catalog.version);
    expect(got?.components.ui_choice.origin).toBe("brain");
    expect(hits.n).toBe(1);
    expect(await get("catalog")).toBeTruthy();
  });

  it("offline uses stored", async () => {
    serve(() => HttpResponse.error());
    await set("catalog", { ...catalog, beUrl: TEST_BE_URL });
    const got = await loadCatalog("2026-10-25.1");
    expect(got?.version).toBe(catalogJson.version);
  });

  it("a catalog kept for another BE (or with no BE noted) is not used", async () => {
    serve(() => HttpResponse.error());
    await set("catalog", { ...catalog, beUrl: "https://old.example.ts.net" });
    expect(await loadCatalog(null)).toBeNull();
    await set("catalog", catalog);
    expect(await loadCatalog(null)).toBeNull();
  });

  it("stores the BE address with the catalog", async () => {
    serve();
    await loadCatalog(catalog.version);
    expect(((await get("catalog")) as { beUrl: string }).beUrl).toBe(TEST_BE_URL);
  });

  it("a catalog that arrives after a disconnect is not stored", async () => {
    serve(() => {
      localStorage.clear(); // "이 기기 연결 해제" while the answer was coming
      return HttpResponse.json(catalog);
    });
    await loadCatalog(catalog.version);
    expect(await get("catalog")).toBeUndefined();
  });

  it("offline with nothing stored gives null", async () => {
    serve(() => HttpResponse.error());
    expect(await loadCatalog(catalog.version)).toBeNull();
  });

  it("checks props against schema", () => {
    const check = makePropsCheck(catalog);
    const one = { question: "무엇부터 할까요?", options: [{ id: "a", label: "운동" }] };
    const two = { ...one, options: [...one.options, { id: "b", label: "독서" }] };
    expect(check("ui_choice", one)).toBe(false);
    expect(check("ui_choice", two)).toBe(true);
    expect(check("ui_nothing", two)).toBe(false);
    expect(check("ui_choice", null)).toBe(false);
  });

  it("a broken schema checks as false instead of throwing", () => {
    const broken: Catalog = {
      version: "x",
      components: { ui_bad: { origin: "brain", schema: { type: "object", properties: { a: { $ref: "#/$defs/missing" } } } } },
    };
    const check = makePropsCheck(broken);
    expect(() => check("ui_bad", { a: 1 })).not.toThrow();
    expect(check("ui_bad", { a: 1 })).toBe(false);
  });

  it("catalog names match registry", () => {
    // The chat bundle's four (SP6 11.2) and ui_events (SP9 9.8) join the first screen's eleven once the sheet has loaded.
    registerChatParts();
    expect(Object.keys(catalog.components).sort()).toEqual([...registryNames()].sort());
    expect(registryNames()).toHaveLength(16);
  });

  it("catalog version has the BE's form", () => {
    // The fixture is the BE's catalog() as is (10.5: YYYY-MM-DD.n); no test pins a version string.
    expect(catalog.version).toMatch(/^\d{4}-\d{2}-\d{2}\.\d+$/);
  });
});

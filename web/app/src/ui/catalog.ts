import { Validator, type Schema } from "@cfworker/json-schema";
import { get } from "idb-keyval";
import { apiGet } from "../api/client";
import { loadConn } from "../lib/connection";
import { setForBe } from "../lib/snapshot";
import type { UiCatalog } from "../api/types.gen";

// Spec 6: the BE's list of screen parts with a JSON Schema for each one's props. Kept on the device
// (IndexedDB `catalog`) and fetched again only when /health says the version changed.
export type Catalog = {
  version: string;
  components: Record<string, { origin: "brain" | "harness"; schema: object }>;
};

// The stored copy notes the BE it came from; a copy from another BE (or one without that note) is not used.
async function stored(beUrl: string | null): Promise<Catalog | null> {
  try {
    const v = (await get("catalog")) as (Catalog & { beUrl?: string }) | undefined;
    if (!v || typeof v.version !== "string" || !v.components || !beUrl || v.beUrl !== beUrl) return null;
    return { version: v.version, components: v.components };
  } catch {
    return null; // blocked IndexedDB is "nothing saved"
  }
}

export async function loadCatalog(currentVersion: string | null): Promise<Catalog | null> {
  const beUrl = loadConn()?.beUrl ?? null; // apiGet sends with the saved connection
  const saved = await stored(beUrl);
  if (saved && (currentVersion === null || saved.version === currentVersion)) return saved;
  const r = await apiGet<UiCatalog>("/ui/catalog", "UiCatalog");
  if (r.kind !== "ok") return saved; // offline or refused: the stored one still draws what it knows
  const fresh = r.data as Catalog;
  try {
    if (beUrl) await setForBe("catalog", { ...fresh, beUrl }, beUrl);
  } catch {
    // not saving is fine
  }
  return fresh;
}

// @cfworker/json-schema interprets the schema (no eval), so this runs under the strict CSP.
export function makePropsCheck(catalog: Catalog): (name: string, props: unknown) => boolean {
  const validators = new Map<string, Validator>();
  return (name, props) => {
    const entry = Object.hasOwn(catalog.components, name) ? catalog.components[name] : undefined;
    if (!entry) return false;
    try {
      let v = validators.get(name);
      if (!v) {
        v = new Validator(entry.schema as Schema, "2020-12", true);
        validators.set(name, v);
      }
      return v.validate(props).valid;
    } catch {
      return false; // a schema the checker cannot read means "cannot draw", never a crash while rendering
    }
  };
}

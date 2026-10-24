import { Validator, type Schema } from "@cfworker/json-schema";
import { get, set } from "idb-keyval";
import { apiGet } from "../api/client";
import type { UiCatalog } from "../api/types.gen";

// Spec 6: the BE's list of screen parts with a JSON Schema for each one's props. Kept on the device
// (IndexedDB `catalog`) and fetched again only when /health says the version changed.
export type Catalog = {
  version: string;
  components: Record<string, { origin: "brain" | "harness"; schema: object }>;
};

async function stored(): Promise<Catalog | null> {
  try {
    const v = (await get("catalog")) as Catalog | undefined;
    return v && typeof v.version === "string" && v.components ? v : null;
  } catch {
    return null; // blocked IndexedDB is "nothing saved"
  }
}

export async function loadCatalog(currentVersion: string | null): Promise<Catalog | null> {
  const saved = await stored();
  if (saved && (currentVersion === null || saved.version === currentVersion)) return saved;
  const r = await apiGet<UiCatalog>("/ui/catalog", "UiCatalog");
  if (r.kind !== "ok") return saved; // offline or refused: the stored one still draws what it knows
  const fresh = r.data as Catalog;
  try {
    await set("catalog", fresh);
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

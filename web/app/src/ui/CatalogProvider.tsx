import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { useConnection } from "../lib/ConnectionProvider";
import { type Catalog, loadCatalog, makePropsCheck } from "./catalog";

export interface CatalogValue {
  catalog: Catalog | null;
  /** The first load has finished (with or without a catalog); until then parts wait instead of showing "unknown". */
  settled: boolean;
  check(name: string, props: unknown): boolean;
}

const none = (): boolean => false;
const CatalogContext = createContext<CatalogValue>({ catalog: null, settled: true, check: none });

export function useCatalog(): CatalogValue {
  return useContext(CatalogContext);
}

// Loads the catalog once the connection is known and again when /health reports another version.
export function CatalogProvider({ children }: { children: ReactNode }) {
  const { state, conn } = useConnection();
  const beUrl = conn?.beUrl ?? null;
  const version = state?.kind === "online" ? state.health.version.ui_catalog : null;
  const ready = state !== null; // any known connection state: a catalog that cannot be had settles as null
  const [loaded, setLoaded] = useState<{ beUrl: string; catalog: Catalog | null } | null>(null);

  useEffect(() => {
    if (!beUrl || !ready) return;
    let alive = true;
    void loadCatalog(version).then((c) => {
      if (alive) setLoaded((prev) => (c || prev?.beUrl !== beUrl ? { beUrl, catalog: c } : prev)); // a failed reread keeps the one in hand
    });
    return () => {
      alive = false;
    };
  }, [beUrl, version, ready]);

  const mine = loaded && loaded.beUrl === beUrl ? loaded : null;
  const catalog = mine?.catalog ?? null;
  const check = useMemo(() => (catalog ? makePropsCheck(catalog) : none), [catalog]);
  const value = useMemo(() => ({ catalog, settled: mine !== null, check }), [catalog, mine, check]);
  return <CatalogContext.Provider value={value}>{children}</CatalogContext.Provider>;
}


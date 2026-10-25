// A full page load (not a client-side route change): every in-memory state of the old connection
// (chat sheet, catalog, polls, streams) is gone afterwards. Its own module so tests can stub it.
export function hardReplace(path: string): void {
  window.location.replace(path);
}

/**
 * Whether the build has the `/status/` page (SP8 app status screen). The more screen lists
 * "상태창" only then (spec 9.1); SP8-02 added the page and set this to true.
 */
export const HAS_STATUS_PAGE = true;

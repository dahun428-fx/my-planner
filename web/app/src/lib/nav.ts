// A full page load (not a client-side route change): every in-memory state of the old connection
// (chat sheet, catalog, polls, streams) is gone afterwards. Its own module so tests can stub it.
export function hardReplace(path: string): void {
  window.location.replace(path);
}

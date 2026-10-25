import type { AppProps } from "next/app";
import Head from "next/head";
import { useRouter } from "next/router";
import { Component as ReactComponent, type ComponentType, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatSheetProps } from "../chat/ChatSheet";
import { chatSheetChunk } from "../chat/loadChatSheet";
import { type ChatSheetApi, ChatSheetContext } from "../chat/sheetContext";
import { ToastProvider, useToast } from "../components/Toast";
import { ConnectionProvider, useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { reportBrowserError } from "../lib/errorReport";
import { ensurePushSubscription, registerServiceWorker } from "../lib/push";
import { pruneDeviceData } from "../lib/snapshot";
import { applyPalette, applyTheme, loadPalette, loadTheme } from "../lib/theme";
import { CatalogProvider } from "../ui/CatalogProvider";
// The design system (DESIGN.md): the generated copy of web/shared/global.css (`npm run sync:design`).
import "../styles/global.css";
// Every screen's styles go out with _app as one stylesheet. Otherwise Next's pages router carries a
// page's CSS as inline <style> tags when the app moves between tabs, which style-src 'self' blocks.
import "../screens/Activity";
import "../screens/Checkin";
import "../screens/Connect";
import "../screens/Habits";
import "../screens/More";
import "../screens/Settings";
import "../screens/Today";
import "../screens/Todos";
import "../components/LargeTitle";
import "../components/MoreButton";
import "../components/TabBar";
import "../styles/page.module.css";
// SP6 11.3: the parts' stylesheet goes out with _app too (the chat sheet's parts load late, their CSS does not).
import "../ui/primitives/primitives.module.css";
import "../ui/chat/cards.module.css";

// A crash inside the chat sheet takes down only the sheet, never the screen behind it.
class ChatBoundary extends ReactComponent<{ onError(error: unknown): void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    this.props.onError(error);
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

// One chat sheet for the whole app. Its chunk loads on the first open; if that fails (a stale
// deploy, a bad network) a toast says so and the next tap tries again. Once loaded it stays
// mounted, so a reply still coming survives a close and a change of tab, and the last view is
// there to read offline (F9).
function ChatHost({ children }: { children: ReactNode }) {
  const toast = useToast();
  const router = useRouter();
  const routerRef = useRef(router);
  routerRef.current = router;
  // Another BE address (re-entered on /connect/) gets a fresh sheet: the old conversation, its id
  // and any stream still coming must never reach the new BE.
  const beUrl = useConnection().conn?.beUrl ?? "";
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const [open, setOpen] = useState(false);
  const [Sheet, setSheet] = useState<ComponentType<ChatSheetProps> | null>(null);
  const [generation, setGeneration] = useState(0);
  const sheetRef = useRef<ComponentType<ChatSheetProps> | null>(null);
  const loading = useRef(false);
  const closed = useRef(new Set<() => void>());

  const fail = useCallback(() => {
    sheetRef.current = null;
    setSheet(null);
    setOpen(false);
    setGeneration((g) => g + 1); // a fresh boundary for the next try
    toastRef.current.show({ text: copy.chat.openFailed });
  }, []);

  const api = useMemo<ChatSheetApi>(
    () => ({
      open: () => {
        setOpen(true);
        if (sheetRef.current || loading.current) return;
        loading.current = true;
        chatSheetChunk
          .load()
          .then((m) => {
            sheetRef.current = m.ChatSheet;
            setSheet(() => m.ChatSheet);
          })
          .catch(fail)
          .finally(() => {
            loading.current = false;
          });
      },
      onClosed: (cb) => {
        closed.current.add(cb);
        return () => {
          closed.current.delete(cb);
        };
      },
    }),
    [fail],
  );
  const close = useCallback(() => {
    setOpen(false);
    closed.current.forEach((cb) => cb());
  }, []);
  return (
    <ChatSheetContext.Provider value={api}>
      {children}
      {Sheet && (
        <ChatBoundary
          key={`${generation}|${beUrl}`}
          onError={(error) => {
            reportBrowserError(error, routerRef.current.pathname);
            fail();
          }}
        >
          <Sheet open={open} onClose={close} />
        </ChatBoundary>
      )}
    </ChatSheetContext.Provider>
  );
}

// First effect (no inline script under the CSP): the saved theme and colour preset, then the
// service worker; a notification tap posts {navigate} to the app router. iOS may have dropped this
// device's push subscription since the last open: make it again (F7). Then the 7-day sweep of
// device data (4.7).
function useAppShell() {
  const router = useRouter();
  const routerRef = useRef(router);
  routerRef.current = router;
  useEffect(() => {
    applyTheme(loadTheme());
    // Like the theme, the palette comes in this effect: the first paint is ink, then the choice.
    applyPalette(loadPalette());
    void registerServiceWorker((url) => void routerRef.current.push(url)).then(() => ensurePushSubscription());
    void pruneDeviceData();
    // Uncaught errors and rejected promises go to the BE as name + place, never the message (spec 3.3).
    const onError = (e: ErrorEvent) => reportBrowserError(e.error, routerRef.current.pathname);
    const onRejection = (e: PromiseRejectionEvent) => reportBrowserError(e.reason, routerRef.current.pathname);
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
}

export default function App({ Component, pageProps }: AppProps) {
  useAppShell();
  return (
    <>
      <Head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </Head>
      <ConnectionProvider>
        <ToastProvider>
          <CatalogProvider>
            <ChatHost>
              <Component {...pageProps} />
            </ChatHost>
          </CatalogProvider>
        </ToastProvider>
      </ConnectionProvider>
    </>
  );
}

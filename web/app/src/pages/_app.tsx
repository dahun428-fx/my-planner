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
import { ensurePushSubscription, registerServiceWorker } from "../lib/push";
import { applyTheme, loadTheme } from "../lib/theme";
import { CatalogProvider } from "../ui/CatalogProvider";
import "../styles/tokens.css";
import "../styles/globals.css";

// A crash inside the chat sheet takes down only the sheet, never the screen behind it.
class ChatBoundary extends ReactComponent<{ onError(): void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
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
        <ChatBoundary key={`${generation}|${beUrl}`} onError={fail}>
          <Sheet open={open} onClose={close} />
        </ChatBoundary>
      )}
    </ChatSheetContext.Provider>
  );
}

// First effect (no inline script under the CSP): the saved theme, then the service worker; a
// notification tap posts {navigate} to the app router. iOS may have dropped this device's push
// subscription since the last open: make it again (F7).
function useAppShell() {
  const router = useRouter();
  const routerRef = useRef(router);
  routerRef.current = router;
  useEffect(() => {
    applyTheme(loadTheme());
    void registerServiceWorker((url) => void routerRef.current.push(url)).then(() => ensurePushSubscription());
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

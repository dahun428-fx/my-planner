import type { AppProps } from "next/app";
import Head from "next/head";
import { lazy, type ReactNode, Suspense, useCallback, useMemo, useRef, useState } from "react";
import { type ChatSheetApi, ChatSheetContext } from "../chat/sheetContext";
import { ToastProvider } from "../components/Toast";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import { CatalogProvider } from "../ui/CatalogProvider";
import "../styles/tokens.css";
import "../styles/globals.css";

// The AI SDK is loaded the first time the sheet opens, so it stays out of the first screen's
// bundle (spec 9: 180KB).
const ChatSheet = lazy(() => import("../chat/ChatSheet").then((m) => ({ default: m.ChatSheet })));

// One chat sheet for the whole app: once opened it stays mounted, so a reply still coming survives
// a close and a change of tab, and the last view is there to read offline (F9).
function ChatHost({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(false);
  const closed = useRef(new Set<() => void>());
  const api = useMemo<ChatSheetApi>(
    () => ({
      open: () => {
        setUsed(true);
        setOpen(true);
      },
      onClosed: (cb) => {
        closed.current.add(cb);
        return () => {
          closed.current.delete(cb);
        };
      },
    }),
    [],
  );
  const close = useCallback(() => {
    setOpen(false);
    closed.current.forEach((cb) => cb());
  }, []);
  return (
    <ChatSheetContext.Provider value={api}>
      {children}
      {used && (
        <Suspense fallback={null}>
          <ChatSheet open={open} onClose={close} />
        </Suspense>
      )}
    </ChatSheetContext.Provider>
  );
}

export default function App({ Component, pageProps }: AppProps) {
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

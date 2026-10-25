import type { AppProps } from "next/app";
import Head from "next/head";
import { useRouter } from "next/router";
import { type ReactNode, useEffect } from "react";
import { ConnectionBand } from "../components/ConnectionBand";
import { Nav } from "../components/Nav";
import { ConnectionProvider, useConnection } from "../lib/ConnectionProvider";
import "../styles/global.css";
import "../styles/tokens.css";
import "../styles/globals.css";

const isSettings = (path: string) => path.replace(/[?#].*$/, "").replace(/\/+$/, "") === "/settings";

// No connection yet: every screen sends the browser to the settings screen (spec 13.1).
export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { ready, conn } = useConnection();
  const away = ready && !conn && !isSettings(router.asPath);
  useEffect(() => {
    if (away) void router.replace("/settings/");
  }, [away, router]);
  return (
    <>
      <header className="top">
        <Nav />
        <ConnectionBand />
      </header>
      <main className="main">{away ? null : children}</main>
    </>
  );
}

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <title>my-planner 대시보드</title>
      </Head>
      <ConnectionProvider>
        <Shell>
          <Component {...pageProps} />
        </Shell>
      </ConnectionProvider>
    </>
  );
}

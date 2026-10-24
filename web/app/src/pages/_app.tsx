import type { AppProps } from "next/app";
import Head from "next/head";
import { ToastProvider } from "../components/Toast";
import { ConnectionProvider } from "../lib/ConnectionProvider";
import "../styles/tokens.css";
import "../styles/globals.css";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </Head>
      <ConnectionProvider>
        <ToastProvider>
          <Component {...pageProps} />
        </ToastProvider>
      </ConnectionProvider>
    </>
  );
}

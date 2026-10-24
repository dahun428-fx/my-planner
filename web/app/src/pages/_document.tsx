import { Head, Html, Main, NextScript } from "next/document";

const connectSrc = process.env.NEXT_PUBLIC_CONNECT_SRC ?? "";

const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; " +
  `connect-src 'self' ${connectSrc}; base-uri 'none'; form-action 'none'; ` +
  "worker-src 'self'; manifest-src 'self'";

export default function Document() {
  return (
    <Html lang="ko">
      <Head>
        <meta httpEquiv="Content-Security-Policy" content={CSP} />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="theme-color" media="(prefers-color-scheme: light)" content="#f6f3ec" />
        <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#12110f" />
        <link rel="manifest" href="/manifest.webmanifest" />
        <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}

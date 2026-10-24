import { Head, Html, Main, NextScript } from "next/document";

// Spec 14 / gap 3: the CSP is the first element of this <Head>, before any <script> or stylesheet. (Next
// itself writes charset, viewport and title from next/head ahead of it; check-csp checks the order.) connect-src takes the
// build constant (the tailnet wildcard); the BE URL itself is a per-device value kept in localStorage.
const connectSrc = process.env.NEXT_PUBLIC_CONNECT_SRC ?? "";

export const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; " +
  `connect-src 'self' ${connectSrc}; base-uri 'none'; form-action 'none'`;

export default function Document() {
  return (
    <Html lang="ko">
      <Head>
        <meta httpEquiv="Content-Security-Policy" content={CSP} />
        <meta name="referrer" content="no-referrer" />
        <meta name="color-scheme" content="light dark" />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}

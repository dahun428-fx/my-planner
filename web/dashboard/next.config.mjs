import { PHASE_PRODUCTION_BUILD } from "next/constants.js";

// Static export only (spec 13.1): Pages Router, no API routes, no server rendering of data.
// NEXT_PUBLIC_CONNECT_SRC is the CSP connect-src list (tailnet wildcard, not a secret, spec 14).
/** @param {string} phase */
export default function config(phase) {
  if (phase === PHASE_PRODUCTION_BUILD) {
    const src = process.env.NEXT_PUBLIC_CONNECT_SRC;
    if (!src || !src.trim()) {
      throw new Error("NEXT_PUBLIC_CONNECT_SRC is required for build (CSP connect-src)");
    }
    // Only tailnet wildcards, the same range normalizeBeUrl accepts (no `https:` or `*` opening every host).
    // An optional `:port` is for the staging BE behind `tailscale serve --https=8443` (release flow spec 5.1).
    const ok = src.trim().split(/\s+/).every((e) => /^https:\/\/\*(\.[a-z0-9-]+)+\.ts\.net(:\d{1,5})?$/i.test(e));
    if (!ok) {
      throw new Error("NEXT_PUBLIC_CONNECT_SRC must be space separated https://*.<tailnet>.ts.net[:port] sources");
    }
  }
  /** @type {import('next').NextConfig} */
  const nextConfig = {
    output: "export",
    trailingSlash: true,
    images: { unoptimized: true },
    reactStrictMode: true,
    poweredByHeader: false,
  };
  return nextConfig;
}

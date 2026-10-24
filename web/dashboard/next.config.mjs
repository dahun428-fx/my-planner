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
    if (/[;'"<>]/.test(src)) {
      throw new Error("NEXT_PUBLIC_CONNECT_SRC must be a plain source list");
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

import { PHASE_PRODUCTION_BUILD } from "next/constants.js";

// NEXT_PUBLIC_DEFAULT_BE_URL and NEXT_PUBLIC_DASHBOARD_URL are optional (device pairing spec 5.2, 6.1;
// declared in src/env.d.ts). Not checked here: a default address normalizeBeUrl refuses leaves the
// connect screen's field empty, it never stops the build.
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
    env: {
      NEXT_PUBLIC_APP_VERSION: (process.env.VERCEL_GIT_COMMIT_SHA ?? "dev").slice(0, 7),
      // inlined at build time so the probe button is dropped from normal builds
      NEXT_PUBLIC_MEDIC_PROBE: process.env.NEXT_PUBLIC_MEDIC_PROBE ?? "",
    },
  };
  return nextConfig;
}

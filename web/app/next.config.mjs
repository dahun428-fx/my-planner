import { PHASE_PRODUCTION_BUILD } from "next/constants.js";

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
  };
  return nextConfig;
}

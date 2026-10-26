/// <reference types="next" />
/// <reference types="next/image-types/global" />

// Build constants (static export, readable by anyone: never a secret, spec 14).
declare namespace NodeJS {
  interface ProcessEnv {
    /** Required: the CSP connect-src list and the range normalizeBeUrl accepts (`https://*.<tailnet>.ts.net`). */
    readonly NEXT_PUBLIC_CONNECT_SRC?: string;
    /** Optional: fills the settings screen's BE address (device pairing spec 6.1). Ignored unless normalizeBeUrl takes it. */
    readonly NEXT_PUBLIC_DEFAULT_BE_URL?: string;
  }
}

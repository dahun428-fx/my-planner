/// <reference types="next" />
/// <reference types="next/image-types/global" />

// Build constants (static export, readable by anyone: never a secret, SP3-4 spec 14).
declare namespace NodeJS {
  interface ProcessEnv {
    /** Required: the CSP connect-src list and the range normalizeBeUrl accepts (`https://*.<tailnet>.ts.net`). */
    readonly NEXT_PUBLIC_CONNECT_SRC?: string;
    /** Optional: fills the connect screen's BE address (device pairing spec 6.1). Ignored unless normalizeBeUrl takes it. */
    readonly NEXT_PUBLIC_DEFAULT_BE_URL?: string;
    /** Optional: the dashboard's address on the new device sheet (spec 5.2). Unset hides its row and QR switch. */
    readonly NEXT_PUBLIC_DASHBOARD_URL?: string;
  }
}

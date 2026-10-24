import { config } from "zod/v4/core";

// The AI SDK builds its zod schemas when its module loads. zod decides then whether to compile
// object checks, probing `Function("")`, which the CSP (script-src 'self', no 'unsafe-eval')
// reports as a violation even though zod catches it. Import this module before "ai" and
// "@ai-sdk/react" so the switch is set before any schema exists (A10 csp.spec found the probe).
config({ jitless: true });

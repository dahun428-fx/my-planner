import { defineConfig } from "vitest/config";

export default defineConfig({
  // tsconfig keeps "jsx": "preserve" for Next; tests compile JSX with the automatic runtime.
  oxc: { jsx: { runtime: "automatic" } },
  test: {
    environment: "jsdom",
    // next build inlines this from `trailingSlash: true`; next/link reads it at run time in tests.
    env: { __NEXT_TRAILING_SLASH: "true", NEXT_PUBLIC_CONNECT_SRC: "https://*.example.ts.net" },
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs", "public/**/*.test.ts"],
    css: { modules: { classNameStrategy: "non-scoped" } },
  },
});

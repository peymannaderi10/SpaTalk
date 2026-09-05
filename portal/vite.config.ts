import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import { wasp } from "wasp/client/vite";

export default defineConfig({
  plugins: [wasp(), tailwindcss()],
  server: {
    open: true,
    // The dev server is shown to others through Cloudflare quick tunnels whose hostnames change
    // on every restart, so the host check cannot be a fixed list. Development only; production
    // is a built app behind its own domain.
    allowedHosts: true,
  },
  test: {
    // Wasp merges these with its own entries. Two kinds of test file are not
    // client tests: the Playwright specs under `e2e-tests/`, which need
    // Playwright's runner, and `*.server.test.ts`, which is server code and
    // may import `wasp/server` (see `vitest.server.config.ts`).
    exclude: ["e2e-tests/**", "src/**/*.server.test.ts"],
  },
});

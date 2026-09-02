import { defineConfig } from "vitest/config";

/**
 * The runner for server-side unit tests.
 *
 * `wasp test client` drives Vitest through Wasp's client plugin, which refuses
 * every import from `wasp/server` — correctly, for client code. The access
 * rules are server code and throw Wasp's `HttpError`, so their tests need a
 * runner without that plugin: plain Vitest, Node environment, and only the
 * files named `*.server.test.ts`.
 *
 * Run with `npm run test:unit`. Client-side tests stay on `wasp test client`.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.server.test.ts"],
  },
});

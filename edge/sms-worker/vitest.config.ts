import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.toml" },
      miniflare: {
        bindings: {
          RUNTIME_URL: "https://runtime.test",
          EDGE_SHARED_KEY: "edge-key-for-tests",
          TELNYX_API_KEY: "telnyx-key-for-tests",
          // Every signature test overrides this with a freshly generated key pair.
          TELNYX_PUBLIC_KEY: "",
        },
      },
    }),
  ],
});

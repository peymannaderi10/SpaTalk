import * as z from "zod";

/**
 * The runtime is the only place tenant, conversation, item and usage data
 * lives. The portal reaches it over HTTP with a shared key; Task C4 generates
 * the typed client that uses these two values.
 */
export const runtimeEnvSchema = z.object({
  RUNTIME_INTERNAL_URL: z.string({
    error: "RUNTIME_INTERNAL_URL is required",
  }),
  RUNTIME_INTERNAL_KEY: z.string({
    error: "RUNTIME_INTERNAL_KEY is required",
  }),
});

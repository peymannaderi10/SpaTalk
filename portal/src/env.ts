import { defineEnvValidationSchema } from "wasp/env";

import * as z from "zod";
import { authEnvSchema } from "./auth/env";
import { stripeEnvSchema } from "./payment/stripe/env";
import { runtimeEnvSchema } from "./runtime/env";

// Wasp merges this schema with its built-in env var validations and uses it
// to validate `process.env` at server startup. Access the validated env vars
// with `import { env } from 'wasp/server'` instead of using `process.env` directly.
// https://wasp.sh/docs/project/env-vars#custom-env-var-validations
export const serverEnvValidationSchema = defineEnvValidationSchema(
  z.object({
    ...authEnvSchema.shape,
    ...stripeEnvSchema.shape,
    ...runtimeEnvSchema.shape,
  }),
);

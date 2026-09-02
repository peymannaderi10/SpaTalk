import { env } from "wasp/server";
import type { ServerSetupFn } from "wasp/server/types";
import { installLogScrubbing, registerSecret } from "./security";

/**
 * What happens once, when the portal's server starts (portal plan, Task C7).
 *
 * Two things: every secret this process holds is registered and the console is
 * wrapped so none of them can be printed by anything — our code, Wasp's, or a
 * library dumping an error object — and express is told which peers may be
 * believed when they say who a request came from, so the rate limit counts real
 * addresses behind Caddy without letting a stranger choose their own bucket.
 */

/**
 * Read once, here, at start. The only other place in the portal that reads a
 * secret out of the environment is `src/runtime/api.ts`, which caches the
 * shared key on first use and never hands it to anything but the runtime.
 *
 * `SMTP_PASSWORD` is not part of Wasp's validated `env` — Wasp's email sender
 * reads it itself — so it comes from `process.env`.
 */
function secretsHeldByThisProcess(): Array<string | undefined> {
  return [
    env.RUNTIME_INTERNAL_KEY,
    env.STRIPE_API_KEY,
    env.STRIPE_WEBHOOK_SECRET,
    env.JWT_SECRET,
    env.DATABASE_URL,
    process.env.SMTP_PASSWORD,
  ];
}

export const serverSetup: ServerSetupFn = async ({ app }) => {
  for (const secret of secretsHeldByThisProcess()) {
    registerSecret(secret);
  }
  installLogScrubbing();

  // Behind Caddy the peer is a container on a private network, so its
  // forwarded-for header is worth believing; a request straight off the
  // internet is not, and cannot pick its own rate-limit bucket.
  app.set("trust proxy", ["loopback", "linklocal", "uniquelocal"]);
};

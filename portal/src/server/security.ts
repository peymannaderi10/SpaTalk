import type { NextFunction, Request, RequestHandler, Response } from "express";
import type { MiddlewareConfigFn } from "wasp/server/middleware";

/**
 * The portal's hardening (portal plan, Task C7).
 *
 * Three things live here, and nothing in this module imports Wasp, Prisma or
 * the environment, so all three are ordinary functions a unit test can drive:
 *
 * 1. the headers every response carries, which say the app may not be framed
 *    and may only load its own code and Stripe's;
 * 2. a rate limit on the endpoints a stranger can reach without an account —
 *    logging in, signing up, resetting a password and accepting an invitation;
 * 3. redaction, so that a secret the server holds can never reach a log line.
 *
 * `src/server/setup.ts` is what reads the real secrets and installs (3) at
 * server start; `portalMiddleware` below is what `main.wasp.ts` hands Wasp for
 * (1) and (2).
 */

// ---------------------------------------------------------------------------
// Security headers
// ---------------------------------------------------------------------------

/** Where Stripe's checkout script comes from. */
export const STRIPE_SCRIPT_ORIGIN = "https://js.stripe.com";
/** Where Stripe's script talks to, and where its frames come from. */
export const STRIPE_API_ORIGIN = "https://api.stripe.com";
export const STRIPE_FRAME_ORIGINS = [
  "https://js.stripe.com",
  "https://hooks.stripe.com",
];
/** Stripe's telemetry pixel; named so the policy needs no wildcard. */
export const STRIPE_IMAGE_ORIGIN = "https://q.stripe.com";

export type ContentSecurityPolicyOptions = {
  /**
   * Extra origins the browser may open connections to. The client host adds
   * the Wasp server's origin here, because in production the two are different
   * names (`app.<domain>` and `app-api.<domain>`, portal plan Task C9).
   */
  connectOrigins?: readonly string[];
};

/**
 * The content security policy: this origin and Stripe, and nothing else.
 *
 * No wildcard appears anywhere in it on purpose — a single `*` is how a policy
 * quietly stops being one.
 */
export function contentSecurityPolicy(
  options: ContentSecurityPolicyOptions = {},
): string {
  const connect = ["'self'", ...(options.connectOrigins ?? []), STRIPE_API_ORIGIN];

  return [
    "default-src 'self'",
    "base-uri 'none'",
    "object-src 'none'",
    // Clickjacking: this app is never a frame, anywhere.
    "frame-ancestors 'none'",
    "form-action 'self'",
    `script-src 'self' ${STRIPE_SCRIPT_ORIGIN}`,
    // Tailwind and the component library inject style attributes at runtime;
    // scripts are not given the same latitude.
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: ${STRIPE_IMAGE_ORIGIN}`,
    "font-src 'self' data:",
    `connect-src ${connect.join(" ")}`,
    `frame-src ${STRIPE_FRAME_ORIGINS.join(" ")}`,
    "worker-src 'self' blob:",
    "upgrade-insecure-requests",
  ].join("; ");
}

/**
 * The headers the Wasp server sends on every response.
 *
 * The client host has to send the same table for the documents it serves; it
 * is written down once, here, so the two cannot drift.
 */
export const SECURITY_HEADERS: Readonly<Record<string, string>> = Object.freeze({
  "Content-Security-Policy": contentSecurityPolicy(),
  // A year, subdomains included: the portal is only ever served over https.
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-site",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
  "X-DNS-Prefetch-Control": "off",
});

export function securityHeaders(
  headers: Readonly<Record<string, string>> = SECURITY_HEADERS,
): RequestHandler {
  return (_request: Request, response: Response, next: NextFunction) => {
    for (const [name, value] of Object.entries(headers)) {
      response.setHeader(name, value);
    }
    // Express announces itself by default; nothing is gained by telling a
    // stranger what to look up an exploit for.
    response.removeHeader("X-Powered-By");
    next();
  };
}

// ---------------------------------------------------------------------------
// Rate limits
// ---------------------------------------------------------------------------

/** Ten attempts a minute per address per endpoint (portal plan, Task C7). */
export const RATE_LIMIT_MAX_REQUESTS = 10;
export const RATE_LIMIT_WINDOW_MS = 60_000;

/**
 * The endpoints a stranger can reach without an account: a password to guess,
 * an address to enumerate, or a token to brute force. Everything else is behind
 * a session, and Stripe's webhook is deliberately absent — throttling it would
 * turn Stripe's retries into failures.
 *
 * `ALWAYS_COUNTED_PATHS` below says which of these spend their budget on every
 * request rather than only on the ones that were refused.
 */
export const RATE_LIMITED_PATHS: readonly string[] = Object.freeze([
  "/auth/email/login",
  "/auth/email/signup",
  "/auth/email/request-password-reset",
  "/auth/email/reset-password",
  "/auth/email/verify-email",
  "/operations/invite-member",
  "/operations/get-invitation",
  "/operations/accept-invitation",
]);

/**
 * The endpoints where every request counts, whatever it answers.
 *
 * Everywhere else the budget is spent by attempts that were *refused*: what a
 * limit on a login exists to stop is guessing, and a person who typed their own
 * password correctly has proved they are not guessing. Counting successes there
 * would lock a clinic's whole front desk out of the portal on a busy morning —
 * five staff behind one office address share one bucket — and would not slow an
 * attacker down by a single guess.
 *
 * These two are different: a password-reset request is answered the same way
 * whoever asks (so a success proves nothing, and each one sends an email), and
 * an invitation is an email an owner can send to anybody.
 */
export const ALWAYS_COUNTED_PATHS: readonly string[] = Object.freeze([
  "/auth/email/request-password-reset",
  "/operations/invite-member",
]);

export function isRateLimitedPath(
  path: string,
  paths: readonly string[] = RATE_LIMITED_PATHS,
): boolean {
  return paths.includes(normalisePath(path));
}

/** Whether an answered request keeps its place in the window even if it worked. */
export function countsWhenItSucceeds(
  path: string,
  paths: readonly string[] = ALWAYS_COUNTED_PATHS,
): boolean {
  return paths.includes(normalisePath(path));
}

/**
 * The path the limiter counts against.
 *
 * Express strips the mount point from `req.path` inside a router, so a login
 * arrives at the global middleware as `/email/login`. `originalUrl` is the only
 * thing that still says which endpoint was asked for.
 */
export function requestPath(request: Pick<Request, "originalUrl" | "url">): string {
  const raw = request.originalUrl || request.url || "";
  return normalisePath(raw.split("?")[0]);
}

function normalisePath(path: string): string {
  const trimmed = path.split("?")[0];
  if (trimmed.length > 1 && trimmed.endsWith("/")) {
    return trimmed.slice(0, -1);
  }
  return trimmed;
}

/**
 * Who is asking. `req.ip` honours express's `trust proxy` setting, which
 * `src/server/setup.ts` limits to private peers, so a stranger on the internet
 * cannot pick their own bucket by forging a forwarded-for header.
 */
export function clientIpOf(
  request: Pick<Request, "ip"> & { socket?: { remoteAddress?: string } },
): string {
  const address = request.ip ?? request.socket?.remoteAddress ?? "";
  // Node reports an IPv4 peer on a dual-stack socket as ::ffff:1.2.3.4.
  return address.replace(/^::ffff:/, "") || "unknown";
}

export type RateLimiterOptions = {
  limit?: number;
  windowMs?: number;
  paths?: readonly string[];
  alwaysCountedPaths?: readonly string[];
  now?: () => number;
};

export type RateLimiter = RequestHandler & { reset(): void };

/**
 * A fixed window counter, in this process's memory.
 *
 * The portal is one server process; a shared store would be a second piece of
 * infrastructure to run and watch for a limit whose whole job is to make
 * guessing slow.
 */
export function createRateLimiter(options: RateLimiterOptions = {}): RateLimiter {
  const limit = options.limit ?? RATE_LIMIT_MAX_REQUESTS;
  const windowMs = options.windowMs ?? RATE_LIMIT_WINDOW_MS;
  const paths = options.paths ?? RATE_LIMITED_PATHS;
  const alwaysCounted = options.alwaysCountedPaths ?? ALWAYS_COUNTED_PATHS;
  const now = options.now ?? Date.now;

  const windows = new Map<string, { count: number; resetAt: number }>();

  function prune(at: number): void {
    for (const [key, window] of windows) {
      if (window.resetAt <= at) {
        windows.delete(key);
      }
    }
  }

  const middleware = ((
    request: Request,
    response: Response,
    next: NextFunction,
  ) => {
    const path = requestPath(request);
    if (!isRateLimitedPath(path, paths)) {
      next();
      return;
    }

    const at = now();
    // Both halves of the key matter: one address exhausting its logins must not
    // close the invitation page, and one address must not close anyone else's.
    const key = `${clientIpOf(request)}|${path}`;
    let window = windows.get(key);
    if (!window || window.resetAt <= at) {
      window = { count: 0, resetAt: at + windowMs };
      windows.set(key, window);
      if (windows.size > 1024) {
        prune(at);
      }
    }

    window.count += 1;
    const remaining = Math.max(0, limit - window.count);
    response.setHeader("X-RateLimit-Limit", String(limit));
    response.setHeader("X-RateLimit-Remaining", String(remaining));

    if (window.count > limit) {
      const retryAfter = Math.max(1, Math.ceil((window.resetAt - at) / 1000));
      response.setHeader("Retry-After", String(retryAfter));
      response.status(429).json({
        message:
          "Too many attempts from this connection. Please wait a minute and try again.",
        data: null,
      });
      return;
    }

    // The attempt is counted first and given back only once it is answered, so
    // a burst of guesses cannot slip through while the answers are pending.
    if (!countsWhenItSucceeds(path, alwaysCounted) && typeof response.on === "function") {
      const counted = window;
      response.on("finish", () => {
        if (response.statusCode < 400 && counted.count > 0) {
          counted.count -= 1;
        }
      });
    }

    next();
  }) as RateLimiter;

  middleware.reset = () => windows.clear();
  return middleware;
}

// ---------------------------------------------------------------------------
// Secrets never reach a log line
// ---------------------------------------------------------------------------

export const REDACTED = "[redacted]";

/**
 * Below this, a "secret" is a substring of ordinary words and numbers, and
 * redacting it would blank out half of every log line instead of protecting
 * anything.
 */
export const SECRET_MIN_LENGTH = 8;

const registered = new Set<string>();

/** Remembers a value that must never be printed. Short values are ignored. */
export function registerSecret(secret: string | null | undefined): void {
  if (typeof secret === "string" && secret.length >= SECRET_MIN_LENGTH) {
    registered.add(secret);
  }
}

export function registeredSecrets(): string[] {
  return [...registered];
}

/** Only for tests: forgets every registered secret. */
export function __resetRegisteredSecrets(): void {
  registered.clear();
}

export function scrubSecrets(
  text: string,
  secrets: Iterable<string> = registered,
): string {
  let scrubbed = text;
  for (const secret of secrets) {
    if (typeof secret !== "string" || secret.length < SECRET_MIN_LENGTH) {
      continue;
    }
    scrubbed = scrubbed.split(secret).join(REDACTED);
  }
  return scrubbed;
}

function usableSecrets(secrets: Iterable<string>): string[] {
  return [...secrets].filter(
    (secret) => typeof secret === "string" && secret.length >= SECRET_MIN_LENGTH,
  );
}

function safeJson(value: unknown): string {
  const seen = new WeakSet<object>();
  try {
    return JSON.stringify(value, (_key, entry: unknown) => {
      if (typeof entry === "object" && entry !== null) {
        if (seen.has(entry)) {
          return "[circular]";
        }
        seen.add(entry);
      }
      return entry;
    }) ?? "";
  } catch {
    return "";
  }
}

/**
 * Everything a logged value could reveal, as one string — used only to decide
 * whether the value holds a secret.
 */
function renderForScan(value: unknown): string {
  try {
    if (value instanceof Error) {
      return `${value.stack ?? value.message} ${safeJson({ ...value })}`;
    }
    if (typeof value === "object" && value !== null) {
      return safeJson(value);
    }
    return String(value);
  } catch {
    return "";
  }
}

function holdsSecret(text: string, secrets: readonly string[]): boolean {
  return secrets.some((secret) => text.includes(secret));
}

/**
 * One argument on its way to the console. A value that holds no secret is
 * passed through exactly as it was, so ordinary logging keeps its formatting;
 * only a value that would have printed a secret is replaced by its redacted
 * text.
 */
export function scrubLogArgument(
  value: unknown,
  secrets: readonly string[],
): unknown {
  if (secrets.length === 0) {
    return value;
  }
  if (typeof value === "string") {
    return holdsSecret(value, secrets) ? scrubSecrets(value, secrets) : value;
  }
  const rendered = renderForScan(value);
  if (!holdsSecret(rendered, secrets)) {
    return value;
  }
  return scrubSecrets(rendered, secrets);
}

type ConsoleLike = Pick<Console, "log" | "info" | "warn" | "error" | "debug">;

const SCRUBBED_METHODS = ["log", "info", "warn", "error", "debug"] as const;

export type LogScrubbingOptions = {
  console?: ConsoleLike;
  secrets?: Iterable<string>;
};

/**
 * Wraps the console so that no registered secret can be printed, whatever
 * library or handler does the printing. Returns the undo.
 */
export function installLogScrubbing(
  options: LogScrubbingOptions = {},
): () => void {
  const target = (options.console ?? globalThis.console) as ConsoleLike;
  const secrets = usableSecrets(options.secrets ?? registered);
  const originals = new Map<string, (...args: unknown[]) => void>();

  for (const method of SCRUBBED_METHODS) {
    const original = target[method] as (...args: unknown[]) => void;
    originals.set(method, original);
    (target as unknown as Record<string, unknown>)[method] = (
      ...args: unknown[]
    ) => {
      original.apply(target, args.map((arg) => scrubLogArgument(arg, secrets)));
    };
  }

  return () => {
    for (const [method, original] of originals) {
      (target as unknown as Record<string, unknown>)[method] = original;
    }
  };
}

// ---------------------------------------------------------------------------
// What Wasp is handed
// ---------------------------------------------------------------------------

/**
 * The portal's global middleware: Wasp's own entries, with helmet replaced by
 * the header table above and the rate limiter added in front of everything.
 *
 * Wasp applies this to `/auth` and `/operations`, and every custom api starts
 * from it too, so both the headers and the limit reach every route the server
 * answers.
 */
/** The entry the rate limiter is placed after, so a refusal is still logged. */
export const ACCESS_LOG_MIDDLEWARE = "logger";

export const portalMiddleware: MiddlewareConfigFn = (middlewareConfig) => {
  const rest = new Map(middlewareConfig);
  // helmet's defaults allow same-origin framing and describe a policy that
  // knows nothing about Stripe; the table above replaces it outright.
  rest.delete("helmet");

  const limiter = createRateLimiter();
  const ordered = new Map(middlewareConfig);
  ordered.clear();

  // First, so that every answer carries the headers — the refusals included.
  ordered.set("securityHeaders", securityHeaders());

  for (const [name, handler] of rest) {
    ordered.set(name, handler);
    // Straight after the access log: a refused attempt has to appear in it,
    // or a brute-force attempt is invisible to whoever reads the logs.
    if (name === ACCESS_LOG_MIDDLEWARE) {
      ordered.set("rateLimit", limiter);
    }
  }
  if (!ordered.has("rateLimit")) {
    ordered.set("rateLimit", limiter);
  }

  return ordered;
};

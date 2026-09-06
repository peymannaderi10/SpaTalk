import { Readable } from "stream";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { Request, RequestHandler, Response } from "express";
import {
  ACCESS_LOG_MIDDLEWARE,
  contentSecurityPolicy,
  countsWhenItSucceeds,
  createRateLimiter,
  installLogScrubbing,
  isRateLimitedPath,
  portalMiddleware,
  RATE_LIMIT_MAX_REQUESTS,
  RATE_LIMIT_WINDOW_MS,
  REDACTED,
  scrubSecrets,
  SECURITY_HEADERS,
  securityHeaders,
} from "./security";

/**
 * The portal's own hardening: what a browser is told it may do, how many times
 * a stranger may guess a password or an invitation token, and the promise that
 * a secret never reaches a log line.
 *
 * All three are plain express middleware and plain functions, so this runs
 * without a server, a database or a network.
 */

// --- the smallest express request and response these middlewares need -------

type FakeResponse = {
  statusCode: number;
  headers: Record<string, string>;
  body: unknown;
  setHeader(name: string, value: string): void;
  removeHeader(name: string): void;
  getHeader(name: string): string | undefined;
  status(code: number): FakeResponse;
  json(body: unknown): FakeResponse;
  on(event: string, listener: () => void): FakeResponse;
  /** Express emits this when the answer has been written. */
  finish(statusCode: number): void;
};

function response(): FakeResponse {
  const listeners: Array<() => void> = [];
  const res: FakeResponse = {
    statusCode: 200,
    headers: {},
    body: undefined,
    setHeader(name, value) {
      res.headers[name.toLowerCase()] = value;
    },
    removeHeader(name) {
      delete res.headers[name.toLowerCase()];
    },
    getHeader(name) {
      return res.headers[name.toLowerCase()];
    },
    status(code) {
      res.statusCode = code;
      return res;
    },
    json(body) {
      res.body = body;
      return res;
    },
    on(event, listener) {
      if (event === "finish") {
        listeners.push(listener);
      }
      return res;
    },
    finish(statusCode) {
      res.statusCode = statusCode;
      for (const listener of listeners) {
        listener();
      }
    },
  };
  return res;
}

type FakeRequest = {
  originalUrl: string;
  url: string;
  baseUrl: string;
  path: string;
  method: string;
  ip: string;
  socket: { remoteAddress: string };
  headers: Record<string, string>;
};

function request({
  path = "/auth/email/login",
  ip = "10.0.0.1",
}: { path?: string; ip?: string } = {}): FakeRequest {
  return {
    originalUrl: path,
    url: path,
    baseUrl: "",
    path,
    method: "POST",
    ip,
    socket: { remoteAddress: ip },
    headers: {},
  };
}

/** Runs a middleware and says whether the request was allowed through. */
function run(
  middleware: unknown,
  req: FakeRequest,
): { passed: boolean; res: FakeResponse } {
  const res = response();
  let passed = false;
  (middleware as (a: unknown, b: unknown, c: () => void) => void)(
    req,
    res,
    () => {
      passed = true;
    },
  );
  return { passed, res };
}

// --- security headers ------------------------------------------------------

describe("the security headers on every server response", () => {
  test("the content security policy allows this origin and Stripe and nothing else", () => {
    const { res } = run(securityHeaders(), request());
    const policy = res.getHeader("content-security-policy") ?? "";

    expect(policy).toContain("default-src 'self'");
    expect(policy).toContain("script-src 'self' https://js.stripe.com");
    expect(policy).toContain("https://api.stripe.com");
    expect(policy).not.toContain("'unsafe-eval'");
    expect(policy).not.toContain("*");
  });

  test("the page may not be framed by anyone", () => {
    const { res } = run(securityHeaders(), request());

    expect(res.getHeader("content-security-policy")).toContain(
      "frame-ancestors 'none'",
    );
    expect(res.getHeader("x-frame-options")).toBe("DENY");
  });

  test("browsers are told to stay on https for a year, subdomains included", () => {
    const { res } = run(securityHeaders(), request());
    const hsts = res.getHeader("strict-transport-security") ?? "";

    expect(hsts).toContain("max-age=31536000");
    expect(hsts).toContain("includeSubDomains");
  });

  test("the response does not sniff types, leak referrers or name the server", () => {
    const res = response();
    res.setHeader("X-Powered-By", "Express");
    (
      securityHeaders() as unknown as (
        a: unknown,
        b: unknown,
        c: () => void,
      ) => void
    )(request(), res, () => {});

    expect(res.getHeader("x-content-type-options")).toBe("nosniff");
    expect(res.getHeader("referrer-policy")).toBe("no-referrer");
    expect(res.getHeader("x-powered-by")).toBeUndefined();
  });

  test("the request is passed on", () => {
    const { passed } = run(securityHeaders(), request());
    expect(passed).toBe(true);
  });

  test("the api origin a browser may reach can be added for the client host", () => {
    const policy = contentSecurityPolicy({
      connectOrigins: ["https://app-api.example.com"],
    });

    expect(policy).toContain("connect-src 'self' https://app-api.example.com");
    expect(policy).toContain("frame-ancestors 'none'");
    // The table shipped for the server itself never widens on its own.
    expect(SECURITY_HEADERS["Content-Security-Policy"]).not.toContain(
      "app-api.example.com",
    );
  });
});

// --- rate limits -----------------------------------------------------------

describe("the rate limit on login, signup and invitation", () => {
  test("login, signup, password reset and the three invitation calls are limited", () => {
    for (const path of [
      "/auth/email/login",
      "/auth/email/signup",
      "/auth/email/request-password-reset",
      "/auth/email/reset-password",
      "/auth/email/verify-email",
      "/operations/invite-member",
      "/operations/get-invitation",
      "/operations/accept-invitation",
    ]) {
      expect(isRateLimitedPath(path), path).toBe(true);
    }
  });

  test("Stripe's webhook and the ordinary pages are not limited", () => {
    for (const path of [
      "/payments-webhook",
      "/operations/get-tenant-conversations",
      "/operations/read-conversation",
      "/operations/create-tenant-from-bundle",
      "/auth/me",
    ]) {
      expect(isRateLimitedPath(path), path).toBe(false);
    }
  });

  test("ten attempts a minute are allowed and the eleventh is refused", () => {
    const limiter = createRateLimiter();

    for (let attempt = 1; attempt <= RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      expect(run(limiter, request()).passed, `attempt ${attempt}`).toBe(true);
    }

    const eleventh = run(limiter, request());
    expect(eleventh.passed).toBe(false);
    expect(eleventh.res.statusCode).toBe(429);
  });

  test("the refusal is a sentence with no stack and says how long to wait", () => {
    const limiter = createRateLimiter();
    for (let attempt = 0; attempt <= RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      run(limiter, request());
    }

    const { res } = run(limiter, request());
    const body = res.body as { message?: string };

    expect(typeof body.message).toBe("string");
    expect(body.message).not.toMatch(/\bat\s+\S+\s+\(/); // no stack frames
    expect(JSON.stringify(body)).not.toContain("Error:");
    expect(Number(res.getHeader("retry-after"))).toBeGreaterThan(0);
  });

  test("one address running out does not lock another one out", () => {
    const limiter = createRateLimiter();
    for (let attempt = 0; attempt <= RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      run(limiter, request({ ip: "10.0.0.1" }));
    }

    expect(run(limiter, request({ ip: "10.0.0.1" })).passed).toBe(false);
    expect(run(limiter, request({ ip: "10.0.0.2" })).passed).toBe(true);
  });

  test("running out of login attempts does not close the invitation page", () => {
    const limiter = createRateLimiter();
    for (let attempt = 0; attempt <= RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      run(limiter, request({ path: "/auth/email/login" }));
    }

    expect(run(limiter, request({ path: "/auth/email/login" })).passed).toBe(
      false,
    );
    expect(
      run(limiter, request({ path: "/operations/accept-invitation" })).passed,
    ).toBe(true);
  });

  test("an address is forgiven once the minute is over", () => {
    let now = 1_000_000;
    const limiter = createRateLimiter({ now: () => now });

    for (let attempt = 0; attempt <= RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      run(limiter, request());
    }
    expect(run(limiter, request()).passed).toBe(false);

    now += RATE_LIMIT_WINDOW_MS + 1;
    expect(run(limiter, request()).passed).toBe(true);
  });

  function runAndFinish(
    limiter: ReturnType<typeof createRateLimiter>,
    req: FakeRequest,
    answeredWith: number,
  ): boolean {
    const { passed, res } = run(limiter, req);
    res.finish(answeredWith);
    return passed;
  }

  test("a password typed correctly is not held against the person", () => {
    const limiter = createRateLimiter();

    // A clinic's staff share one office address; twenty good logins in a
    // minute must not lock the front desk out of its own portal.
    for (let attempt = 1; attempt <= 20; attempt += 1) {
      expect(
        runAndFinish(limiter, request({ path: "/auth/email/login" }), 200),
        `attempt ${attempt}`,
      ).toBe(true);
    }
  });

  test("a refused password attempt is counted", () => {
    const limiter = createRateLimiter();

    for (let attempt = 0; attempt < RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      expect(
        runAndFinish(limiter, request({ path: "/auth/email/login" }), 401),
      ).toBe(true);
    }

    expect(
      runAndFinish(limiter, request({ path: "/auth/email/login" }), 401),
    ).toBe(false);
  });

  test("a good login does not buy back a guess that was refused", () => {
    const limiter = createRateLimiter();

    for (let attempt = 0; attempt < RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      runAndFinish(limiter, request({ path: "/auth/email/login" }), 401);
      runAndFinish(limiter, request({ path: "/auth/email/login" }), 200);
    }

    expect(
      runAndFinish(limiter, request({ path: "/auth/email/login" }), 401),
    ).toBe(false);
  });

  test("sending a password-reset email counts even though it always succeeds", () => {
    const path = "/auth/email/request-password-reset";
    expect(countsWhenItSucceeds(path)).toBe(true);
    expect(countsWhenItSucceeds("/auth/email/login")).toBe(false);

    const limiter = createRateLimiter();
    for (let attempt = 0; attempt < RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      expect(runAndFinish(limiter, request({ path }), 200)).toBe(true);
    }

    expect(runAndFinish(limiter, request({ path }), 200)).toBe(false);
  });

  test("inviting people counts even when the owner is allowed to", () => {
    const path = "/operations/invite-member";
    const limiter = createRateLimiter();

    for (let attempt = 0; attempt < RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      expect(runAndFinish(limiter, request({ path }), 200)).toBe(true);
    }

    expect(runAndFinish(limiter, request({ path }), 200)).toBe(false);
  });

  test("a burst of guesses cannot slip through while the answers are pending", () => {
    const limiter = createRateLimiter();

    // Nothing has been answered yet, so nothing has been given back.
    for (let attempt = 0; attempt < RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      expect(run(limiter, request({ path: "/auth/email/login" })).passed).toBe(
        true,
      );
    }
    expect(run(limiter, request({ path: "/auth/email/login" })).passed).toBe(
      false,
    );
  });

  test("a path that is not limited is never counted", () => {
    const limiter = createRateLimiter();
    for (let attempt = 0; attempt < 100; attempt += 1) {
      expect(run(limiter, request({ path: "/payments-webhook" })).passed).toBe(
        true,
      );
    }
  });

  test("the limited path is read from the whole url, not the router's remainder", () => {
    const limiter = createRateLimiter();
    // Express strips the mount point: inside `router.use('/auth', ...)` the
    // request's own `path` is `/email/login` and `originalUrl` is the truth.
    const mounted: FakeRequest = {
      ...request(),
      baseUrl: "/auth",
      path: "/email/login",
      url: "/email/login",
      originalUrl: "/auth/email/login?redirect=/app",
    };

    for (let attempt = 0; attempt <= RATE_LIMIT_MAX_REQUESTS; attempt += 1) {
      run(limiter, mounted);
    }
    expect(run(limiter, mounted).passed).toBe(false);
  });
});

// --- what Wasp is handed ---------------------------------------------------

describe("the middleware the portal hands Wasp", () => {
  function waspDefaults(): Map<string, RequestHandler> {
    const noop: RequestHandler = (_req, _res, next) => next();
    return new Map<string, RequestHandler>([
      ["helmet", noop],
      ["cors", noop],
      ["logger", noop],
      ["express.json", noop],
      ["express.urlencoded", noop],
      ["cookieParser", noop],
    ]);
  }

  test("helmet is replaced by the portal's own header table", () => {
    const names = [...portalMiddleware(waspDefaults()).keys()];

    expect(names).not.toContain("helmet");
    expect(names).toContain("securityHeaders");
  });

  test("the headers are set first, so even a refusal carries them", () => {
    const names = [...portalMiddleware(waspDefaults()).keys()];

    expect(names[0]).toBe("securityHeaders");
  });

  test("a refused attempt still reaches the access log", () => {
    const names = [...portalMiddleware(waspDefaults()).keys()];

    expect(names.indexOf("rateLimit")).toBe(
      names.indexOf(ACCESS_LOG_MIDDLEWARE) + 1,
    );
  });

  test("the JSON body parser takes a body the size of a logo upload", async () => {
    // A 200 KB logo arrives as a ~273 KB base64 string inside the operation's
    // JSON, well over Express's default 100 KB, so the portal supplies its
    // own parser with a limit the Branding page fits under.
    const handler = portalMiddleware(waspDefaults()).get("express.json");
    if (!handler) throw new Error("no express.json entry");

    const logoDataUrl = `data:image/png;base64,${"A".repeat(280_000)}`;
    const body = JSON.stringify({ slug: "skincentrix", logoDataUrl });
    const request = Object.assign(Readable.from([Buffer.from(body)]), {
      headers: {
        "content-type": "application/json",
        "content-length": String(Buffer.byteLength(body)),
      },
      method: "POST",
      url: "/operations/update-organization-branding",
    }) as unknown as Request;
    const next = vi.fn();

    await new Promise<void>((resolve) => {
      handler(request, {} as Response, (error?: unknown) => {
        next(error);
        resolve();
      });
    });

    expect(next).toHaveBeenCalledTimes(1);
    expect(next.mock.calls[0][0]).toBeUndefined();
    expect(
      (request as unknown as { body: { logoDataUrl: string } }).body
        .logoDataUrl,
    ).toBe(logoDataUrl);
  });

  test("Wasp's own middleware is all still there", () => {
    const names = [...portalMiddleware(waspDefaults()).keys()];

    for (const kept of [
      "cors",
      "logger",
      "express.json",
      "express.urlencoded",
      "cookieParser",
    ]) {
      expect(names, kept).toContain(kept);
    }
  });
});

// --- secrets never reach the logs ------------------------------------------

describe("scrubbing secrets out of everything the server logs", () => {
  const KEY = "runtime-internal-key-abcdef123456";
  const restores: Array<() => void> = [];

  afterEach(() => {
    while (restores.length > 0) {
      restores.pop()?.();
    }
    vi.restoreAllMocks();
  });

  type Sink = {
    log: (...args: unknown[]) => void;
    info: (...args: unknown[]) => void;
    warn: (...args: unknown[]) => void;
    error: (...args: unknown[]) => void;
    debug: (...args: unknown[]) => void;
  };

  function captureConsole(secrets: string[]): { sink: Sink; lines: string[] } {
    const lines: string[] = [];
    const push = (...args: unknown[]) => {
      lines.push(args.map((arg) => String(arg)).join(" "));
    };
    const sink: Sink = {
      log: push,
      info: push,
      warn: push,
      error: push,
      debug: push,
    };
    restores.push(installLogScrubbing({ console: sink, secrets }));
    return { sink, lines };
  }

  test("a secret written straight into a line is replaced", () => {
    expect(scrubSecrets(`key=${KEY} refused`, [KEY])).toBe(
      `key=${REDACTED} refused`,
    );
  });

  test("a secret carried inside a serialised object is replaced", () => {
    const scrubbed = scrubSecrets(
      JSON.stringify({ headers: { "X-Internal-Key": KEY } }),
      [KEY],
    );

    expect(scrubbed).not.toContain(KEY);
    expect(scrubbed).toContain(REDACTED);
  });

  test("a line that holds no secret is left exactly as it was", () => {
    expect(scrubSecrets("nothing to hide here", [KEY])).toBe(
      "nothing to hide here",
    );
  });

  test("a value too short to be a secret is never treated as one", () => {
    // Redacting "3" would blank out half of every log line.
    expect(scrubSecrets("port 3001, attempt 3", ["3", ""])).toBe(
      "port 3001, attempt 3",
    );
  });

  test("the installed console redacts a secret in a string argument", () => {
    const { sink, lines } = captureConsole([KEY]);

    sink.error(`calling the runtime with ${KEY}`);

    expect(lines.join("\n")).not.toContain(KEY);
    expect(lines.join("\n")).toContain(REDACTED);
  });

  test("the installed console redacts a secret hidden in an object", () => {
    const { sink, lines } = captureConsole([KEY]);

    sink.error("runtime refused", { request: { headers: { key: KEY } } });

    expect(lines.join("\n")).not.toContain(KEY);
  });

  test("the installed console redacts a secret carried by an error", () => {
    const { sink, lines } = captureConsole([KEY]);

    sink.error(new Error(`GET /internal/tenants failed for key ${KEY}`));

    expect(lines.join("\n")).not.toContain(KEY);
  });

  test("an ordinary line is passed through untouched", () => {
    const { sink, lines } = captureConsole([KEY]);

    sink.info("Server listening on port 3001");

    expect(lines).toEqual(["Server listening on port 3001"]);
  });

  test("a circular object does not break logging", () => {
    const { sink, lines } = captureConsole([KEY]);
    const looped: Record<string, unknown> = { name: "context" };
    looped.self = looped;

    sink.warn("context", looped);

    expect(lines).toHaveLength(1);
  });

  test("uninstalling puts the console back", () => {
    const sink: Sink = {
      log: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    };
    const original = sink.error;
    const restore = installLogScrubbing({ console: sink, secrets: [KEY] });

    expect(sink.error).not.toBe(original);
    restore();
    expect(sink.error).toBe(original);
  });
});

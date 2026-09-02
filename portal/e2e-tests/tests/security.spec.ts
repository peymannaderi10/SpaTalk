import { expect, test } from "@playwright/test";
import { readFile } from "fs/promises";
import { RUNTIME_KEY } from "./runtime";
import {
  agencyAdmin,
  callOperation,
  MAIL_SINK_PATH,
  SERVER_URL,
  signInOrSignUp,
} from "./utils";

/**
 * What a browser is told, and what a stranger is allowed to try.
 *
 * These assertions are against the Wasp *server*, which is the origin the
 * portal's own code is served from in production only for the API; the client
 * host (Caddy, portal plan Task C9) has to send the same table for the
 * documents it serves, and `SECURITY_HEADERS` in `src/server/security.ts` is
 * where that table is written down.
 */

const SERVER_PATHS = ["/", "/auth/me"];

test.describe("the security headers", () => {
  for (const path of SERVER_PATHS) {
    test(`${path} refuses to be framed by anyone`, async ({ request }) => {
      const response = await request.get(`${SERVER_URL}${path}`);
      const headers = response.headers();

      expect(headers["content-security-policy"]).toContain(
        "frame-ancestors 'none'",
      );
      expect(headers["x-frame-options"]).toBe("DENY");
    });
  }

  test("the content security policy allows this origin and Stripe and nothing else", async ({
    request,
  }) => {
    const response = await request.get(`${SERVER_URL}/`);
    const policy = response.headers()["content-security-policy"] ?? "";

    expect(policy).toContain("default-src 'self'");
    expect(policy).toContain("https://js.stripe.com");
    expect(policy).not.toContain("'unsafe-eval'");
    expect(policy).not.toContain("*");
  });

  test("browsers are told to stay on https and not to sniff types", async ({
    request,
  }) => {
    const headers = (await request.get(`${SERVER_URL}/`)).headers();

    expect(headers["strict-transport-security"]).toContain("max-age=31536000");
    expect(headers["strict-transport-security"]).toContain("includeSubDomains");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("no-referrer");
  });

  test("the server does not name itself", async ({ request }) => {
    const headers = (await request.get(`${SERVER_URL}/`)).headers();

    expect(headers["x-powered-by"]).toBeUndefined();
  });

  test("a signed-out operation call still carries the headers", async ({
    request,
  }) => {
    const response = await request.post(
      `${SERVER_URL}/operations/list-my-organizations`,
      { data: { json: {} }, failOnStatusCode: false },
    );

    expect(response.status()).toBe(401);
    expect(response.headers()["content-security-policy"]).toContain(
      "frame-ancestors 'none'",
    );
  });
});

test.describe("the rate limit", () => {
  /**
   * Proving the limiter is wired into the running app, not only that it works
   * in a unit test. Guessing a password-reset token is the attempt used here
   * because no other spec touches that endpoint: the limit is per address *and*
   * per endpoint, so spending this one leaves login, signup and the invitation
   * calls with their full budget for the rest of the run.
   */
  test("an eleventh guess at a password-reset token in a minute is refused", async ({
    request,
  }) => {
    const attempt = () =>
      request.post(`${SERVER_URL}/auth/email/reset-password`, {
        data: { token: `guess-${Date.now()}`, password: "password123" },
        failOnStatusCode: false,
      });

    const statuses: number[] = [];
    for (let i = 0; i < 11; i += 1) {
      statuses.push((await attempt()).status());
    }

    expect(statuses.slice(0, 10).every((status) => status === 400)).toBe(true);
    expect(statuses[10]).toBe(429);

    const refused = await attempt();
    expect(refused.status()).toBe(429);
    expect(Number(refused.headers()["retry-after"])).toBeGreaterThan(0);
    const body = await refused.json();
    expect(typeof body.message).toBe("string");
    expect(JSON.stringify(body)).not.toContain("Error:");
  });

  test("logging in is not affected by that", async ({ request }) => {
    const response = await request.post(`${SERVER_URL}/auth/email/login`, {
      data: { email: "nobody@spatalk.test", password: "wrong-password" },
      failOnStatusCode: false,
    });

    expect(response.status()).not.toBe(429);
  });
});

test.describe("the shared key", () => {
  /**
   * The server's whole output for this run is in the mail sink — the suite
   * pipes `wasp start` into it — so this is the plan's log-scrub check against
   * a real failing call, not a stubbed one: an organisation is pointed at a
   * tenant the runtime has never heard of, the agency tenants table is asked
   * for, and the failure is looked for in the log without the key beside it.
   */
  test("never appears in the server's log, not even when a runtime call fails", async ({
    page,
  }) => {
    await signInOrSignUp({ page, user: agencyAdmin });

    // A fixed slug, so re-runs reuse the same organisation instead of leaving a
    // new one behind every time.
    const slug = "runtime-unknown-security-e2e";
    const created = await callOperation(
      page,
      "/operations/create-organization",
      {
        name: "A clinic the runtime does not know",
        slug,
        runtimeTenantId: slug,
      },
    );
    expect([200, 409]).toContain(created.status);

    const tenants = await callOperation(page, "/operations/get-agency-tenants");
    expect(tenants.status).toBe(200);
    const row = tenants.body.find(
      (entry: { slug: string }) => entry.slug === slug,
    );
    expect(row.problem).toBeTruthy();

    const log = await readFile(MAIL_SINK_PATH, "utf8");
    expect(log).toContain("The front desk service failed on");
    expect(log).not.toContain(RUNTIME_KEY);
    expect(log).not.toContain("X-Internal-Key:");
  });
});

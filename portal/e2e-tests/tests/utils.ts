import { expect, type Page } from "@playwright/test";
import { randomUUID } from "crypto";
import { readFile } from "fs/promises";
import { join } from "path";

export type User = {
  email: string;
  password: string;
};

const DEFAULT_PASSWORD = "password123";

/**
 * The agency admin the suite signs in as. `playwright.config.ts` pins
 * `ADMIN_EMAILS` to this address for the dev server it starts, so a user who
 * signs up with it becomes an agency admin (`User.isAdmin`).
 */
export const AGENCY_ADMIN_EMAIL = "admin@spatalk.test";

export const agencyAdmin: User = {
  email: AGENCY_ADMIN_EMAIL,
  password: DEFAULT_PASSWORD,
};

/**
 * The dev server runs with Wasp's Dummy email provider, which prints every
 * message it would have sent. `playwright.config.ts` pipes that output into
 * this file, so it is the test suite's mail sink.
 */
export const MAIL_SINK_PATH = join(__dirname, "..", "mail-sink.log");

export function createRandomUser(): User {
  return {
    email: `${randomUUID()}@spatalk.test`,
    password: DEFAULT_PASSWORD,
  };
}

export async function signUserUp({
  page,
  user,
}: {
  page: Page;
  user: User;
}): Promise<void> {
  await page.goto("/signup", { waitUntil: "domcontentloaded" });

  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);

  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes("/auth/email/signup") &&
        response.status() === 200,
    ),
    page.click('button:has-text("Sign up")'),
  ]);
}

/**
 * Reads the verification link the Dummy provider printed for this address.
 * The mail sink is written by a separate process, so this polls.
 */
export async function readVerificationLink(
  email: string,
  timeoutMs = 30_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastSeen = "";

  while (Date.now() < deadline) {
    let contents = "";
    try {
      contents = await readFile(MAIL_SINK_PATH, "utf8");
    } catch {
      contents = "";
    }
    lastSeen = contents;

    const link = findVerificationLink(contents, email);
    if (link) {
      return link;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  throw new Error(
    `No verification email for ${email} appeared in ${MAIL_SINK_PATH} within ${timeoutMs}ms. ` +
      `Sink held ${lastSeen.length} characters.`,
  );
}

function findVerificationLink(
  mailSink: string,
  email: string,
): string | undefined {
  // The Dummy provider prints the recipient and the body of each email. Take
  // the last verification link that appears after this address, so a re-run
  // for the same address picks up the newest token.
  const addressAt = mailSink.lastIndexOf(email);
  if (addressAt === -1) {
    return undefined;
  }

  const after = mailSink.slice(addressAt);
  const matches = after.match(/https?:\/\/\S*email-verification\?token=[^\s"'<]+/g);
  return matches?.[matches.length - 1];
}

export async function verifyUserEmail({
  page,
  user,
}: {
  page: Page;
  user: User;
}): Promise<void> {
  const link = await readVerificationLink(user.email);
  await page.goto(link, { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/verified/i)).toBeVisible();
}

export async function logUserIn({
  page,
  user,
}: {
  page: Page;
  user: User;
}): Promise<void> {
  await page.goto("/login", { waitUntil: "domcontentloaded" });

  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);

  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes("/auth/email/login") &&
        response.status() === 200,
    ),
    page.click('button:has-text("Log in")'),
  ]);
}

/**
 * Where signing in ends up.
 *
 * `/app` is a resolver, not a page (`portal/src/client/entry.ts`): an agency
 * admin goes on to `/admin`, a person who belongs to one organisation into it,
 * and only a person who belongs to none stays put. A helper that has just
 * signed somebody in does not know which of those they are, so it waits for
 * any of the three rather than for `/app` alone.
 */
const AFTER_SIGN_IN = /\/(app|admin)(\/|$)/;

/**
 * An account the suite may have created on an earlier run: the database
 * outlives a run, so a fixed address (the agency admin) is signed in if it
 * exists and created if it does not.
 */
export async function signInOrSignUp({
  page,
  user,
}: {
  page: Page;
  user: User;
}): Promise<void> {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);

  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/auth/email/login")),
    page.click('button:has-text("Log in")'),
  ]);

  if (response.status() === 200) {
    await page.waitForURL(AFTER_SIGN_IN);
    return;
  }

  await signUserUp({ page, user });
  await verifyUserEmail({ page, user });
  await logUserIn({ page, user });
  await page.waitForURL(AFTER_SIGN_IN);
}

export const SERVER_URL = process.env.WASP_SERVER_URL ?? "http://localhost:3001";

export type OperationResult = {
  status: number;
  body: any;
};

/**
 * Calls a Wasp server operation with the signed-in session, so a test can
 * assert what the server does, not only what the UI shows.
 *
 * Wasp puts operation arguments and results through superjson, so the wire
 * body is `{ json, meta }` in both directions (see
 * `.wasp/out/server/src/middleware/operations.js`). The envelope is added and
 * removed here so a test writes plain arguments.
 */
export async function callOperation(
  page: Page,
  path: string,
  args: unknown = {},
): Promise<OperationResult> {
  return page.evaluate(
    async ({ url, payload }: { url: string; payload: unknown }) => {
      // Wasp stores the session id JSON-encoded under a prefixed key.
      const stored = localStorage.getItem("wasp:sessionId");
      const sessionId = stored ? (JSON.parse(stored) as string) : null;
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(sessionId ? { Authorization: `Bearer ${sessionId}` } : {}),
        },
        body: JSON.stringify({ json: payload }),
      });
      const text = await response.text();
      let body: any = text;
      try {
        const parsed = JSON.parse(text);
        body = parsed && "json" in parsed ? parsed.json : parsed;
      } catch {
        // A non-JSON body (an error page) is returned as the raw text.
      }
      return { status: response.status, body };
    },
    { url: `${SERVER_URL}${path}`, payload: args },
  );
}

/**
 * The HTTP status of a server operation called with the signed-in session.
 */
export async function serverRequestStatus(
  page: Page,
  path: string,
  args: unknown = {},
): Promise<number> {
  const { status } = await callOperation(page, path, args);
  return status;
}

/**
 * The organisation that holds a runtime tenant, created if there is none.
 *
 * `runtimeTenantId` is unique on `Organization`, so a second spec that wants
 * its own organisation for the seeded `skincentrix` tenant is refused with
 * 409 and must use the one an earlier spec (or an earlier run) created. The
 * agency admin sees every organisation in `list-my-organizations`, so the
 * lookup works whoever created it. Returns the organisation's id and slug;
 * callers build their URLs from the slug that comes back, never from the one
 * they asked for.
 */
export async function organisationForTenant(
  page: Page,
  wanted: { name: string; slug: string; runtimeTenantId: string },
): Promise<{ id: string; slug: string }> {
  const created = await callOperation(
    page,
    "/operations/create-organization",
    wanted,
  );
  if (created.status === 200) {
    return { id: created.body.id, slug: created.body.slug ?? wanted.slug };
  }
  expect(created.status).toBe(409);
  const mine = await callOperation(page, "/operations/list-my-organizations");
  const found = (mine.body as { id: string; slug: string; runtimeTenantId: string }[]).find(
    (org) =>
      org.slug === wanted.slug || org.runtimeTenantId === wanted.runtimeTenantId,
  );
  if (!found) {
    throw new Error(
      `no organisation for tenant ${wanted.runtimeTenantId} is visible to this user, ` +
        `yet creating one answered 409`,
    );
  }
  return { id: found.id, slug: found.slug };
}


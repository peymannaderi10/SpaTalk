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

export const SERVER_URL = process.env.WASP_SERVER_URL ?? "http://localhost:3001";

/**
 * Calls a Wasp server operation with the signed-in session and returns the
 * HTTP status, so a test can assert that the server, not only the UI, refuses.
 */
export async function serverRequestStatus(
  page: Page,
  path: string,
): Promise<number> {
  return page.evaluate(
    async ({ url }: { url: string }) => {
      // Wasp stores the session id JSON-encoded under a prefixed key.
      const stored = localStorage.getItem("wasp:sessionId");
      const sessionId = stored ? (JSON.parse(stored) as string) : null;
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(sessionId ? { Authorization: `Bearer ${sessionId}` } : {}),
        },
        body: JSON.stringify({}),
      });
      return response.status;
    },
    { url: `${SERVER_URL}${path}` },
  );
}

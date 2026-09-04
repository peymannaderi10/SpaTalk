import { expect, test, type Page } from "@playwright/test";
import {
  agencyAdmin,
  createRandomUser,
  logUserIn,
  signInOrSignUp,
  signUserUp,
  verifyUserEmail,
  type User,
} from "./utils";

test.describe.configure({ mode: "serial" });

/** Vite compiles each route on its first visit in development. */
const FIRST_RENDER = { timeout: 30_000 };

let page: Page;
let user: User;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  user = createRandomUser();
});

test.afterAll(async () => {
  await page.close();
});

test.describe("signing up and in", () => {
  test("a new user signs up, verifies the emailed link and lands on /app", async () => {
    await signUserUp({ page, user });
    await verifyUserEmail({ page, user });
    await logUserIn({ page, user });

    // `/app` resolves to wherever this person's work is. A brand-new account
    // belongs to no organisation yet, so there is nowhere to send them and the
    // page says who invites them.
    await page.waitForURL("**/app");
    await expect(page.getByTestId("no-organisations")).toBeVisible(
      FIRST_RENDER,
    );
  });

  test("a signed-in user visiting / is sent to /app", async () => {
    await page.goto("/");

    await page.waitForURL("**/app");
    expect(new URL(page.url()).pathname).toBe("/app");
  });

  test("a signed-in user visiting /login is sent to /app", async () => {
    await page.goto("/login");

    await page.waitForURL("**/app");
    expect(new URL(page.url()).pathname).toBe("/app");
  });
});

test.describe("signed out", () => {
  test("visiting / is sent to /login", async ({ page: freshPage }) => {
    await freshPage.goto("/");

    await freshPage.waitForURL("**/login");
    expect(new URL(freshPage.url()).pathname).toBe("/login");
  });

  test("visiting /app is sent to /login", async ({ page: freshPage }) => {
    await freshPage.goto("/app");

    await freshPage.waitForURL("**/login");
    expect(new URL(freshPage.url()).pathname).toBe("/login");
  });
});

/**
 * The gateway at the door: two addresses, one session, and `/app` deciding
 * where each person's work is. `/admin/login` grants nothing — it is the same
 * form and the same credentials — so what this proves is only that an agency
 * admin who uses their own address arrives on the platform.
 */
test.describe("the platform sign-in", () => {
  test("an agency admin signs in at /admin/login and lands on /admin", async ({
    browser,
  }) => {
    // The account outlives a run; make sure it exists before signing in to it.
    const setup = await browser.newPage();
    await signInOrSignUp({ page: setup, user: agencyAdmin });
    await setup.close();

    const adminPage = await browser.newPage();
    try {
      await adminPage.goto("/admin/login", { waitUntil: "domcontentloaded" });
      await expect(
        adminPage.getByRole("heading", { name: "Platform sign-in" }),
      ).toBeVisible(FIRST_RENDER);

      await adminPage.fill('input[name="email"]', agencyAdmin.email);
      await adminPage.fill('input[name="password"]', agencyAdmin.password);
      await Promise.all([
        adminPage.waitForResponse((response) =>
          response.url().includes("/auth/email/login"),
        ),
        adminPage.click('button:has-text("Log in")'),
      ]);

      // It lands on `/app` like every other sign-in; the resolver is what
      // sends an agency admin on to the platform.
      await adminPage.waitForURL("**/admin", FIRST_RENDER);
      await expect(adminPage.getByTestId("nav-admin-tenants")).toBeVisible(
        FIRST_RENDER,
      );
    } finally {
      await adminPage.close();
    }
  });
});

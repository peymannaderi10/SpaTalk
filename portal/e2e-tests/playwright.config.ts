import { defineConfig, devices } from "@playwright/test";
import { RUNTIME_KEY, RUNTIME_URL } from "./tests/runtime";
import {
  STRIPE_TEST_API_KEY,
  STRIPE_TEST_PRICE_ID,
  STRIPE_TEST_WEBHOOK_SECRET,
} from "./tests/stripe";
import { AGENCY_ADMIN_EMAIL, SERVER_URL } from "./tests/utils";

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: "./tests",
  outputDir: "./test-results",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,

  /**
   * Playwright's default is 30 seconds per test. A test that signs a person
   * up, reads the emailed verification link out of the mail sink, logs in and
   * then walks two or three cold routes of a development build spends most of
   * that on Vite compiling pages on demand, so the budget is raised.
   */
  timeout: 120 * 1000,

  /**
   * Seeds one tenant, four conversations, four tracked items and a day of usage
   * into the runtime, and refuses to start the suite if no runtime answers.
   */
  globalSetup: require.resolve("./global-setup"),

  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  /**
   * The app runs in development mode so that the email sender is Wasp's Dummy
   * provider, which prints every message instead of sending it. The output is
   * piped into `mail-sink.log`, and the tests read the verification link from
   * there: that file is the suite's mail sink.
   */
  webServer: {
    command:
      "rm -f e2e-tests/mail-sink.log; wasp start </dev/null 2>&1 | tee e2e-tests/mail-sink.log",
    cwd: "..",
    env: {
      PORTAL_EMAIL_PROVIDER: "Dummy",
      // The links in every email and invitation carry these hosts, and the
      // suite drives http://localhost:3000. A developer's `.env.server` may
      // point them at a tunnel; an invitation opened on that origin parks its
      // token in another origin's storage and the sign-up round trip never
      // finds it (2026-09-06).
      WASP_WEB_CLIENT_URL: "http://localhost:3000",
      WASP_SERVER_URL: SERVER_URL,
      // Pinned so the organisation tests do not depend on whatever the local
      // .env.server holds: this address signs up as the agency admin.
      ADMIN_EMAILS: AGENCY_ADMIN_EMAIL,
      // The client pages read every tenant, conversation, item and usage number
      // from the runtime, so the server has to be pointed at the same one the
      // tests seeded and assert against.
      RUNTIME_INTERNAL_URL: RUNTIME_URL,
      RUNTIME_INTERNAL_KEY: RUNTIME_KEY,
      // Billing is proved with Stripe's own test-mode fixture events, signed
      // with this secret. Pinning it here means the suite does not depend on
      // whatever a developer happens to have in `.env.server`, and nothing in
      // these tests ever reaches Stripe.
      STRIPE_WEBHOOK_SECRET: STRIPE_TEST_WEBHOOK_SECRET,
      STRIPE_API_KEY: STRIPE_TEST_API_KEY,
      STRIPE_PRICE_ID_FRONTDESK: STRIPE_TEST_PRICE_ID,
      // A no-code portal link, so "Manage subscription" needs no Stripe call.
      STRIPE_CUSTOMER_PORTAL_URL: "https://billing.stripe.test/p/session/test",
    },
    url: "http://localhost:3000",
    reuseExistingServer: false,
    timeout: 900 * 1000,
    stdout: "pipe",
    stderr: "pipe",
  },
});

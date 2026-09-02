import { defineConfig, devices } from "@playwright/test";
import { AGENCY_ADMIN_EMAIL } from "./tests/utils";

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
      // Pinned so the organisation tests do not depend on whatever the local
      // .env.server holds: this address signs up as the agency admin.
      ADMIN_EMAILS: AGENCY_ADMIN_EMAIL,
    },
    url: "http://localhost:3000",
    reuseExistingServer: false,
    timeout: 900 * 1000,
    stdout: "pipe",
    stderr: "pipe",
  },
});

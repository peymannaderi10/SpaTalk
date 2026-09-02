import { defineConfig, devices } from "@playwright/test";

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
    },
    url: "http://localhost:3000",
    reuseExistingServer: false,
    timeout: 900 * 1000,
    stdout: "pipe",
    stderr: "pipe",
  },
});

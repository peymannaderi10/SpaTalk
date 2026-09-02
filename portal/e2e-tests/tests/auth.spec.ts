import { expect, test, type Page } from "@playwright/test";
import {
  createRandomUser,
  logUserIn,
  signUserUp,
  verifyUserEmail,
  type User,
} from "./utils";

test.describe.configure({ mode: "serial" });

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

    await page.waitForURL("**/app");
    await expect(
      page.getByRole("heading", { name: "Your front desk" }),
    ).toBeVisible();
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

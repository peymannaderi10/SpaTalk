import { expect, test, type Page } from "@playwright/test";
import {
  createRandomUser,
  logUserIn,
  serverRequestStatus,
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
  await signUserUp({ page, user });
  await verifyUserEmail({ page, user });
  await logUserIn({ page, user });
  await page.waitForURL("**/app");
});

test.afterAll(async () => {
  await page.close();
});

test.describe("agency admin area", () => {
  test("/admin is denied to a user who is not an agency admin", async () => {
    await page.goto("/admin");

    await page.waitForURL("**/app");
    expect(new URL(page.url()).pathname).toBe("/app");
    await expect(page.getByText("Total Revenue")).toHaveCount(0);
  });

  test("the admin stats query refuses a user who is not an agency admin", async () => {
    const status = await serverRequestStatus(page, "/operations/get-daily-stats");

    expect(status).toBe(403);
  });
});

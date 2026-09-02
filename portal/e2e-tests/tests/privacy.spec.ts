import { expect, test } from "@playwright/test";

test.describe("privacy policy", () => {
  test("/privacy renders for a signed-out visitor", async ({ page }) => {
    await page.goto("/privacy");

    await expect(
      page.getByRole("heading", { name: "Privacy policy" }),
    ).toBeVisible();
  });

  test("names the retention period and the subprocessors", async ({ page }) => {
    await page.goto("/privacy");

    await expect(page.getByText(/30 days by default/)).toBeVisible();
    for (const provider of ["OVHcloud", "Telnyx", "Soniox", "Inworld"]) {
      await expect(page.getByText(provider, { exact: true })).toBeVisible();
    }
    await expect(page.getByText("privacy@spatalk.ca").first()).toBeVisible();
  });
});

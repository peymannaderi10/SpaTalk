import { expect, test, type Page } from "@playwright/test";
import { agencyAdmin, organisationForTenant, SERVER_URL, signInOrSignUp } from "./utils";
import { checkoutSessionCompleted, postStripeEvent } from "./stripe";
import { runtimeGet } from "./runtime";

/**
 * The SMS block list (plan F, F2): a number blocked from the settings page is
 * on the runtime's list, shows in the table, and is gone again after Unblock.
 * Every assertion about state is against the runtime, not the portal.
 */

test.describe.configure({ mode: "serial" });

const FIRST_RENDER = { timeout: 30_000 };
const ORG_NAME = "Skincentrix Blocks";
// Asked for, then replaced by whatever organisation holds the tenant (see
// `organisationForTenant`): the URL below is built after `beforeAll` ran.
let ORG_SLUG = "skincentrix-blocks";
const RUNTIME_TENANT_ID = "skincentrix";
const NUMBER = "+19055550188";

let ownerPage: Page;

test.beforeAll(async ({ browser }) => {
  ownerPage = await browser.newPage();
  await signInOrSignUp({ page: ownerPage, user: agencyAdmin });

  const org = await organisationForTenant(ownerPage, {
    name: ORG_NAME,
    slug: ORG_SLUG,
    runtimeTenantId: RUNTIME_TENANT_ID,
  });
  const organizationId = org.id;
  ORG_SLUG = org.slug;
  const subscribed = await postStripeEvent(
    SERVER_URL,
    checkoutSessionCompleted({
      organizationId,
      stripeCustomerId: `cus_test_${ORG_SLUG}`,
      customerEmail: agencyAdmin.email,
    }),
  );
  expect([200, 204]).toContain(subscribed);
});

test.afterAll(async () => {
  await ownerPage.close();
});

test("blocking a number from settings puts it on the runtime's list, and Unblock removes it", async () => {
  await ownerPage.goto(`/app/${ORG_SLUG}/settings`);
  await ownerPage.getByRole("button", { name: "Numbers" }).click();
  await expect(ownerPage.getByTestId("sms-blocks")).toBeVisible(FIRST_RENDER);

  await ownerPage.getByTestId("sms-block-input").fill("905 555 0188");
  await ownerPage.getByTestId("sms-block-add").click();
  await expect(ownerPage.getByTestId("sms-block-row")).toContainText(NUMBER);
  await expect(ownerPage.getByTestId("sms-block-row")).toContainText("Blocked by a person");

  const listed = await runtimeGet<{ phone: string; until: string | null }[]>(
    `/internal/tenants/${RUNTIME_TENANT_ID}/sms-blocks`,
  );
  expect(listed.map((row) => row.phone)).toContain(NUMBER);
  expect(listed.find((row) => row.phone === NUMBER)?.until).toBeNull();

  await ownerPage.getByTestId("sms-unblock").click();
  await expect(ownerPage.getByTestId("sms-block-row")).toHaveCount(0);
  const after = await runtimeGet<{ phone: string }[]>(
    `/internal/tenants/${RUNTIME_TENANT_ID}/sms-blocks`,
  );
  expect(after.map((row) => row.phone)).not.toContain(NUMBER);
});

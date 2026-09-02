import { expect, test, type Page } from "@playwright/test";
import { randomBytes } from "crypto";
import {
  agencyAdmin,
  callOperation,
  createRandomUser,
  logUserIn,
  SERVER_URL,
  signInOrSignUp,
  signUserUp,
  verifyUserEmail,
  type User,
} from "./utils";
import {
  checkoutSessionCompleted,
  postStripeEvent,
  STRIPE_TEST_WEBHOOK_SECRET,
  subscriptionEvent,
} from "./stripe";

/**
 * Billing, per organisation.
 *
 * Stripe test-mode fixture events, signed with the secret
 * `playwright.config.ts` gives the app, are posted at `/payments-webhook`
 * exactly as Stripe would post them. What they must do is change one
 * organisation's subscription, and what that subscription must decide is
 * whether the client pages open (portal plan, Task C6).
 *
 * The organisation here deliberately points at a runtime tenant that does not
 * exist: nothing in this file is about tenant data, only about who is let in.
 */

test.describe.configure({ mode: "serial" });

/** Vite compiles each route on its first visit in development. */
const FIRST_RENDER = { timeout: 30_000 };

const suffix = randomBytes(4).toString("hex");
const ORG_NAME = `Billing Test ${suffix}`;
const ORG_SLUG = `billing-test-${suffix}`;
const RUNTIME_TENANT_ID = `billing-test-${suffix}`;
const STRIPE_CUSTOMER_ID = `cus_test_billing_${suffix}`;

/** The status the portal answers with when a subscription is what is missing. */
const PAYMENT_REQUIRED = 402;

let adminPage: Page;
let memberPage: Page;
let member: User;
let organizationId: string;

async function subscriptionStatusOf(slug: string): Promise<string | null> {
  const { body } = await callOperation(
    adminPage,
    "/operations/get-organization",
    {
      slug,
    },
  );
  return body.subscriptionStatus ?? null;
}

test.beforeAll(async ({ browser }) => {
  adminPage = await browser.newPage();
  memberPage = await browser.newPage();
  member = createRandomUser();

  await signInOrSignUp({ page: adminPage, user: agencyAdmin });

  const created = await callOperation(
    adminPage,
    "/operations/create-organization",
    { name: ORG_NAME, slug: ORG_SLUG, runtimeTenantId: RUNTIME_TENANT_ID },
  );
  expect(created.status).toBe(200);
  organizationId = created.body.id;

  // A real member, because an agency admin is exactly the person the gate lets
  // through and so cannot show that the gate is there at all.
  const invitation = await callOperation(
    adminPage,
    "/operations/invite-member",
    {
      organizationId,
      email: member.email,
      role: "OWNER",
    },
  );
  expect(invitation.status).toBe(200);

  await signUserUp({ page: memberPage, user: member });
  await verifyUserEmail({ page: memberPage, user: member });
  await logUserIn({ page: memberPage, user: member });
  await memberPage.waitForURL("**/app");

  const accepted = await callOperation(
    memberPage,
    "/operations/accept-invitation",
    { token: invitation.body.inviteUrl.split("/invite/")[1] },
  );
  expect(accepted.status).toBe(200);
});

test.afterAll(async () => {
  await adminPage.close();
  await memberPage.close();
});

test.describe("an organisation that has never subscribed", () => {
  test("is refused the conversations, requests and settings pages", async () => {
    for (const operation of [
      "get-tenant-conversations",
      "get-tenant-requests",
      "get-tenant-settings",
    ]) {
      const refused = await callOperation(
        memberPage,
        `/operations/${operation}`,
        { slug: ORG_SLUG },
      );
      expect(refused.status, `${operation} should need a subscription`).toBe(
        PAYMENT_REQUIRED,
      );
    }
  });

  test("is told why, on the page, instead of being shown an empty table", async () => {
    await memberPage.goto(`/app/${ORG_SLUG}/conversations`);
    const banner = memberPage.getByTestId("subscription-required");
    await expect(banner).toBeVisible(FIRST_RENDER);
    await expect(banner).toContainText(/no subscription/i);
    await expect(memberPage.getByTestId("conversation-row")).toHaveCount(0);
  });

  test("keeps the overview open, so an owner can see what they would be paying for", async () => {
    const answer = await callOperation(
      memberPage,
      "/operations/get-tenant-overview",
      { slug: ORG_SLUG },
    );
    expect(answer.status).not.toBe(PAYMENT_REQUIRED);
  });

  test("does not stop an agency admin", async () => {
    const answer = await callOperation(
      adminPage,
      "/operations/get-tenant-conversations",
      { slug: ORG_SLUG },
    );
    expect(answer.status).not.toBe(PAYMENT_REQUIRED);
  });

  test("has no Stripe billing portal to open yet", async () => {
    const answer = await callOperation(
      memberPage,
      "/operations/open-customer-portal",
      { organizationId },
    );
    expect(answer.status).toBe(404);
  });
});

test.describe("a Stripe checkout that completed", () => {
  test("subscribes the organisation it names", async () => {
    const status = await postStripeEvent(
      SERVER_URL,
      checkoutSessionCompleted({
        organizationId,
        stripeCustomerId: STRIPE_CUSTOMER_ID,
        customerEmail: member.email,
      }),
    );
    expect(status).toBe(204);

    expect(await subscriptionStatusOf(ORG_SLUG)).toBe("active");
  });

  test("opens the pages the gate was closing", async () => {
    const answer = await callOperation(
      memberPage,
      "/operations/get-tenant-requests",
      { slug: ORG_SLUG },
    );
    expect(answer.status).not.toBe(PAYMENT_REQUIRED);
  });

  test("gives the owner a link into Stripe's own billing portal", async () => {
    const answer = await callOperation(
      memberPage,
      "/operations/open-customer-portal",
      { organizationId },
    );
    expect(answer.status).toBe(200);
    // `playwright.config.ts` pins a no-code portal link, so this call reaches
    // no Stripe API; what it proves is that the portal now knows the customer.
    expect(answer.body).toContain("billing.stripe.test");
  });

  test("is refused when it is not signed with the portal's secret", async () => {
    const status = await postStripeEvent(
      SERVER_URL,
      subscriptionEvent({
        type: "customer.subscription.deleted",
        stripeCustomerId: STRIPE_CUSTOMER_ID,
      }),
      `${STRIPE_TEST_WEBHOOK_SECRET}_tampered`,
    );
    expect(status).toBe(400);
    expect(await subscriptionStatusOf(ORG_SLUG)).toBe("active");
  });
});

test.describe("a subscription that stops being paid", () => {
  test("is recorded as past due", async () => {
    const status = await postStripeEvent(
      SERVER_URL,
      subscriptionEvent({
        type: "customer.subscription.updated",
        stripeCustomerId: STRIPE_CUSTOMER_ID,
        status: "past_due",
      }),
    );
    expect(status).toBe(204);

    expect(await subscriptionStatusOf(ORG_SLUG)).toBe("past_due");
  });

  test("closes the client pages again, with a banner naming the failed payment", async () => {
    const refused = await callOperation(
      memberPage,
      "/operations/get-tenant-requests",
      { slug: ORG_SLUG },
    );
    expect(refused.status).toBe(PAYMENT_REQUIRED);

    await memberPage.goto(`/app/${ORG_SLUG}/requests`);
    const banner = memberPage.getByTestId("subscription-required");
    await expect(banner).toBeVisible(FIRST_RENDER);
    await expect(banner).toContainText(/payment/i);
  });

  test("still lets the agency admin in", async () => {
    const answer = await callOperation(
      adminPage,
      "/operations/get-tenant-requests",
      { slug: ORG_SLUG },
    );
    expect(answer.status).not.toBe(PAYMENT_REQUIRED);
  });
});

test.describe("a subscription that ends", () => {
  test("is recorded as ended", async () => {
    const status = await postStripeEvent(
      SERVER_URL,
      subscriptionEvent({
        type: "customer.subscription.deleted",
        stripeCustomerId: STRIPE_CUSTOMER_ID,
      }),
    );
    expect(status).toBe(204);

    expect(await subscriptionStatusOf(ORG_SLUG)).toBe("deleted");
  });

  test("leaves the billing page offering the plan again", async () => {
    await memberPage.goto(`/app/${ORG_SLUG}/billing`);
    await expect(
      memberPage.getByRole("heading", { name: "Billing" }),
    ).toBeVisible(FIRST_RENDER);
    await expect(memberPage.getByTestId("subscription-state")).toContainText(
      /ended/i,
    );
    await expect(
      memberPage.getByRole("button", { name: "Subscribe" }),
    ).toBeVisible();
  });
});

test.describe("an event for somebody else's customer", () => {
  test("changes nothing and is still answered", async () => {
    const status = await postStripeEvent(
      SERVER_URL,
      subscriptionEvent({
        type: "customer.subscription.updated",
        stripeCustomerId: "cus_test_not_ours_at_all",
        status: "active",
      }),
    );
    expect(status).toBe(204);

    expect(await subscriptionStatusOf(ORG_SLUG)).toBe("deleted");
  });
});

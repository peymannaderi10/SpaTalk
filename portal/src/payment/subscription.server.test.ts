import { describe, expect, test } from "vitest";
import {
  checkoutSessionCompleted,
  invoiceEvent,
  signEvent,
  STRIPE_TEST_PRICE_ID,
  STRIPE_TEST_WEBHOOK_SECRET,
  subscriptionEvent,
  unhandledEvent,
  type StripeEventBody,
} from "./stripe/fixtures";
import { UnhandledWebhookEventError } from "./errors";
import { PaymentPlanId, SubscriptionStatus } from "./plans";
import {
  applyStripeEvent,
  type OrganizationBillingDelegate,
} from "./subscription";

/**
 * What a Stripe webhook event does to an organisation.
 *
 * There is no Stripe account for this project, so the events are the test-mode
 * fixtures in `e2e-tests/tests/stripe.ts`, signed with a test secret and put
 * through the same verification the live endpoint uses. Nothing here reaches
 * the network: the organisation table is a fake with the two methods the
 * handler calls.
 */

const ORG_ID = "org-1";
const CUSTOMER = "cus_test_skincentrix";

type Row = {
  id: string;
  stripeCustomerId: string | null;
  subscriptionStatus: string | null;
  subscriptionPlan: string | null;
};

function organizations(rows: Row[]): OrganizationBillingDelegate & {
  rows: Row[];
} {
  const table = {
    rows,
    async updateMany({
      where,
      data,
    }: {
      where: { id?: string; stripeCustomerId?: string };
      data: Partial<Omit<Row, "id">>;
    }): Promise<{ count: number }> {
      const matched = rows.filter(
        (row) =>
          (where.id === undefined || row.id === where.id) &&
          (where.stripeCustomerId === undefined ||
            row.stripeCustomerId === where.stripeCustomerId),
      );
      for (const row of matched) {
        Object.assign(row, data);
      }
      return { count: matched.length };
    },
  };
  return table;
}

const planFor = (priceId: string): PaymentPlanId | null =>
  priceId === STRIPE_TEST_PRICE_ID ? PaymentPlanId.FrontDesk : null;

function deliver(
  event: StripeEventBody,
  table: OrganizationBillingDelegate,
  secret: string = STRIPE_TEST_WEBHOOK_SECRET,
) {
  const { rawBody, signature } = signEvent(event, secret);
  return applyStripeEvent({
    rawBody,
    signature,
    secret: STRIPE_TEST_WEBHOOK_SECRET,
    planFor,
    organizations: table,
  });
}

function unsubscribed(): Row {
  return {
    id: ORG_ID,
    stripeCustomerId: null,
    subscriptionStatus: null,
    subscriptionPlan: null,
  };
}

function subscribed(): Row {
  return {
    id: ORG_ID,
    stripeCustomerId: CUSTOMER,
    subscriptionStatus: SubscriptionStatus.Active,
    subscriptionPlan: PaymentPlanId.FrontDesk,
  };
}

describe("a completed checkout", () => {
  test("links the organisation that paid to its Stripe customer and subscribes it", async () => {
    const table = organizations([unsubscribed()]);

    const { updated } = await deliver(
      checkoutSessionCompleted({
        organizationId: ORG_ID,
        stripeCustomerId: CUSTOMER,
      }),
      table,
    );

    expect(updated).toBe(1);
    expect(table.rows[0]).toMatchObject({
      stripeCustomerId: CUSTOMER,
      subscriptionStatus: SubscriptionStatus.Active,
      subscriptionPlan: PaymentPlanId.FrontDesk,
    });
  });

  test("names the organisation from client_reference_id, not from the email", async () => {
    const other: Row = { ...unsubscribed(), id: "org-2" };
    const table = organizations([unsubscribed(), other]);

    await deliver(
      checkoutSessionCompleted({
        organizationId: "org-2",
        stripeCustomerId: CUSTOMER,
      }),
      table,
    );

    expect(table.rows[0].stripeCustomerId).toBeNull();
    expect(table.rows[1].stripeCustomerId).toBe(CUSTOMER);
  });

  test("a session that names no organisation changes nothing", async () => {
    const table = organizations([unsubscribed()]);
    const event = checkoutSessionCompleted({
      organizationId: ORG_ID,
      stripeCustomerId: CUSTOMER,
    });
    event.data.object.client_reference_id = null;
    event.data.object.metadata = {};

    const { updated } = await deliver(event, table);

    expect(updated).toBe(0);
    expect(table.rows[0]).toEqual(unsubscribed());
  });

  test("an unpaid session links the customer without claiming a subscription", async () => {
    const table = organizations([unsubscribed()]);

    await deliver(
      checkoutSessionCompleted({
        organizationId: ORG_ID,
        stripeCustomerId: CUSTOMER,
        paymentStatus: "unpaid",
      }),
      table,
    );

    expect(table.rows[0].stripeCustomerId).toBe(CUSTOMER);
    expect(table.rows[0].subscriptionStatus).toBeNull();
  });
});

describe("a changed subscription", () => {
  test("a deleted subscription ends the organisation's subscription", async () => {
    const table = organizations([subscribed()]);

    const { updated } = await deliver(
      subscriptionEvent({
        type: "customer.subscription.deleted",
        stripeCustomerId: CUSTOMER,
      }),
      table,
    );

    expect(updated).toBe(1);
    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.Deleted);
  });

  test("a trialing subscription is recorded as trialing, not as active", async () => {
    const table = organizations([subscribed()]);

    await deliver(
      subscriptionEvent({
        type: "customer.subscription.updated",
        stripeCustomerId: CUSTOMER,
        status: "trialing",
      }),
      table,
    );

    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.Trialing);
  });

  test("a past-due subscription is recorded as past due", async () => {
    const table = organizations([subscribed()]);

    await deliver(
      subscriptionEvent({
        type: "customer.subscription.updated",
        stripeCustomerId: CUSTOMER,
        status: "past_due",
      }),
      table,
    );

    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.PastDue);
  });

  test("an active subscription cancelled at period end is recorded as such", async () => {
    const table = organizations([subscribed()]);

    await deliver(
      subscriptionEvent({
        type: "customer.subscription.updated",
        stripeCustomerId: CUSTOMER,
        status: "active",
        cancelAtPeriodEnd: true,
      }),
      table,
    );

    expect(table.rows[0].subscriptionStatus).toBe(
      SubscriptionStatus.CancelAtPeriodEnd,
    );
  });

  test("a status the portal has no wording for leaves the organisation alone", async () => {
    const table = organizations([subscribed()]);

    const { updated } = await deliver(
      subscriptionEvent({
        type: "customer.subscription.updated",
        stripeCustomerId: CUSTOMER,
        status: "incomplete",
      }),
      table,
    );

    expect(updated).toBe(0);
    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.Active);
  });
});

describe("an invoice", () => {
  test("a paid invoice keeps the subscription active", async () => {
    const table = organizations([
      { ...subscribed(), subscriptionStatus: SubscriptionStatus.PastDue },
    ]);

    await deliver(
      invoiceEvent({ type: "invoice.paid", stripeCustomerId: CUSTOMER }),
      table,
    );

    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.Active);
  });

  test("a failed payment marks the organisation past due", async () => {
    const table = organizations([subscribed()]);

    await deliver(
      invoiceEvent({
        type: "invoice.payment_failed",
        stripeCustomerId: CUSTOMER,
      }),
      table,
    );

    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.PastDue);
  });
});

describe("an event the portal should not act on", () => {
  test("one signed with another secret is refused", async () => {
    const table = organizations([subscribed()]);

    await expect(
      deliver(
        subscriptionEvent({
          type: "customer.subscription.deleted",
          stripeCustomerId: CUSTOMER,
        }),
        table,
        "whsec_someone_elses_secret",
      ),
    ).rejects.toThrow(/signature/i);

    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.Active);
  });

  test("an unsigned event is refused", async () => {
    const table = organizations([subscribed()]);

    await expect(
      applyStripeEvent({
        rawBody: JSON.stringify(
          subscriptionEvent({
            type: "customer.subscription.deleted",
            stripeCustomerId: CUSTOMER,
          }),
        ),
        signature: undefined,
        secret: STRIPE_TEST_WEBHOOK_SECRET,
        planFor,
        organizations: table,
      }),
    ).rejects.toThrow(/signature/i);
  });

  test("an event type the portal does not handle is reported as unhandled", async () => {
    const table = organizations([subscribed()]);

    await expect(deliver(unhandledEvent(), table)).rejects.toBeInstanceOf(
      UnhandledWebhookEventError,
    );
  });

  test("an event for a customer no organisation owns changes nothing", async () => {
    const table = organizations([subscribed()]);

    const { updated } = await deliver(
      subscriptionEvent({
        type: "customer.subscription.deleted",
        stripeCustomerId: "cus_test_somebody_else",
      }),
      table,
    );

    expect(updated).toBe(0);
    expect(table.rows[0].subscriptionStatus).toBe(SubscriptionStatus.Active);
  });
});

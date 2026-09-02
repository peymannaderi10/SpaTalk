import { createHmac } from "crypto";

/**
 * Stripe test-mode fixture events, and the signature Stripe puts on them.
 *
 * No Stripe account, key or CLI exists for this project, so billing is proved
 * the way Stripe itself documents: an event body signed with a webhook secret
 * we hold, posted at the same endpoint Stripe would post at. The shapes below
 * are the ones `docs/reference/api-surface.md` names under "Stripe webhook
 * events used".
 *
 * Nothing in the running portal imports this module. It lives under `src` only
 * because both suites need one definition of the shapes and Wasp compiles user
 * code from `src` alone: the unit test in
 * `portal/src/payment/subscription.server.test.ts` feeds the bodies straight to
 * the handler, and `e2e-tests/tests/billing.spec.ts` posts them over HTTP to a
 * running portal.
 */

/**
 * The secret the end-to-end suite signs with. `playwright.config.ts` gives the
 * app under test the same value, so a developer's own `.env.server` never
 * changes what these tests prove.
 */
export const STRIPE_TEST_WEBHOOK_SECRET = "whsec_spatalk_e2e_test_secret";

/** The price the e2e app is configured with, echoed by the fixtures. */
export const STRIPE_TEST_PRICE_ID = "price_spatalk_frontdesk_test";

export const STRIPE_TEST_API_KEY = "sk_test_spatalk_e2e_not_a_real_key";

export type StripeEventBody = {
  id: string;
  object: "event";
  api_version: string;
  created: number;
  livemode: false;
  type: string;
  data: { object: Record<string, unknown> };
};

let counter = 0;

function eventId(): string {
  counter += 1;
  return `evt_test_${Date.now()}_${counter}`;
}

function envelope(
  type: string,
  object: Record<string, unknown>,
): StripeEventBody {
  return {
    id: eventId(),
    object: "event",
    api_version: "2025-04-30.basil",
    created: Math.floor(Date.now() / 1000),
    livemode: false,
    type,
    data: { object },
  };
}

/**
 * The event that says a clinic finished checkout. It is the only one that
 * carries `client_reference_id`, which is how the portal learns *which*
 * organisation the new Stripe customer belongs to.
 */
export function checkoutSessionCompleted({
  organizationId,
  stripeCustomerId,
  customerEmail = "owner@example.com",
  paymentStatus = "paid",
  paymentPlanId = "frontdesk",
}: {
  organizationId: string;
  stripeCustomerId: string;
  customerEmail?: string;
  paymentStatus?: "paid" | "unpaid" | "no_payment_required";
  paymentPlanId?: string;
}): StripeEventBody {
  return envelope("checkout.session.completed", {
    id: `cs_test_${counter}`,
    object: "checkout.session",
    mode: "subscription",
    status: "complete",
    payment_status: paymentStatus,
    client_reference_id: organizationId,
    customer: stripeCustomerId,
    customer_email: customerEmail,
    subscription: `sub_test_${counter}`,
    metadata: { organizationId, paymentPlanId },
  });
}

export function subscriptionEvent({
  type,
  stripeCustomerId,
  status = "active",
  cancelAtPeriodEnd = false,
  priceId = STRIPE_TEST_PRICE_ID,
}: {
  type: "customer.subscription.updated" | "customer.subscription.deleted";
  stripeCustomerId: string;
  status?: string;
  cancelAtPeriodEnd?: boolean;
  priceId?: string;
}): StripeEventBody {
  return envelope(type, {
    id: `sub_test_${counter}`,
    object: "subscription",
    customer: stripeCustomerId,
    status,
    cancel_at_period_end: cancelAtPeriodEnd,
    items: {
      object: "list",
      data: [
        {
          id: `si_test_${counter}`,
          object: "subscription_item",
          price: { id: priceId, object: "price" },
        },
      ],
    },
  });
}

export function invoiceEvent({
  type,
  stripeCustomerId,
  priceId = STRIPE_TEST_PRICE_ID,
}: {
  type: "invoice.paid" | "invoice.payment_failed";
  stripeCustomerId: string;
  priceId?: string;
}): StripeEventBody {
  return envelope(type, {
    id: `in_test_${counter}`,
    object: "invoice",
    customer: stripeCustomerId,
    status: type === "invoice.paid" ? "paid" : "open",
    status_transitions: {
      paid_at: type === "invoice.paid" ? Math.floor(Date.now() / 1000) : null,
    },
    lines: {
      object: "list",
      data: [
        {
          id: `il_test_${counter}`,
          object: "line_item",
          pricing: { price_details: { price: priceId } },
        },
      ],
    },
  });
}

/** An event type the portal does not handle, to prove it is ignored quietly. */
export function unhandledEvent(): StripeEventBody {
  return envelope("payment_intent.succeeded", {
    id: `pi_test_${counter}`,
    object: "payment_intent",
  });
}

/**
 * Stripe signs `"{timestamp}.{raw body}"` with HMAC-SHA256 and puts the result
 * in `Stripe-Signature` as `t=<timestamp>,v1=<hex digest>`.
 * https://docs.stripe.com/webhooks#verify-manually
 */
export function signStripePayload(
  rawBody: string,
  secret: string,
  timestampSeconds: number = Math.floor(Date.now() / 1000),
): string {
  const signature = createHmac("sha256", secret)
    .update(`${timestampSeconds}.${rawBody}`, "utf8")
    .digest("hex");
  return `t=${timestampSeconds},v1=${signature}`;
}

export type SignedEvent = { rawBody: string; signature: string };

export function signEvent(
  event: StripeEventBody,
  secret: string = STRIPE_TEST_WEBHOOK_SECRET,
): SignedEvent {
  const rawBody = JSON.stringify(event);
  return { rawBody, signature: signStripePayload(rawBody, secret) };
}

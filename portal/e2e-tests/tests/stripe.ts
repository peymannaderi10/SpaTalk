import {
  signEvent,
  STRIPE_TEST_WEBHOOK_SECRET,
  type StripeEventBody,
} from "../../src/payment/stripe/fixtures";

/**
 * Posting Stripe's test-mode fixture events at the portal, exactly as Stripe
 * would post them.
 *
 * The event shapes and the signature live with the payment code
 * (`src/payment/stripe/fixtures.ts`) so the unit test and this suite prove the
 * same bodies; this module is only the HTTP half.
 */

export {
  checkoutSessionCompleted,
  invoiceEvent,
  signEvent,
  signStripePayload,
  STRIPE_TEST_API_KEY,
  STRIPE_TEST_PRICE_ID,
  STRIPE_TEST_WEBHOOK_SECRET,
  subscriptionEvent,
  unhandledEvent,
  type StripeEventBody,
} from "../../src/payment/stripe/fixtures";

/**
 * Posts a signed fixture event at the portal's webhook endpoint. Returns the
 * HTTP status the portal answered with.
 */
export async function postStripeEvent(
  serverUrl: string,
  event: StripeEventBody,
  secret: string = STRIPE_TEST_WEBHOOK_SECRET,
): Promise<number> {
  const { rawBody, signature } = signEvent(event, secret);
  const response = await fetch(`${serverUrl}/payments-webhook`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Stripe-Signature": signature,
    },
    body: rawBody,
  });
  return response.status;
}

import Stripe from "stripe";
import { checkoutCanceledUrl, checkoutSuccessUrl } from "../paths";
import { type PaymentPlanId } from "../plans";
import { stripeClient } from "./stripeClient";

interface CreateStripeCheckoutSessionParams {
  priceId: Stripe.Price["id"];
  paymentPlanId: PaymentPlanId;
  organizationId: string;
  organizationSlug: string;
  organizationName: string;
  /** The owner starting the checkout; Stripe prefills and invoices this. */
  ownerEmail: string;
}

/**
 * The subscription checkout for one clinic.
 *
 * `client_reference_id` is the organisation id: it is the only thing that comes
 * back on `checkout.session.completed`, and therefore the only honest way to
 * decide which clinic a new Stripe customer belongs to. Matching on the email
 * address instead would tie the subscription to whichever person happened to
 * click, which is the bug this whole task exists to remove.
 *
 * No customer is created up front: `customer_email` lets Stripe make one, and
 * the webhook writes its id onto the organisation.
 */
export function createStripeCheckoutSession({
  priceId,
  paymentPlanId,
  organizationId,
  organizationSlug,
  organizationName,
  ownerEmail,
}: CreateStripeCheckoutSessionParams): Promise<Stripe.Checkout.Session> {
  return stripeClient.checkout.sessions.create({
    mode: "subscription",
    line_items: [{ price: priceId, quantity: 1 }],
    client_reference_id: organizationId,
    customer_email: ownerEmail,
    metadata: { organizationId, organizationSlug, paymentPlanId },
    subscription_data: {
      description: organizationName,
      metadata: { organizationId, organizationSlug, paymentPlanId },
    },
    success_url: checkoutSuccessUrl(organizationSlug),
    cancel_url: checkoutCanceledUrl(organizationSlug),
    automatic_tax: { enabled: true },
    allow_promotion_codes: true,
  });
}

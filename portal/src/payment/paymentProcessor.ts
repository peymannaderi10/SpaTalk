import type { MiddlewareConfigFn } from "wasp/server";
import type { PaymentsWebhook } from "wasp/server/api";
import type { PaymentPlan } from "./plans";
import { stripePaymentProcessor } from "./stripe/paymentProcessor";

/**
 * The payment processor, seen from the rest of the portal.
 *
 * Everything here is keyed to an organisation: a clinic subscribes, not a
 * person (portal plan, Task C6). The processor never reads or writes the
 * database — the webhook does that through `src/payment/subscription.ts`.
 */

export interface CreateCheckoutSessionArgs {
  organizationId: string;
  organizationSlug: string;
  organizationName: string;
  /** The owner starting the checkout. Stripe prefills and invoices this. */
  ownerEmail: string;
  paymentPlan: PaymentPlan;
}

export interface FetchCustomerPortalUrlArgs {
  /** Learned from `checkout.session.completed`; null before a first payment. */
  stripeCustomerId: string;
  organizationSlug: string;
}

export interface PaymentProcessor {
  id: "stripe";
  createCheckoutSession: (
    args: CreateCheckoutSessionArgs,
  ) => Promise<{ session: { id: string; url: string } }>;
  fetchCustomerPortalUrl: (
    args: FetchCustomerPortalUrlArgs,
  ) => Promise<string | null>;
  webhook: PaymentsWebhook;
  webhookMiddlewareConfigFn: MiddlewareConfigFn;
  fetchTotalRevenue: () => Promise<number>;
}

export const paymentProcessor: PaymentProcessor = stripePaymentProcessor;

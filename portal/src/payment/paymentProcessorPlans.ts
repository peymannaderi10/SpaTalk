import { env } from "wasp/server";
import { type PaymentPlan, PaymentPlanId } from "./plans";

/**
 * The ID under which this payment plan is identified on Stripe (a price ID).
 */
export const paymentProcessorPlanIds = {
  [PaymentPlanId.FrontDesk]: env.STRIPE_PRICE_ID_FRONTDESK,
} as const satisfies Record<PaymentPlanId, string>;

/**
 * Returns the Stripe price ID for a given `PaymentPlan`.
 */
export function getPaymentProcessorPlanId(paymentPlan: PaymentPlan): string {
  return paymentProcessorPlanIds[paymentPlan.id];
}

/**
 * Returns the `PaymentPlanId` for a Stripe price ID, or null when the price is
 * not one of ours.
 *
 * Null rather than a throw: the same Stripe account may carry prices that have
 * nothing to do with this portal, and an exception in the webhook would make
 * Stripe retry a foreign event until it gave up.
 */
export function findPaymentPlanIdByPaymentProcessorPlanId(
  paymentProcessorPlanId: string,
): PaymentPlanId | null {
  for (const [planId, processorPlanId] of Object.entries(
    paymentProcessorPlanIds,
  )) {
    if (processorPlanId === paymentProcessorPlanId) {
      return planId as PaymentPlanId;
    }
  }

  return null;
}

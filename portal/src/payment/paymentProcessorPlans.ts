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
 * Returns the `PaymentPlanId` for a Stripe price ID.
 */
export function getPaymentPlanIdByPaymentProcessorPlanId(
  paymentProcessorPlanId: string,
): PaymentPlanId {
  for (const [planId, processorPlanId] of Object.entries(
    paymentProcessorPlanIds,
  )) {
    if (processorPlanId === paymentProcessorPlanId) {
      return planId as PaymentPlanId;
    }
  }

  throw new Error(
    `Unknown payment processor plan ID: ${paymentProcessorPlanId}`,
  );
}

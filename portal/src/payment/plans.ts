/**
 * What the portal records on `Organization.subscriptionStatus`.
 *
 * These are Stripe's own words, kept rather than flattened: a trial and a paid
 * subscription both open the client pages, but only one of them is money, and
 * the agency's revenue table has to be able to tell them apart.
 */
export enum SubscriptionStatus {
  PastDue = "past_due",
  CancelAtPeriodEnd = "cancel_at_period_end",
  Trialing = "trialing",
  Active = "active",
  Deleted = "deleted",
}

export enum PaymentPlanId {
  FrontDesk = "frontdesk",
}

/**
 * The list price of the single plan, in Canadian dollars per month
 * (`docs/runbooks/accounts-and-env.md` § 10: "recurring price CA$999 per
 * month"). Stripe holds the price of record; this is what the portal prints
 * where it has to name a figure, and every page that does says so.
 */
export const PLAN_MONTHLY_CAD = 999;

export const PLAN_PRICE_TEXT = "CA$999";

/** What the plan includes, in the words the pricing and billing pages use. */
export const PLAN_FEATURES: readonly string[] = [
  "Phone, SMS, web chat and Instagram",
  "Every request tracked until a person closes it",
  "Owner dashboard, transcripts and audit trail",
];

export interface PaymentPlan {
  id: PaymentPlanId;
  effect: PaymentPlanEffect;
}

export type PaymentPlanEffect = { kind: "subscription" };

export const paymentPlans = {
  [PaymentPlanId.FrontDesk]: {
    id: PaymentPlanId.FrontDesk,
    effect: { kind: "subscription" },
  },
} as const satisfies Record<PaymentPlanId, PaymentPlan>;

export function prettyPaymentPlanName(planId: PaymentPlanId): string {
  const planToName: Record<PaymentPlanId, string> = {
    [PaymentPlanId.FrontDesk]: "AI front desk",
  };
  return planToName[planId];
}

export function parsePaymentPlanId(planId: string): PaymentPlanId {
  if ((Object.values(PaymentPlanId) as string[]).includes(planId)) {
    return planId as PaymentPlanId;
  } else {
    throw new Error(`Invalid PaymentPlanId: ${planId}`);
  }
}

export function getSubscriptionPaymentPlanIds(): PaymentPlanId[] {
  return Object.values(PaymentPlanId).filter(
    (planId) => paymentPlans[planId].effect.kind === "subscription",
  );
}

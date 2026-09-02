import type Stripe from "stripe";
import {
  subscriptionChangeFor,
  verifyStripeEvent,
  type PlanForPriceId,
  type SubscriptionChange,
} from "./stripe/events";

/**
 * Writing a subscription onto an organisation.
 *
 * Billing is keyed to `Organization`, never to `User` (portal plan, Task C6):
 * a clinic pays, not a person, and the people in a clinic come and go. The
 * table is passed in rather than imported so this whole path — verify, read,
 * write — is exercised by a unit test with fixture events and no database.
 */

export type OrganizationBillingUpdate = {
  stripeCustomerId?: string;
  subscriptionStatus?: string;
  subscriptionPlan?: string;
};

/**
 * The two Prisma calls this module makes, and nothing else. `updateMany` for
 * both, so an event about a Stripe customer no organisation owns is a count of
 * zero rather than an exception Stripe would retry forever.
 */
export type OrganizationBillingDelegate = {
  updateMany(args: {
    where: { id?: string; stripeCustomerId?: string };
    data: OrganizationBillingUpdate;
  }): Promise<{ count: number }>;
};

export async function applySubscriptionChange(
  change: SubscriptionChange,
  organizations: OrganizationBillingDelegate,
): Promise<number> {
  const data: OrganizationBillingUpdate = {};
  if (change.subscriptionStatus !== undefined) {
    data.subscriptionStatus = change.subscriptionStatus;
  }
  if (change.subscriptionPlan !== undefined) {
    data.subscriptionPlan = change.subscriptionPlan;
  }

  if (change.organizationId) {
    // The checkout named the organisation, so this is also where the Stripe
    // customer id is written for every later event to find it by.
    const { count } = await organizations.updateMany({
      where: { id: change.organizationId },
      data: { ...data, stripeCustomerId: change.stripeCustomerId },
    });
    return count;
  }

  if (Object.keys(data).length === 0) {
    return 0;
  }

  const { count } = await organizations.updateMany({
    where: { stripeCustomerId: change.stripeCustomerId },
    data,
  });
  return count;
}

/**
 * The whole webhook path: prove the event is Stripe's, read what it says, write
 * it. Throws when the signature does not verify, and
 * `UnhandledWebhookEventError` for an event type the portal does not act on.
 */
export async function applyStripeEvent({
  rawBody,
  signature,
  secret,
  planFor,
  organizations,
}: {
  rawBody: string | Buffer;
  signature: string | string[] | undefined;
  secret: string;
  planFor: PlanForPriceId;
  organizations: OrganizationBillingDelegate;
}): Promise<{ event: Stripe.Event; updated: number }> {
  const event = verifyStripeEvent(rawBody, signature, secret);
  const change = subscriptionChangeFor(event, planFor);
  if (!change) {
    return { event, updated: 0 };
  }
  return {
    event,
    updated: await applySubscriptionChange(change, organizations),
  };
}

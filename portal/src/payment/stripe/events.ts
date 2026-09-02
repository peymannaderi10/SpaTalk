import Stripe from "stripe";
import { UnhandledWebhookEventError } from "../errors";
import {
  parsePaymentPlanId,
  PaymentPlanId,
  SubscriptionStatus,
} from "../plans";

/**
 * Reading a Stripe webhook event: is it really from Stripe, and what does it
 * say about one organisation's subscription?
 *
 * Deliberately free of Wasp, Prisma and the environment, so the whole path from
 * a signed body to a decision can be exercised by a unit test with fixture
 * events (`fixtures.ts`) and no network. The writing half is
 * `src/payment/subscription.ts`.
 */

/** What one event asks the portal to write on one organisation. */
export type SubscriptionChange = {
  /**
   * Set only by `checkout.session.completed`, the one event that carries the
   * `client_reference_id` we put on the Checkout Session. Every other event
   * finds its organisation by Stripe customer id.
   */
  organizationId?: string;
  stripeCustomerId: string;
  subscriptionStatus?: SubscriptionStatus;
  subscriptionPlan?: PaymentPlanId;
};

/** Resolves a Stripe price id to one of our plans, or null if it is not ours. */
export type PlanForPriceId = (priceId: string) => PaymentPlanId | null;

/**
 * Verifies Stripe's signature over the raw body. Stripe signs
 * `"{timestamp}.{body}"` with the endpoint's secret; `Stripe.webhooks` does the
 * comparison in constant time and rejects a timestamp outside its tolerance.
 */
export function verifyStripeEvent(
  rawBody: string | Buffer,
  signature: string | string[] | undefined,
  secret: string,
): Stripe.Event {
  if (!signature) {
    throw new Error("Stripe webhook signature not provided");
  }
  return Stripe.webhooks.constructEvent(
    rawBody,
    Array.isArray(signature) ? signature[0] : signature,
    secret,
  );
}

export function subscriptionChangeFor(
  event: Stripe.Event,
  planFor: PlanForPriceId,
): SubscriptionChange | null {
  switch (event.type) {
    case "checkout.session.completed":
      return fromCheckoutSession(event.data.object);
    case "customer.subscription.updated":
      return fromSubscription(event.data.object, planFor);
    case "customer.subscription.deleted":
      return {
        stripeCustomerId: customerIdOf(event.data.object.customer),
        subscriptionStatus: SubscriptionStatus.Deleted,
      };
    case "invoice.paid":
      return fromInvoice(event.data.object, SubscriptionStatus.Active, planFor);
    case "invoice.payment_failed":
      return fromInvoice(
        event.data.object,
        SubscriptionStatus.PastDue,
        planFor,
      );
    default:
      throw new UnhandledWebhookEventError(event.type);
  }
}

/**
 * The only event that says *which organisation* paid. The Checkout Session was
 * created with `client_reference_id` set to the organisation id, so this is
 * where a Stripe customer is first tied to a clinic.
 */
function fromCheckoutSession(
  session: Stripe.Checkout.Session,
): SubscriptionChange | null {
  const organizationId =
    session.client_reference_id ?? session.metadata?.organizationId ?? null;
  if (!organizationId) {
    // A session the portal did not create, or one whose reference was lost:
    // guessing the organisation from an email address is exactly the mistake
    // `client_reference_id` exists to prevent.
    return null;
  }

  const stripeCustomerId = session.customer
    ? customerIdOf(session.customer)
    : null;
  if (!stripeCustomerId) {
    return null;
  }

  return {
    organizationId,
    stripeCustomerId,
    // An unpaid session still tells us who the customer is; it does not tell us
    // the clinic is subscribed.
    subscriptionStatus:
      session.payment_status === "unpaid"
        ? undefined
        : SubscriptionStatus.Active,
    subscriptionPlan: planFromMetadata(session.metadata),
  };
}

function planFromMetadata(
  metadata: Stripe.Metadata | null,
): PaymentPlanId | undefined {
  const raw = metadata?.paymentPlanId;
  if (!raw) {
    return undefined;
  }
  try {
    return parsePaymentPlanId(raw);
  } catch {
    return undefined;
  }
}

function fromSubscription(
  subscription: Stripe.Subscription,
  planFor: PlanForPriceId,
): SubscriptionChange | null {
  const subscriptionStatus = statusOf(subscription);
  if (!subscriptionStatus) {
    // `paused` and `incomplete` have no wording in the portal and no meaning
    // for the gate; leaving the organisation as it is beats inventing a state.
    return null;
  }

  return {
    stripeCustomerId: customerIdOf(subscription.customer),
    subscriptionStatus,
    subscriptionPlan: planOfSubscription(subscription, planFor),
  };
}

function statusOf(
  subscription: Stripe.Subscription,
): SubscriptionStatus | undefined {
  const stripeToPortal: Record<
    Stripe.Subscription.Status,
    SubscriptionStatus | undefined
  > = {
    trialing: SubscriptionStatus.Trialing,
    active: SubscriptionStatus.Active,
    past_due: SubscriptionStatus.PastDue,
    canceled: SubscriptionStatus.Deleted,
    unpaid: SubscriptionStatus.Deleted,
    incomplete_expired: SubscriptionStatus.Deleted,
    paused: undefined,
    incomplete: undefined,
  };

  const status = stripeToPortal[subscription.status];
  const stillPaidFor =
    status === SubscriptionStatus.Active ||
    status === SubscriptionStatus.Trialing;

  if (stillPaidFor && subscription.cancel_at_period_end) {
    return SubscriptionStatus.CancelAtPeriodEnd;
  }
  return status;
}

function planOfSubscription(
  subscription: Stripe.Subscription,
  planFor: PlanForPriceId,
): PaymentPlanId | undefined {
  const items = subscription.items?.data ?? [];
  if (items.length !== 1) {
    // One plan, one item. Anything else is somebody else's product on the same
    // Stripe account, and the portal has nothing to say about it.
    return undefined;
  }
  return planFor(items[0].price.id) ?? undefined;
}

function fromInvoice(
  invoice: Stripe.Invoice,
  subscriptionStatus: SubscriptionStatus,
  planFor: PlanForPriceId,
): SubscriptionChange | null {
  if (!invoice.customer) {
    return null;
  }
  return {
    stripeCustomerId: customerIdOf(invoice.customer),
    subscriptionStatus,
    subscriptionPlan: planOfInvoice(invoice, planFor),
  };
}

function planOfInvoice(
  invoice: Stripe.Invoice,
  planFor: PlanForPriceId,
): PaymentPlanId | undefined {
  const lines = invoice.lines?.data ?? [];
  if (lines.length !== 1) {
    return undefined;
  }
  const priceId = lines[0].pricing?.price_details?.price;
  return priceId ? planFor(priceId) ?? undefined : undefined;
}

function customerIdOf(
  customer: string | Stripe.Customer | Stripe.DeletedCustomer,
): string {
  return typeof customer === "string" ? customer : customer.id;
}

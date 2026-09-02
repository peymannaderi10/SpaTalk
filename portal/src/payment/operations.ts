import { HttpError } from "wasp/server";
import type {
  GenerateCheckoutSession,
  OpenCustomerPortal,
} from "wasp/server/operations";
import * as z from "zod";
import { requireOrgOwner } from "../organizations/access";
import { ensureArgsSchemaOrThrowHttpError } from "../server/validation";
import { paymentProcessor } from "./paymentProcessor";
import { PaymentPlanId, paymentPlans } from "./plans";

/**
 * Subscribing a clinic, and managing that subscription afterwards.
 *
 * Both are an owner's job: `requireOrgOwner` refuses STAFF, and an agency admin
 * passes as an owner of every organisation (portal plan, Task C2). Nothing here
 * writes a subscription — Stripe's webhook does that, so what the portal shows
 * is what Stripe actually did.
 */

export type CheckoutSession = {
  sessionUrl: string | null;
  sessionId: string;
};

const organizationArgs = z.object({
  organizationId: z.string().min(1),
});

export const generateCheckoutSession: GenerateCheckoutSession<
  z.infer<typeof organizationArgs>,
  CheckoutSession
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(organizationArgs, rawArgs);
  const { org } = await requireOrgOwner(context, args.organizationId);

  const ownerEmail = context.user?.email;
  if (!ownerEmail) {
    throw new HttpError(
      403,
      "Your account needs an email address before you can subscribe.",
    );
  }

  const { session } = await paymentProcessor.createCheckoutSession({
    organizationId: org.id,
    organizationSlug: org.slug,
    organizationName: org.name,
    ownerEmail,
    paymentPlan: paymentPlans[PaymentPlanId.FrontDesk],
  });

  return { sessionUrl: session.url, sessionId: session.id };
};

/**
 * An action, not a query: it creates a single-use Stripe billing portal session,
 * so it must happen when the owner asks for it, not on every page render.
 */
export const openCustomerPortal: OpenCustomerPortal<
  z.infer<typeof organizationArgs>,
  string
> = async (rawArgs, context) => {
  const args = ensureArgsSchemaOrThrowHttpError(organizationArgs, rawArgs);
  const { org } = await requireOrgOwner(context, args.organizationId);

  if (!org.stripeCustomerId) {
    throw new HttpError(
      404,
      "This organisation has never been billed, so it has no Stripe customer to manage yet.",
    );
  }

  const url = await paymentProcessor.fetchCustomerPortalUrl({
    stripeCustomerId: org.stripeCustomerId,
    organizationSlug: org.slug,
  });

  if (!url) {
    throw new HttpError(502, "Stripe did not return a billing portal link.");
  }
  return url;
};

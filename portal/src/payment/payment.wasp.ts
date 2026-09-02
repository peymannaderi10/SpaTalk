import { action, api, page, route, type Spec } from "@wasp.sh/spec";

import { BillingPage } from "./BillingPage" with { type: "ref" };
import {
  generateCheckoutSession,
  openCustomerPortal,
} from "./operations" with { type: "ref" };
import { PricingPage } from "./PricingPage" with { type: "ref" };
import {
  paymentsMiddlewareConfigFn,
  paymentsWebhook,
} from "./webhook" with { type: "ref" };

/**
 * Billing belongs to an organisation, so its page hangs off one
 * (`/app/:orgSlug/billing`) and both operations take an organisation id. The
 * webhook needs only the `Organization` table: it is the only thing a Stripe
 * event ever writes.
 */

const orgEntities = { entities: ["Organization", "Membership"] };

export const paymentSpec: Spec = [
  route("PricingPageRoute", "/pricing", page(PricingPage), { prerender: true }),
  route(
    "OrgBillingRoute",
    "/app/:orgSlug/billing",
    page(BillingPage, { authRequired: true }),
  ),

  action(generateCheckoutSession, orgEntities),
  action(openCustomerPortal, orgEntities),

  api("POST", "/payments-webhook", paymentsWebhook, {
    entities: ["Organization"],
    middlewareConfigFn: paymentsMiddlewareConfigFn,
  }),
];

import { config } from "wasp/server";

/**
 * Where Stripe sends the owner back to.
 *
 * Billing belongs to an organisation, so every one of these is that
 * organisation's billing page: an owner who pays for two clinics must land back
 * on the one they were paying for.
 */

function billingUrl(organizationSlug: string, query: string): string {
  const base = config.frontendUrl.replace(/\/$/, "");
  return `${base}/app/${encodeURIComponent(organizationSlug)}/billing${query}`;
}

export function checkoutSuccessUrl(organizationSlug: string): string {
  return billingUrl(organizationSlug, "?checkout=success");
}

export function checkoutCanceledUrl(organizationSlug: string): string {
  return billingUrl(organizationSlug, "?checkout=canceled");
}

export function customerPortalReturnUrl(organizationSlug: string): string {
  return billingUrl(organizationSlug, "");
}

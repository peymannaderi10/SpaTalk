import { SubscriptionStatus } from "./plans";

/**
 * Whether an organisation's subscription opens its client pages, and how to
 * say so when it does not.
 *
 * Portal plan, Task C6: every client page except the overview needs a live
 * subscription, and an agency admin is let through regardless. The rule lives
 * here, browser-safe, so the server operation that refuses and the page that
 * explains the refusal read the same list — a gate the UI hides but the server
 * still opens is the failure mode this module exists to prevent.
 */

/**
 * The statuses in which the clinic is still owed the service.
 *
 * `cancel_at_period_end` is on the list because the clinic has paid for the
 * period it is in; closing the pages the day they cancel would take away
 * something already bought. It is the same list the agency counts as revenue
 * (`src/admin/agency.ts`), and deliberately so: "we are being paid" and "they
 * get the service" must not drift apart.
 */
export const ENTITLING_SUBSCRIPTION_STATUSES: readonly string[] = [
  SubscriptionStatus.Active,
  SubscriptionStatus.Trialing,
  SubscriptionStatus.CancelAtPeriodEnd,
];

export function isEntitlingStatus(status: string | null | undefined): boolean {
  return (
    status !== null &&
    status !== undefined &&
    ENTITLING_SUBSCRIPTION_STATUSES.includes(status)
  );
}

export function organizationIsEntitled({
  subscriptionStatus,
  viewerIsAgencyAdmin,
}: {
  subscriptionStatus: string | null | undefined;
  viewerIsAgencyAdmin: boolean;
}): boolean {
  return viewerIsAgencyAdmin || isEntitlingStatus(subscriptionStatus);
}

export type SubscriptionProblem = {
  headline: string;
  detail: string;
  /** What the owner can do about it, as a verb for the button. */
  action: "subscribe" | "manage";
};

/**
 * What to tell someone whose organisation's pages are closed. Nothing here
 * says or implies that anything was deleted: the clinic's conversations,
 * requests and settings are the runtime's, and a lapsed subscription does not
 * touch them.
 */
export function subscriptionProblem(
  status: string | null | undefined,
): SubscriptionProblem | null {
  if (isEntitlingStatus(status)) {
    return null;
  }

  switch (status) {
    case SubscriptionStatus.PastDue:
      return {
        headline: "The last payment did not go through",
        detail:
          "Conversations, requests and settings are closed until the payment method is updated. Nothing has been lost.",
        action: "manage",
      };
    case SubscriptionStatus.Deleted:
      return {
        headline: "This subscription has ended",
        detail:
          "Conversations, requests and settings are closed. Subscribe again to reopen them.",
        action: "subscribe",
      };
    default:
      return {
        headline: "No subscription yet",
        detail:
          "Conversations, requests and settings open once this organisation is subscribed.",
        action: "subscribe",
      };
  }
}

/** The status the portal answers with when a subscription is what is missing. */
export const SUBSCRIPTION_REQUIRED_STATUS = 402;

export function subscriptionRequiredMessage(
  organizationName: string,
  status: string | null | undefined,
): string {
  const problem = subscriptionProblem(status);
  return `${organizationName}: ${problem?.headline ?? "No subscription yet"}. ${
    problem?.detail ?? ""
  }`.trim();
}

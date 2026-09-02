import { describe, expect, test } from "vitest";
import {
  isEntitlingStatus,
  organizationIsEntitled,
  subscriptionProblem,
} from "./entitlement";
import { SubscriptionStatus } from "./plans";

/**
 * Who may open a client page.
 *
 * The portal plan (Task C6) gates every client page except the overview on the
 * organisation's subscription, and lets an agency admin through regardless. The
 * rules live in one browser-safe module so the server operation that refuses
 * and the page that explains the refusal cannot drift apart.
 */

describe("a subscription that opens the client pages", () => {
  test("an active subscription opens them", () => {
    expect(isEntitlingStatus(SubscriptionStatus.Active)).toBe(true);
  });

  test("a subscription still in its trial opens them", () => {
    expect(isEntitlingStatus(SubscriptionStatus.Trialing)).toBe(true);
  });

  test("a subscription cancelled at period end stays open until it ends", () => {
    // The clinic has paid for this month; the subscription ends later.
    expect(isEntitlingStatus(SubscriptionStatus.CancelAtPeriodEnd)).toBe(true);
  });
});

describe("a subscription that does not", () => {
  test("a past-due subscription is closed", () => {
    expect(isEntitlingStatus(SubscriptionStatus.PastDue)).toBe(false);
  });

  test("an ended subscription is closed", () => {
    expect(isEntitlingStatus(SubscriptionStatus.Deleted)).toBe(false);
  });

  test("an organisation that never subscribed is closed", () => {
    expect(isEntitlingStatus(null)).toBe(false);
    expect(isEntitlingStatus(undefined)).toBe(false);
  });

  test("a status the portal does not know is closed, not assumed open", () => {
    expect(isEntitlingStatus("incomplete")).toBe(false);
  });
});

describe("who the gate lets through", () => {
  test("a member of a subscribed organisation is let through", () => {
    expect(
      organizationIsEntitled({
        subscriptionStatus: SubscriptionStatus.Active,
        viewerIsAgencyAdmin: false,
      }),
    ).toBe(true);
  });

  test("a member of an unsubscribed organisation is not", () => {
    expect(
      organizationIsEntitled({
        subscriptionStatus: null,
        viewerIsAgencyAdmin: false,
      }),
    ).toBe(false);
  });

  test("an agency admin is let through without any subscription", () => {
    expect(
      organizationIsEntitled({
        subscriptionStatus: null,
        viewerIsAgencyAdmin: true,
      }),
    ).toBe(true);
    expect(
      organizationIsEntitled({
        subscriptionStatus: SubscriptionStatus.PastDue,
        viewerIsAgencyAdmin: true,
      }),
    ).toBe(true);
  });
});

describe("what the banner says", () => {
  test("nothing at all when the subscription is in good standing", () => {
    expect(subscriptionProblem(SubscriptionStatus.Active)).toBeNull();
  });

  test("a past-due subscription is named as a failed payment", () => {
    const problem = subscriptionProblem(SubscriptionStatus.PastDue);
    expect(problem?.headline).toMatch(/payment/i);
    expect(problem?.detail).toMatch(/payment/i);
  });

  test("an organisation that never subscribed is told so, not that it lapsed", () => {
    const problem = subscriptionProblem(null);
    expect(problem?.headline).toMatch(/no subscription/i);
    expect(problem?.detail).not.toMatch(/lapsed|ended/i);
  });

  test("an ended subscription is told it ended", () => {
    expect(subscriptionProblem(SubscriptionStatus.Deleted)?.headline).toMatch(
      /ended/i,
    );
  });

  test("no wording ever claims the clinic's data was deleted", () => {
    for (const status of [
      null,
      SubscriptionStatus.PastDue,
      SubscriptionStatus.Deleted,
    ]) {
      const problem = subscriptionProblem(status);
      expect(`${problem?.headline} ${problem?.detail}`).not.toMatch(
        /deleted|erased|removed/i,
      );
    }
  });
});

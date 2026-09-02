import { useState } from "react";
import { useSearchParams } from "react-router";
import {
  generateCheckoutSession,
  openCustomerPortal,
} from "wasp/client/operations";
import { OrgShell, type Org } from "../client/OrgShell";
import { Button } from "../client/components/ui/button";
import { subscriptionProblem } from "./entitlement";
import {
  PaymentPlanId,
  PLAN_FEATURES,
  PLAN_PRICE_TEXT,
  prettyPaymentPlanName,
  SubscriptionStatus,
} from "./plans";

/**
 * One clinic's subscription: what it is, and the two buttons that change it.
 *
 * Nothing on this page decides anything — Stripe does, and its webhook writes
 * the result. What is shown is therefore what Stripe last said, never what the
 * portal hopes happened after a click.
 */

const STATUS_WORDING: Record<string, string> = {
  [SubscriptionStatus.Active]: "Subscribed",
  [SubscriptionStatus.Trialing]: "In trial",
  [SubscriptionStatus.CancelAtPeriodEnd]:
    "Subscribed, ending at the end of this billing period",
  [SubscriptionStatus.PastDue]:
    "Past due — the last payment did not go through",
  [SubscriptionStatus.Deleted]: "Ended",
};

export function BillingPage() {
  return (
    <OrgShell title="Billing" requiresSubscription={false}>
      {(org) => <Billing org={org} />}
    </OrgShell>
  );
}

function Billing({ org }: { org: Org }) {
  const [searchParams] = useSearchParams();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const checkout = searchParams.get("checkout");
  const isOwner = org.role === "OWNER";
  const status = org.subscriptionStatus;
  const state = status
    ? STATUS_WORDING[status] ?? status
    : "No subscription yet";
  const lapse = subscriptionProblem(status);

  async function subscribe() {
    setBusy(true);
    setProblem(null);
    try {
      const session = await generateCheckoutSession({
        organizationId: org.id,
      });
      if (!session.sessionUrl) {
        throw new Error("Stripe did not return a checkout link.");
      }
      window.open(session.sessionUrl, "_self");
    } catch (error: unknown) {
      setProblem(
        error instanceof Error
          ? error.message
          : "The checkout could not be started. Please try again.",
      );
      setBusy(false);
    }
  }

  async function manage() {
    setBusy(true);
    setProblem(null);
    try {
      const url = await openCustomerPortal({ organizationId: org.id });
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (error: unknown) {
      setProblem(
        error instanceof Error
          ? error.message
          : "The billing portal could not be opened. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      {checkout === "canceled" && (
        <p
          data-testid="checkout-canceled"
          className="border-border rounded-md border p-4 text-sm"
        >
          The checkout was cancelled. Nothing has been charged.
        </p>
      )}
      {checkout === "success" && (
        <p
          data-testid="checkout-success"
          className="border-border rounded-md border p-4 text-sm"
        >
          Thank you. Stripe confirms the subscription in a moment; this page
          shows it as soon as it does.
        </p>
      )}

      <section className="border-border rounded-lg border p-6">
        <h2 className="text-foreground text-lg font-semibold">
          {prettyPaymentPlanName(PaymentPlanId.FrontDesk)}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {PLAN_PRICE_TEXT} per month, per clinic.
        </p>
        <p className="text-muted-foreground mt-4 text-xs uppercase">Status</p>
        <p
          data-testid="subscription-state"
          className="text-foreground mt-1 text-base font-medium"
        >
          {state}
        </p>
        {lapse && (
          <p className="text-muted-foreground mt-2 text-sm">{lapse.detail}</p>
        )}

        <ul className="text-muted-foreground mt-6 space-y-2 text-sm">
          {PLAN_FEATURES.map((feature) => (
            <li key={feature}>{feature}</li>
          ))}
        </ul>

        {problem && (
          <p
            data-testid="billing-problem"
            className="border-border text-foreground mt-6 rounded-md border p-4 text-sm"
          >
            {problem}
          </p>
        )}

        {isOwner ? (
          <div className="mt-6 flex flex-wrap gap-3">
            {lapse?.action !== "manage" && (
              <Button onClick={subscribe} disabled={busy}>
                Subscribe
              </Button>
            )}
            {org.hasStripeCustomer && (
              <Button variant="outline" onClick={manage} disabled={busy}>
                Manage subscription
              </Button>
            )}
          </div>
        ) : (
          <p className="text-muted-foreground mt-6 text-sm">
            Only an owner of {org.name} can change the subscription.
          </p>
        )}
      </section>
    </div>
  );
}

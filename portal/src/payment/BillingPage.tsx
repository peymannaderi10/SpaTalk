import {
  IconCheck,
  IconCreditCard,
  IconExternalLink,
} from "@tabler/icons-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import {
  generateCheckoutSession,
  openCustomerPortal,
} from "wasp/client/operations";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "../client/components/ui/alert";
import { Badge } from "../client/components/ui/badge";
import { Button } from "../client/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../client/components/ui/card";
import { Separator } from "../client/components/ui/separator";
import { OrgShell, type Org } from "../client/OrgShell";
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
 *
 * The kit has no billing page, so this is composed in its idiom: the section
 * card of `src/features/settings` with the plan in it, its header, its
 * description and its footer of actions.
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
    <OrgShell
      title="Billing"
      description="What this clinic pays for, and how to change it."
      requiresSubscription={false}
    >
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
    <div className="max-w-2xl space-y-4">
      {checkout === "canceled" && (
        <Alert data-testid="checkout-canceled">
          <AlertTitle>The checkout was cancelled</AlertTitle>
          <AlertDescription>Nothing has been charged.</AlertDescription>
        </Alert>
      )}
      {checkout === "success" && (
        <Alert data-testid="checkout-success">
          <AlertTitle>Thank you</AlertTitle>
          <AlertDescription>
            Stripe confirms the subscription in a moment; this page shows it as
            soon as it does.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <CardTitle className="text-lg">
                {prettyPaymentPlanName(PaymentPlanId.FrontDesk)}
              </CardTitle>
              <CardDescription>
                {PLAN_PRICE_TEXT} per month, per clinic.
              </CardDescription>
            </div>
            <Badge variant={lapse ? "outline" : "secondary"}>
              <IconCreditCard className="size-3" />
              {status ?? "not subscribed"}
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div>
            <p className="text-muted-foreground text-xs uppercase">Status</p>
            <p
              data-testid="subscription-state"
              className="text-foreground mt-1 text-base font-medium"
            >
              {state}
            </p>
            {lapse && (
              <p className="text-muted-foreground mt-2 text-sm">
                {lapse.detail}
              </p>
            )}
          </div>

          <Separator />

          <ul className="space-y-2 text-sm">
            {PLAN_FEATURES.map((feature) => (
              <li key={feature} className="flex items-start gap-2">
                <IconCheck className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                <span className="text-muted-foreground">{feature}</span>
              </li>
            ))}
          </ul>

          {problem && (
            <Alert variant="destructive" data-testid="billing-problem">
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}
        </CardContent>

        <CardFooter className="flex flex-wrap gap-3">
          {isOwner ? (
            <>
              {lapse?.action !== "manage" && (
                <Button onClick={subscribe} disabled={busy}>
                  Subscribe
                </Button>
              )}
              {org.hasStripeCustomer && (
                <Button variant="outline" onClick={manage} disabled={busy}>
                  Manage subscription
                  <IconExternalLink className="size-4" />
                </Button>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-sm">
              Only an owner of {org.name} can change the subscription.
            </p>
          )}
        </CardFooter>
      </Card>
    </div>
  );
}

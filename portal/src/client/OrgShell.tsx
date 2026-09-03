import { type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { getOrganization, useQuery } from "wasp/client/operations";
import { subscriptionProblem } from "../payment/entitlement";
import { OrgAppLayout } from "./layout/OrgAppLayout";

/**
 * The frame every client page sits in: the organisation it is about, the app
 * shell it is navigated from, and the one place a refusal is turned into a
 * sentence instead of a blank screen.
 *
 * The navigation used to be a strip of links above the page. It is now the
 * sidebar `OrgAppLayout` mounts, built from `nav.ts`, so a page added to the
 * Wasp spec cannot quietly become unreachable.
 */

export type Org = {
  id: string;
  name: string;
  slug: string;
  runtimeTenantId: string;
  role: "OWNER" | "STAFF";
  subscriptionStatus: string | null;
  /** Whether Stripe has ever billed this organisation. */
  hasStripeCustomer: boolean;
  /**
   * Whether this viewer may open the pages that need a subscription. The
   * server decides it — an agency admin is entitled to every organisation —
   * and the page only obeys, so the banner and the refusal always agree.
   */
  entitled: boolean;
};

export function OrgShell({
  title,
  requiresSubscription = true,
  children,
}: {
  title: string;
  /** False for the pages a clinic keeps without a subscription. */
  requiresSubscription?: boolean;
  children: (org: Org) => ReactNode;
}) {
  const { orgSlug = "" } = useParams();
  const {
    data: org,
    isLoading,
    error,
  } = useQuery(getOrganization, {
    slug: orgSlug,
  });

  if (isLoading) {
    return (
      <Frame title={title} slug={orgSlug}>
        <p className="text-muted-foreground text-sm">Loading…</p>
      </Frame>
    );
  }

  if (error || !org) {
    return (
      <Frame title={title} slug={orgSlug}>
        <p className="text-muted-foreground text-sm">
          {error?.message ??
            "This organisation is not open to you. Ask an owner for an invitation."}
        </p>
        <p className="mt-6 text-sm">
          <Link className="underline" to="/app">
            Back to your organisations
          </Link>
        </p>
      </Frame>
    );
  }

  const closed = !org.entitled;

  return (
    <Frame title={title} slug={org.slug} org={org}>
      {closed && <SubscriptionBanner org={org} />}
      {closed && requiresSubscription ? null : children(org)}
    </Frame>
  );
}

/**
 * Why a page is closed, and what the owner can do about it. It never says the
 * clinic's data is gone: a lapsed subscription closes the door, it does not
 * empty the room.
 */
export function SubscriptionBanner({ org }: { org: Org }) {
  const problem = subscriptionProblem(org.subscriptionStatus);
  if (!problem) {
    return null;
  }

  return (
    <div
      data-testid="subscription-required"
      className="border-border mb-8 rounded-md border p-4"
    >
      <p className="text-foreground text-sm font-medium">{problem.headline}</p>
      <p className="text-muted-foreground mt-1 text-sm">{problem.detail}</p>
      <p className="mt-3 text-sm">
        {org.role === "OWNER" ? (
          <Link className="underline" to={`/app/${org.slug}/billing`}>
            {problem.action === "manage"
              ? "Update the payment method"
              : "Subscribe this organisation"}
          </Link>
        ) : (
          `Ask an owner of ${org.name} to sort out the subscription.`
        )}
      </p>
    </div>
  );
}

function Frame({
  title,
  slug,
  org,
  children,
}: {
  title: string;
  slug: string;
  org?: Org;
  children: ReactNode;
}) {
  return (
    <OrgAppLayout
      orgSlug={slug}
      orgName={org?.name}
      role={org?.role}
      breadcrumbs={[{ label: title }]}
    >
      <h1 className="text-foreground text-2xl font-semibold">{title}</h1>
      <div className="mt-8">{children}</div>
    </OrgAppLayout>
  );
}

/** A refusal or an outage, said in one line rather than shown as a stack. */
export function Problem({ error }: { error: { message?: string } | null }) {
  if (!error) {
    return null;
  }
  return (
    <p
      data-testid="page-problem"
      className="border-border text-foreground mt-4 rounded-md border p-4 text-sm"
    >
      {error.message ?? "Something went wrong."}
    </p>
  );
}

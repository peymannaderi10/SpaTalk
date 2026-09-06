import { IconAlertTriangle } from "@tabler/icons-react";
import { type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { getOrganization, useQuery } from "wasp/client/operations";
import { subscriptionProblem } from "../payment/entitlement";
import { PageHeader } from "./components/page-header";
import { Alert, AlertDescription, AlertTitle } from "./components/ui/alert";
import { OrgAppLayout } from "./layout/OrgAppLayout";
import { cn } from "./utils";

/**
 * The frame every client page sits in: the organisation it is about, the app
 * shell it is navigated from, and the one place a refusal is turned into a
 * sentence instead of a blank screen.
 *
 * The navigation used to be a strip of links above the page. It is now the
 * sidebar `OrgAppLayout` mounts, built from `nav.ts`, so a page added to the
 * Wasp spec cannot quietly become unreachable.
 *
 * Inside the shell the page opens with the kit's page header — title, a line
 * saying what the page is for, and the page's primary buttons — and lays its
 * content out in the kit's column (`src/features/tasks/index.tsx` in
 * `satnaing/shadcn-admin`).
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
  /**
   * The clinic's branding, from `getOrganization`: the logo the owner uploaded
   * as a `data:` URL, the theme preset (`clinic` when null) and the accent
   * that overrides the preset's primary colour. The shell wears it; the
   * Branding page edits it. Null all round means the kit's own look.
   */
  logoDataUrl: string | null;
  themePreset: string | null;
  accentHex: string | null;
};

export function OrgShell({
  title,
  description,
  actions,
  requiresSubscription = true,
  fixed,
  fluid,
  children,
}: {
  title: string;
  /** One line under the title, in the kit's page header. */
  description?: ReactNode;
  /** The page's primary buttons, at the end of the header row. */
  actions?: ReactNode;
  /** False for the pages a clinic keeps without a subscription. */
  requiresSubscription?: boolean;
  /** The page fills the shell and scrolls inside itself: what a table wants. */
  fixed?: boolean;
  /** Drop the reading-width cap: what a wall of cards wants. */
  fluid?: boolean;
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
      <Frame title={title} description={description} slug={orgSlug}>
        <p className="text-muted-foreground text-sm">Loading…</p>
      </Frame>
    );
  }

  if (error || !org) {
    return (
      <Frame title={title} description={description} slug={orgSlug}>
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
    <Frame
      title={title}
      description={description}
      actions={closed && requiresSubscription ? undefined : actions}
      slug={org.slug}
      org={org}
      fixed={fixed}
      fluid={fluid}
    >
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
    <Alert data-testid="subscription-required">
      <IconAlertTriangle />
      <AlertTitle>{problem.headline}</AlertTitle>
      <AlertDescription>
        <p>{problem.detail}</p>
        <p>
          {org.role === "OWNER" ? (
            <Link
              className="underline underline-offset-4"
              to={`/app/${org.slug}/billing`}
            >
              {problem.action === "manage"
                ? "Update the payment method"
                : "Subscribe this organisation"}
            </Link>
          ) : (
            `Ask an owner of ${org.name} to sort out the subscription.`
          )}
        </p>
      </AlertDescription>
    </Alert>
  );
}

function Frame({
  title,
  description,
  actions,
  slug,
  org,
  fixed,
  fluid,
  children,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  slug: string;
  org?: Org;
  fixed?: boolean;
  fluid?: boolean;
  children: ReactNode;
}) {
  return (
    <OrgAppLayout
      orgSlug={slug}
      orgName={org?.name}
      role={org?.role}
      breadcrumbs={[{ label: title }]}
      fixed={fixed}
      fluid={fluid}
    >
      <div
        className={cn(
          "flex flex-1 flex-col gap-4 sm:gap-6",
          // A fixed page scrolls inside itself, and a flex child only shrinks
          // to let that happen once its own overflow is clipped.
          fixed && "overflow-hidden",
        )}
      >
        <PageHeader title={title} description={description} actions={actions} />
        {children}
      </div>
    </OrgAppLayout>
  );
}

/** A refusal or an outage, said in one line rather than shown as a stack. */
export function Problem({ error }: { error: { message?: string } | null }) {
  if (!error) {
    return null;
  }
  return (
    <Alert variant="destructive" data-testid="page-problem">
      <IconAlertTriangle />
      <AlertDescription>
        {error.message ?? "Something went wrong."}
      </AlertDescription>
    </Alert>
  );
}

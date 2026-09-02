import { type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { type AuthUser } from "wasp/auth";
import { getOrganization, useQuery } from "wasp/client/operations";

/**
 * The landing page for one organisation. Overview, conversations, requests
 * and tenant settings hang off this path once they are backed by the runtime.
 */
export function OrgHomePage({ user }: { user: AuthUser }) {
  const { orgSlug = "" } = useParams();
  const {
    data: org,
    isLoading,
    error,
  } = useQuery(getOrganization, { slug: orgSlug });

  if (isLoading) {
    return <PageShell>Loading…</PageShell>;
  }

  if (error || !org) {
    return (
      <PageShell>
        <h1 className="text-foreground text-2xl font-semibold">
          This organisation is not open to you
        </h1>
        <p className="text-muted-foreground mt-4 text-sm">
          {error?.message ??
            "Ask an owner of the organisation for an invitation."}
        </p>
        <p className="mt-6 text-sm">
          <Link className="underline" to="/app">
            Back to your organisations
          </Link>
        </p>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <h1 className="text-foreground text-2xl font-semibold">{org.name}</h1>
      <dl className="text-muted-foreground mt-6 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
        <Fact label="Your role" value={org.role} />
        <Fact label="Runtime tenant" value={org.runtimeTenantId} />
        <Fact label="People" value={String(org.members.length)} />
      </dl>
      <nav className="mt-8 flex flex-wrap gap-4 text-sm">
        <Link className="underline" to={`/app/${org.slug}/overview`}>
          Overview
        </Link>
        <Link className="underline" to={`/app/${org.slug}/conversations`}>
          Conversations
        </Link>
        <Link className="underline" to={`/app/${org.slug}/requests`}>
          Requests
        </Link>
        <Link className="underline" to={`/app/${org.slug}/settings`}>
          Settings
        </Link>
      </nav>

      <p className="text-muted-foreground mt-6 text-sm">
        Signed in as {user.email ?? user.id}.
      </p>
      {org.role === "OWNER" && (
        <p className="mt-6 text-sm">
          <Link className="underline" to={`/app/${org.slug}/settings/people`}>
            Manage who is in this organisation
          </Link>
        </p>
      )}
    </PageShell>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-border rounded-lg border p-4">
      <dt className="text-muted-foreground text-xs uppercase">{label}</dt>
      <dd className="text-foreground mt-1 text-base font-medium">{value}</dd>
    </div>
  );
}

function PageShell({ children }: { children: ReactNode }) {
  return <main className="mx-auto max-w-3xl px-6 py-16">{children}</main>;
}
